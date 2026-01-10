import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import re
from datetime import datetime
from gspread_formatting import *

st.set_page_config(page_title="GLOBO Master Dashboard", layout="wide")

# --- 1. GENERATE MONTH LIST ---
def get_month_options():
    start_date = datetime(2024, 4, 1)
    end_date = datetime(2026, 12, 1)
    options = pd.date_range(start=start_date, end=end_date, freq='MS').strftime('%b_%Y').tolist()
    return options[::-1]

# --- UI HEADER ---
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
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
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

        merged = pd.merge(shop_df, sr_grouped, on='Match_ID', how='left')

        # --- REPORT LOGIC ---
        report_df = merged.copy()
        report_df['Secondary Status'] = report_df['Override Shipping Status'] if 'Override Shipping Status' in report_df.columns else ""
        
        if 'Override Payment Method' in report_df.columns:
            report_df['Payment Method'] = report_df.apply(
                lambda row: f"{row['Override Payment Method']} (O)" if str(row['Override Payment Method']).strip() != "" else row['Payment Method'], axis=1
            )

        report_mapping = {'Status': 'Delivery Status'}
        final_report = report_df.rename(columns=report_mapping)
        cols_to_keep = [
            'Name', 'Created at', 'Financial Status', 'Fulfillment Status', 'Currency', 
            'Subtotal', 'Shipping', 'Taxes', 'Total', 'Shipping Method', 
            'Lineitem quantity', 'Lineitem name', 'Outstanding Balance', 'Tax 1 Name', 
            'Tax 1 Value', 'Billing Province Name', 'Shipping Province Name', 
            'Lineitem price', 'Payment Method', 'Lineitem fulfillment status', 
            'Delivery Status', 'Secondary Status'
        ]
        final_report = final_report[[c for c in cols_to_keep if c in final_report.columns]]

        # --- DASHBOARD VIEW ---
        if 'Override Shipping Status' in merged.columns:
            merged['Status'] = merged.apply(
                lambda row: f"{row['Override Shipping Status']} (O)" if str(row['Override Shipping Status']).strip() != "" else row['Status'], axis=1
            )

        dashboard_df = merged.rename(columns={'Name': 'Order ID (Shopify)', 'Order ID': 'Shiprocket Order ID', 'Status': 'Shipping Status', 'Shipping': 'Shipping Revenue', 'Total': 'Total Revenue'})
        requested_view = ['Order ID (Shopify)', 'Shiprocket Order ID', 'AWB Number', 'Shipping Status', 'Subtotal', 'Shipping Revenue', 'Taxes', 'Total Revenue', 'Shipping Method', 'Payment Method']
        
        return dashboard_df[[c for c in requested_view if c in dashboard_df.columns]], final_report, client
    
    except Exception as e:
        st.error(f"Error: {e}")
        return None, None, None

# --- DISPLAY ---
st.info(f"Viewing Month: **{selected_month.replace('_', ' ')}**")
df, report_data, gc = get_master_data(selected_month)

if df is not None:
    # Calculations (Metric Section remains exactly same as requested)
    df['Total Revenue'] = pd.to_numeric(df['Total Revenue'], errors='coerce').fillna(0)
    is_delivered = df['Shipping Status'].str.contains('Delivered', case=False, na=False)
    delivered_df = df[is_delivered]
    
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Shopify Total Orders", len(df))
    m2.metric("Total Revenue", f"₹{df['Total Revenue'].sum():,.2f}")
    m3.metric("Delivered Orders", len(delivered_df))
    m4.metric("Realised Revenue", f"₹{delivered_df['Total Revenue'].sum():,.2f}")
    m5.metric("Delivery %", f"{(len(delivered_df)/len(df)*100):.1f}%" if len(df)>0 else "0%")

    st.write("**Realised Revenue by Payment Method (Delivered Only):**")
    pay_methods = delivered_df.groupby('Payment Method')['Total Revenue'].sum().to_dict()
    p_cols = st.columns(len(pay_methods) if pay_methods else 1)
    for i, (method, amt) in enumerate(pay_methods.items()):
        with p_cols[i]:
            st.caption(f"{method}"); st.write(f"₹{amt:,.2f}")

    st.divider()
    st.dataframe(df, use_container_width=True, hide_index=True)

    # --- NEW GOOGLE SHEETS REPORT BUTTON ---
    st.subheader("📑 Detailed 22-Column Report")
    if st.button("🚀 Create & Open Report in Google Sheets"):
        with st.spinner("Generating formatted Google Sheet..."):
            # 1. Create Spreadsheet
            new_sh = gc.create(f"Globo_Report_{selected_month}_{datetime.now().strftime('%H%M%S')}")
            # 2. Share with your email (replace with your actual email if needed)
            # new_sh.share('your-email@gmail.com', perm_type='user', role='writer')
            new_sh.share('', perm_type='anyone', role='writer') # Link sharing enabled
            
            worksheet = new_sh.get_worksheet(0)
            worksheet.update([report_data.columns.values.tolist()] + report_data.values.tolist())
            
            # 3. Apply Row Highlighting Logic
            status_col_idx = report_data.columns.get_loc("Delivery Status") + 1
            fmt_rules = []
            
            for i, status in enumerate(report_data["Delivery Status"]):
                row_num = i + 2
                color = None
                status_str = str(status).upper()
                
                if "CANCELLED" in status_str:
                    color = Color(1, 0.898, 0.6) # #ffe599
                elif "RTO" in status_str:
                    color = Color(1, 0, 0) # #ff0000
                elif "DELIVERED" not in status_str and status_str != "":
                    color = Color(1, 0, 1) # #ff00ff
                
                if color:
                    fmt_rules.append((f"A{row_num}:V{row_num}", cellFormat(backgroundColor=color)))

            if fmt_rules:
                format_cell_ranges(worksheet, fmt_rules)
            
            st.success("Report Created Successfully!")
            st.link_button("🔗 Click Here to Open Google Sheet", new_sh.url)

else:
    st.warning("Data not found for selected month.")
