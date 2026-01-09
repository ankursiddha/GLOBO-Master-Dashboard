import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import re

st.set_page_config(page_title="GLOBO Master Dashboard", layout="wide")

def get_master_data():
    try:
        # 1. Fetch Secrets
        creds_dict = st.secrets["gcp_service_account"].to_dict()
        
        # 2. FORCE CLEAN the Private Key
        # This regex removes any character that is NOT part of a standard Base64 key
        raw_key = creds_dict["private_key"]
        header = "-----BEGIN PRIVATE KEY-----"
        footer = "-----END PRIVATE KEY-----"
        
        # Isolate the base64 content only
        key_body = raw_key.replace(header, "").replace(footer, "")
        clean_body = re.sub(r'[^A-Za-z0-9+/=]', '', key_body)
        
        # Re-wrap properly with single newlines
        creds_dict["private_key"] = f"{header}\n{clean_body}\n{footer}\n"
        
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        
        # 3. Connect to Sheets (IDs verified from your URLs)
        sr_id = "1l7UDY3BFEgxlSmwejfUU6XgbP1k8OOyq5cCJmVNXyuE"
        shop_id = "1mYk3sh2U9lucFkwoFU-v7dIpdGeiYtYcQrINp--NoU4"
        
        # Load Shiprocket (Jan_2026) and Shopify (Aug_2025)
        sr_df = pd.DataFrame(client.open_by_key(sr_id).worksheet("Jan_2026").get_all_records())
        shop_df = pd.DataFrame(client.open_by_key(shop_id).worksheet("Aug_2025").get_all_records())
        
        # 4. Merge
        shop_df['Name'] = shop_df['Name'].astype(str).str.strip()
        sr_df['Order ID'] = sr_df['Order ID'].astype(str).str.strip()
        
        return pd.merge(shop_df, sr_df, left_on='Name', right_on='Order ID', how='inner')
        
    except Exception as e:
        st.error(f"Sync Error: {e}")
        return None

st.title("📊 GLOBO Master Dashboard")
df = get_master_data()

if df is not None:
    st.success(f"Dashboard Synced: {len(df)} orders active.")
    st.dataframe(df, use_container_width=True)
