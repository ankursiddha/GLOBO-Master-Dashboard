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
    # Showing options up to end of 2026
    end_date = datetime(2026, 12, 1)
    options = pd.date_range(start=start_date, end=end_date, freq='MS').strftime('%b_%Y').tolist()
    return options[::-1] # Latest first

st.sidebar.title("📅 Dashboard Filters")
selected_month = st.sidebar.selectbox("Select Month", get_month_options())

def get_master_data(month_tab):
    try:
        # Secrets Setup
        creds_dict = st.secrets["gcp_service_account"].to_dict()
        raw_key = creds_dict["private_key"]
        header, footer = "-----BEGIN PRIVATE KEY-----", "-----END PRIVATE KEY-----"
        if header in raw_key:
            content = re.sub(r'[^A-Za-z0-9+/=]', '', raw_key.split(header)[1].split(footer)[0])
            creds_dict["private_key"] = f"{header}\n{content}\n{footer}\n"
        
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        
        # 2. Load Shopify (Master Source)
        shop_id = "1mYk3sh2U9lucFkwoFU-v7dIpdGeiYtYcQrINp--NoU4"
        shop_df = pd.DataFrame(client.open_by_key(shop_id).worksheet(month_tab).get_all_records())
        
        # 3. Load Shiprocket
        sr_id = "1l7UDY3BFEgxlSmwejfUU6XgbP1k8OOyq5cCJmVNXyuE"
        sr_df = pd.DataFrame(client.open_by_key(sr_id).worksheet(month_tab).get_all_records())

        # --- 4. DATA MERGING ---
        # Cleaning IDs for matching
        shop_df['Name'] = shop_df['Name'].astype(str).str.strip()
        sr_df['Order ID'] = sr_df['Order ID'].astype(str).str.strip()
        
        # We perform a LEFT JOIN: Shopify is the Master.
        # We bring in 'AWB Number' and 'Status' from Shiprocket.
        merged = pd.merge(
            shop_df, 
            sr_df[['Order ID', 'AWB Number', 'Status']], 
            left_on='Name', 
            right_on='Order ID', 
            how='left'
        )

        # Rename columns to match your request
        column_mapping = {
            'Name': 'Order ID (Shopify)',
            'AWB Number': 'AWB Number',
            'Status': 'Shipping Status',
            'Subtotal': 'Subtotal',
            'Shipping': 'Shipping Revenue',
            'Taxes': 'Taxes',
            'Total': 'Total Revenue',
            'Shipping Method': 'Shipping Method',
            'Payment Method': 'Payment Method'
        }
        
        # Filter and Rename for final display
        final_df = merged.rename(columns=column_mapping)
        
        # Ensure only the columns you asked for are shown
        requested_view = [
            'Order ID (Shopify)', 'AWB Number', 'Shipping Status', 'Subtotal', 
            'Shipping Revenue', 'Taxes', 'Total Revenue', 'Shipping Method', 'Payment Method'
        ]
        
        # Only display columns if they exist in the sheet
        final_view_cols = [c for c in requested_view if c in final_df.columns]
        
        return final_df[final_view_cols]
    
    except Exception as e:
        st.error(f"Error connecting to sheets: {e}")
        return None

# --- 5. DISPLAY ---
st.title(f"📊 GLOBO Master Dashboard")
st.info(f"Viewing Month: **{selected_month.replace('_', ' ')}**")

df = get_master_data(selected_month)

if df is not None:
    # Key Metrics
    m1, m2, m3 = st.columns(3)
    
    total_rev = pd.to_numeric(df['Total Revenue'], errors='coerce').sum()
    m1.metric("Shopify Total Orders", len(df))
    m2.metric("Total Revenue", f"₹{total_rev:,.2f}")
    
    if 'Shipping Status' in df:
        delivered_count = len(df[df['Shipping Status'].str.contains('Delivered', case=False, na=False)])
        m3.metric("Delivered Orders", delivered_count)

    st.divider()
    
    # Table Display
    st.dataframe(df, use_container_width=True, hide_index=True)
    
    # CSV Download Button
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download This Month's Report", csv, f"Globo_{selected_month}.csv", "text/csv")

else:
    st.warning(f"Could not find tab '{selected_month}' in the sheets. Please verify the tab names match exactly.")
