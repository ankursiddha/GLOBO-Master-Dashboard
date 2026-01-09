import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="GLOBO Master Dashboard", layout="wide")

def get_data():
    try:
        # Use the standard streamlit secrets access
        creds_info = st.secrets["gcp_service_account"]
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scope)
        client = gspread.authorize(creds)
        
        # 1. Shiprocket Data
        sr_sheet_id = "1l7UDY3BFEgxlSmwejfUU6XgbP1k8OOyq5cCJmVNXyuE"
        sr_df = pd.DataFrame(client.open_by_key(sr_sheet_id).worksheet("Dec_2025").get_all_records())
        
        # 2. Shopify Data 
        # Please ensure this ID is correct for your Shopify_Orders_2026 sheet
        shop_sheet_id = "1O_vG8F6m9Cq8xX6Wp9nN-k_hP2A7YpWv-hR9xK6m9oE" 
        shop_df = pd.DataFrame(client.open_by_key(shop_sheet_id).worksheet("Aug_2025").get_all_records())
        
        # Data Cleaning for Merge
        shop_df['Name'] = shop_df['Name'].astype(str).str.strip()
        sr_df['Order ID'] = sr_df['Order ID'].astype(str).str.strip()
        
        # Merging Shopify (Sales) + Shiprocket (Shipping)
        master_df = pd.merge(shop_df, sr_df, left_on='Name', right_on='Order ID', how='inner')
        return master_df
    
    except Exception as e:
        st.error(f"System Error: {e}")
        return None

st.title("📊 GLOBO Master Dashboard")

df = get_data()

if df is not None:
    st.success(f"BINGO! Successfully synced {len(df)} orders.")
    
    # Simple Metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Merged Orders", len(df))
    if 'Total' in df:
        m2.metric("Total Sales", f"₹{df['Total'].sum():,.2f}")
    if 'Status' in df:
        m3.metric("Delivered Orders", len(df[df['Status'].str.contains('delivered', case=False, na=False)]))

    st.subheader("Master Data View")
    st.dataframe(df, use_container_width=True)
else:
    st.info("Check if the Service Account has 'Editor' access to both Google Sheets.")
