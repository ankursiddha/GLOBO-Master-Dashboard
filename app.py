import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="GLOBO Master Dashboard", layout="wide")

@st.cache_data(ttl=600)
def get_master_data():
    try:
        # Load credentials from Streamlit Secrets
        creds_info = st.secrets["gcp_service_account"]
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scope)
        client = gspread.authorize(creds)
        
        # 1. Fetch Shiprocket Data (Shipping Details)
        # ID from URL: 1l7UDY3BFEgxlSmwejfUU6XgbP1k8OOyq5cCJmVNXyuE
        sr_id = "1l7UDY3BFEgxlSmwejfUU6XgbP1k8OOyq5cCJmVNXyuE"
        sr_df = pd.DataFrame(client.open_by_key(sr_id).worksheet("Jan_2026").get_all_records())
        
        # 2. Fetch Shopify Data (Sales Details)
        # ID from URL: 1mYk3sh2U9lucFkwoFU-v7dIpdGeiYtYcQrINp--NoU4
        shop_id = "1mYk3sh2U9lucFkwoFU-v7dIpdGeiYtYcQrINp--NoU4"
        shop_df = pd.DataFrame(client.open_by_key(shop_id).worksheet("Aug_2025").get_all_records())
        
        # 3. Clean and Merge
        shop_df['Name'] = shop_df['Name'].astype(str).str.strip()
        sr_df['Order ID'] = sr_df['Order ID'].astype(str).str.strip()
        
        # Inner join to combine Sales and Shipping info
        master_df = pd.merge(shop_df, sr_df, left_on='Name', right_on='Order ID', how='inner')
        return master_df
    except Exception as e:
        st.error(f"Connection failed: {e}")
        return None

st.title("📊 GLOBO Master Dashboard")
df = get_master_data()

if df is not None:
    st.success(f"Synced {len(df)} Orders from Shopify & Shiprocket")
    
    # Dashboard Metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Revenue", f"₹{df['Total'].sum():,.2f}")
    m2.metric("Delivered Orders", len(df[df['Status'] == 'Delivered']))
    m3.metric("RTO Count", len(df[df['Status'].str.contains('RTO', na=False)]))
    
    st.dataframe(df, use_container_width=True)
else:
    st.info("Check Secrets formatting and ensure 'Editor' access is shared with your Service Account.")
