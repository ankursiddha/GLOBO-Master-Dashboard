import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import re
from datetime import datetime

st.set_page_config(page_title="GLOBO Master Dashboard", layout="wide")

# --- 1. MONTH SELECTOR LOGIC ---
def get_month_options():
    start_date = datetime(2024, 4, 1)
    current_date = datetime.now()
    # Adding a buffer for future dates up to Dec 2026
    end_date = datetime(2026, 12, 1)
    
    options = pd.date_range(start=start_date, end=end_date, freq='MS').strftime('%b_%Y').tolist()
    return options[::-1] # Show latest months first

st.sidebar.title("📅 Dashboard Filters")
selected_month = st.sidebar.selectbox("Select Month", get_month_options())

def get_master_data(month_tab):
    try:
        creds_dict = st.secrets["gcp_service_account"].to_dict()
        # Clean the key (Same fix as before to avoid Base64 error)
        raw_key = creds_dict["private_key"]
        header, footer = "-----BEGIN PRIVATE KEY-----", "-----END PRIVATE KEY-----"
        if header in raw_key:
            content = re.sub(r'[^A-Za-z0-9+/=]', '', raw_key.split(header)[1].split(footer)[0])
            creds_dict["private_key"] = f"{header}\n{content}\n{footer}\n"
        
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        
        # --- 2. LOAD SHEETS ---
        # Shopify Master Sheet
        shop_id = "1mYk3sh2U9lucFkwoFU-v7dIpdGeiYtYcQrINp--NoU4"
        shop_df = pd.DataFrame(client.open_by_key(shop_id).worksheet(month_tab).get_all_records())
        
        # Shiprocket Shipping Sheet
        sr_id = "1l7UDY3BFEgxlSmwejfUU6XgbP1k8OOyq5cCJmVNXyuE"
        sr_df = pd.DataFrame(client.open_by_key(sr_id).worksheet(month_tab).get_all_records())

        # --- 3. DATA CLEANING & MERGE ---
        # Shopify ID is 'Name', Shiprocket is 'Order ID'
        shop_df['Name'] = shop_df['Name'].astype(str).str.strip()
        sr_df['Order ID'] = sr_df['Order ID'].astype(str).str.strip()
        
        # Merge using Shopify as the base (Left Join)
        merged = pd.merge(shop_df, sr_df[['Order ID', 'AWB Code', 'Status']], 
                          left_on='Name', right_on='Order ID', how='left')
        
        # --- 4. SELECT REQUESTED COLUMNS ---
        final_cols = [
            'Name', 'AWB Code', 'Status', 'Subtotal', 'Shipping', 
            'Taxes', 'Total', 'Shipping Method', 'Payment Method'
        ]
        
        # Only select columns that actually exist in the sheet to avoid errors
        available_cols = [c for c in final_cols if c in merged.columns]
        return merged[available_cols]
    
    except Exception as e:
        st.error(f"Error loading tab '{month_tab}': {e}")
        return None

# --- 4. DISPLAY DASHBOARD ---
st.title(f"📊 GLOBO Dashboard - {selected_month.replace('_', ' ')}")

df = get_master_data(selected_month)

if df is not None:
    # Top Metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Shopify Orders", len(df))
    m2.metric("Total Revenue", f"₹{df['Total'].sum():,.2f}" if 'Total' in df else "N/A")
    
    if 'Status' in df:
        delivered = len(df[df['Status'].str.contains('Delivered', case=False, na=False)])
        m3.metric("Delivered", delivered)
        m4.metric("Pending/RTO", len(df) - delivered)

    st.subheader("Order Master List")
    st.dataframe(df, use_container_width=True)
else:
    st.warning(f"Tab '{selected_month}' not found in one of the sheets. Please check the sheet tab names.")
