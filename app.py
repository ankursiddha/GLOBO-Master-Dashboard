import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# --- PAGE CONFIG ---
st.set_page_config(page_title="GLOBO Master Dashboard", layout="wide")

def get_data():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        creds_dict = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        
        # 1. Fetch Shiprocket Data (Shipping Details)
        sr_sheet = client.open_by_key("1l7UDY3BFEgxlSmwejfUU6XgbP1k8OOyq5cCJmVNXyuE")
        sr_df = pd.DataFrame(sr_sheet.worksheet("Dec_2025").get_all_records())
        
        # 2. Fetch Shopify Data (Sales Details)
        # REPLACE THE ID BELOW WITH YOUR Shopify_Orders_2026 SHEET ID
        shop_sheet = client.open_by_key("YOUR_SHOPIFY_SHEET_ID_HERE")
        shop_df = pd.DataFrame(shop_sheet.worksheet("Aug_2025").get_all_records())
        
        # 3. Data Cleaning
        # Ensure IDs are strings and stripped of spaces for a perfect match
        shop_df['Name'] = shop_df['Name'].astype(str).str.strip()
        sr_df['Order ID'] = sr_df['Order ID'].astype(str).str.strip()
        
        # 4. Merging the Data
        # We use an 'inner' join to see orders present in both systems
        master_df = pd.merge(shop_df, sr_df, left_on='Name', right_on='Order ID', how='inner')
        
        return master_df
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None

st.title("📊 GLOBO Master Dashboard")
st.markdown("### Integrated Shopify Sales & Shiprocket Shipping Data")

df = get_data()

if df is not None:
    # --- TOP LEVEL METRICS ---
    total_sales = df['Total'].sum() if 'Total' in df else 0
    total_orders = len(df)
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Revenue", f"₹{total_sales:,.2f}")
    m2.metric("Total Orders", total_orders)
    
    if 'Status' in df:
        delivered = len(df[df['Status'].str.contains('delivered', case=False, na=False)])
        m3.metric("Delivered", delivered)
        m4.metric("Delivery %", f"{(delivered/total_orders)*100:.1f}%" if total_orders > 0 else "0%")

    # --- DATA VISUALIZATION ---
    st.divider()
    
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.subheader("Payment Method Distribution")
        if 'Financial Status' in df:
            st.bar_chart(df['Financial Status'].value_counts())

    with col_right:
        st.subheader("Shipping Status Breakdown")
        if 'Status' in df:
            st.write(df['Status'].value_counts())

    # --- RAW DATA TABLE ---
    st.subheader("Detailed Master Table")
    st.dataframe(df, use_container_width=True)

else:
    st.info("Please ensure your Service Account has 'Editor' access to both Google Sheets.")
