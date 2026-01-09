import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="GLOBO Master Dashboard", layout="wide")

@st.cache_data(ttl=600)
def get_data():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        # Standard Streamlit way to load service account secrets
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        
        # 1. Shiprocket Data
        sr_id = "1l7UDY3BFEgxlSmwejfUU6XgbP1k8OOyq5cCJmVNXyuE"
        sr_df = pd.DataFrame(client.open_by_key(sr_id).worksheet("Dec_2025").get_all_records())
        
        # 2. Shopify Data - REPLACE WITH YOUR ACTUAL SHOPIFY SHEET ID
        shop_id = "REPLACE_THIS_WITH_YOUR_SHOPIFY_SHEET_ID" 
        shop_df = pd.DataFrame(client.open_by_key(shop_id).worksheet("Aug_2025").get_all_records())
        
        # Merge
        shop_df['Name'] = shop_df['Name'].astype(str).str.strip()
        sr_df['Order ID'] = sr_df['Order ID'].astype(str).str.strip()
        return pd.merge(shop_df, sr_df, left_on='Name', right_on='Order ID', how='inner')
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None

st.title("📊 GLOBO Master Dashboard")
master_df = get_data()

if master_df is not None:
    st.success(f"Connected! {len(master_df)} orders synchronized.")
    st.dataframe(master_df, use_container_width=True)
