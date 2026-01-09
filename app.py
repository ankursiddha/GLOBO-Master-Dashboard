import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# Dashboard Layout
st.set_page_config(page_title="GLOBO Master Dashboard", layout="wide")

def get_data():
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    # Secrets setup hum Streamlit Cloud par karenge
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    
    # Tumhari Sheet ID
    sheet = client.open_by_key("1l7UDY3BFEgxlSmwejfUU6XgbP1k8OOyq5cCJmVNXyuE")
    data = sheet.worksheet("Dec_2025").get_all_records()
    return pd.DataFrame(data)

st.title("📊 GLOBO Master Dashboard")

try:
    df = get_data()
    
    # Chhoti Summary (Metrics)
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Orders", len(df))
    col2.metric("Unique Customers", df['Customer'].nunique() if 'Customer' in df else "N/A")
    col3.metric("Latest Order Date", df['Created At'].max() if 'Created At' in df else "N/A")

    # Data Display
    st.subheader("Recent Dec 2025 Orders")
    st.dataframe(df, use_container_width=True)

except Exception as e:
    st.warning("Data loading... Dashboard setup hone ke baad yahan data dikhega.")
    st.info("Note: Abhi humein Streamlit Cloud par 'Secrets' (JSON Key) connect karna baaki hai.")
