import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import re
from datetime import datetime

st.set_page_config(page_title="GLOBO Master Dashboard", layout="wide")

# --- 1. GENERATE MONTH LIST (APR 2024 onwards) ---
def get_month_options():
    start_date = datetime(2024, 4, 1)
    end_date = datetime(2026, 12, 1)
    options = pd.date_range(start=start_date, end=end_date, freq='MS').strftime('%b_%Y').tolist()
    return options[::-1] # Latest first

# --- NEW FILTER SECTION (TOP RIGHT) ---
t1, t2 = st.columns([3, 1])
with t1:
    st.title(f"📊 GLOBO Master Dashboard")

with t2:
    years = ["2026", "2025", "2024"]
    months_short = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    
    f1, f2 = st.columns(2)
    sel_year = f1.selectbox("Year", years)
    sel_month = f2.selectbox("Month", months_short, index=datetime.now().month - 1)
    
    selected_month = f"{sel_month}_{sel_year}"

def get_master_data(month_tab):
    try:
        creds_dict = st.secrets["gcp_service_account"].to_dict()
        raw_key = creds_dict["private_key"]
        header, footer = "-----BEGIN PRIVATE KEY-----", "-----END PRIVATE KEY-----"
        if header in raw_key:
            content = re.sub(r'[^A-Za-z0-9+/=]', '', raw_key.split(header)[1].split(footer)[0])
            creds_dict["private_key"] = f"{header}\n{content}\n{footer}\n"
        
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        
        shop_id = "1mYk3sh2U9lucFkwoFU-v7dIpdGeiYtYcQrINp--NoU4"
        shop_df = pd.DataFrame(client.open_by_key(shop_id).worksheet(month_tab).get_all_records())
        
        sr_id = "1l7UDY3BFEgxlSmwejfUU6XgbP1k8OOyq5cCJmVNXyuE"
        sr_df = pd.DataFrame(client.open_by_key(sr_id).worksheet(month_tab).get_all_records())

        def extract_globo_id(s):
            match = re.search(r'(GLOBO\d+)', str(s).upper())
            return match.group(1) if match else str(s).strip()

        shop_df['Match_ID'] = shop_df['Name'].apply(extract_globo_id)
        sr_df['Match_ID'] = sr_df['Order ID'].apply(extract_globo_id)
        
        sr_grouped = sr_df.groupby('Match_ID').agg({
            'Order ID': lambda x: "\n".join(x.astype(str)),
            'AWB Number': lambda x: "\n".join(x.astype(str)),
            'Status': lambda x: "\n".join(x.astype(str))
        }).reset_index()

        merged = pd.merge(
            shop_df, 
            sr_grouped, 
            on='Match_ID', 
            how='left'
        )

        column_mapping = {
            'Name': 'Order ID (Shopify)',
            'Order ID': 'Shiprocket Order ID',
            'AWB Number': 'AWB Number',
            'Status': 'Shipping Status',
            'Subtotal': 'Subtotal',
            'Shipping': 'Shipping Revenue',
            'Taxes': 'Taxes',
            'Total': 'Total Revenue',
            'Shipping Method': 'Shipping Method',
            'Payment Method': 'Payment Method'
        }
        
        final_df = merged.rename(columns=column_mapping)
        
        requested_view = [
            'Order ID (Shopify)', 'Shiprocket Order ID', 'AWB Number', 'Shipping Status', 'Subtotal', 
            'Shipping Revenue', 'Taxes', 'Total Revenue', 'Shipping Method', 'Payment Method'
        ]
        
        final_view_cols = [c for c in requested_view if c in final_df.columns]
        
        return final_df[final_view_cols]
    
    except Exception as e:
        st.error(f"Error connecting to sheets: {e}")
        return None

# --- 5. DISPLAY ---
st.info(f"Viewing Month: **{selected_month.replace('_', ' ')}**")

df = get_master_data(selected_month)

if df is not None:
    # --- CALCULATIONS ---
    df['Total Revenue'] = pd.to_numeric(df['Total Revenue'], errors='coerce').fillna(0)
    total_orders = len(df)
    total_rev = df['Total Revenue'].sum()
    
    # Identify Delivered Orders
    is_delivered = df['Shipping Status'].str.contains('Delivered', case=False, na=False)
    delivered_df = df[is_delivered]
    delivered_count = len(delivered_df)
    realised_rev = delivered_df['Total Revenue'].sum()
    delivery_perc = (delivered_count / total_orders * 100) if total_orders > 0 else 0
    
    # Payment Method Wise Revenue (Delivered Only)
    pay_methods = delivered_df.groupby('Payment Method')['Total Revenue'].sum().to_dict()

    # --- TOP METRICS SECTION ---
    # Line 1: Main Stats
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Shopify Total Orders", total_orders)
    m2.metric("Total Revenue", f"₹{total_rev:,.2f}")
    m3.metric("Delivered Orders", delivered_count)
    m4.metric("Realised Revenue", f"₹{realised_rev:,.2f}")
    m5.metric("Delivery %", f"{delivery_perc:.1f}%")

    # Line 2: Payment Stats (Smaller Format)
    st.write("**Realised Revenue by Payment Method (Delivered Only):**")
    p_cols = st.columns(len(pay_methods) if pay_methods else 1)
    for i, (method, amt) in enumerate(pay_methods.items()):
        with p_cols[i]:
            st.caption(f"{method}")
            st.write(f"₹{amt:,.2f}")

    st.divider()
    
    # Table Display
    st.dataframe(
        df, 
        use_container_width=True, 
        hide_index=True,
        column_config={
            "Shiprocket Order ID": st.column_config.TextColumn(width="medium"),
            "AWB Number": st.column_config.TextColumn(width="medium"),
            "Shipping Status": st.column_config.TextColumn(width="medium"),
        }
    )
    
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download This Month's Report", csv, f"Globo_{selected_month}.csv", "text/csv")

else:
    st.warning(f"Could not find tab '{selected_month}' in the sheets. Please verify the tab names match exactly.")
