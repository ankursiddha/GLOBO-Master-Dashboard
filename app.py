import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import re

st.set_page_config(page_title="GLOBO Master Dashboard", layout="wide")

def get_data():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        
        # --- AUTO-FIX SECRETS ---
        creds_dict = st.secrets["gcp_service_account"].to_dict()
        
        # This line removes any hidden \n or spaces that cause the Base64 error
        raw_key = creds_dict["private_key"]
        creds_dict["private_key"] = raw_key.replace("\\n", "\n")
        
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        
        # 1. Shiprocket Data
        sr_sheet = client.open_by_key("1l7UDY3BFEgxlSmwejfUU6XgbP1k8OOyq5cCJmVNXyuE")
        sr_df = pd.DataFrame(sr_sheet.worksheet("Dec_2025").get_all_records())
        
        # 2. Shopify Data (Ensure this ID is your Shopify Sheet ID)
        # Verify the ID below is correct for your Shopify Sheet
        shop_sheet = client.open_by_key("1Xf_WfQnL4x6p8hYvR6Xk8hZp0Q6Rk8hZp0Q6Rk8hZp0") 
        shop_df = pd.DataFrame(shop_sheet.worksheet("Aug_2025").get_all_records())
        
        # Merge
        shop_df['Name'] = shop_df['Name'].astype(str).str.strip()
        sr_df['Order ID'] = sr_df['Order ID'].astype(str).str.strip()
        master_df = pd.merge(shop_df, sr_df, left_on='Name', right_on='Order ID', how='inner')
        
        return master_df
    except Exception as e:
        st.error(f"Error Details: {e}")
        return None

st.title("📊 GLOBO Master Dashboard")

df = get_data()

if df is not None:
    st.success("Successfully Merged Shopify & Shiprocket Data")
    st.metric("Total Merged Orders", len(df))
    st.dataframe(df, use_container_width=True)
else:
    st.info("Waiting for data connection... Please check the error message above.")
