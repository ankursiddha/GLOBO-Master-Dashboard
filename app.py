import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import re
from datetime import datetime
from io import BytesIO

st.set_page_config(page_title="GLOBO Master Dashboard", layout="wide")

# --- 1. GENERATE MONTH LIST (APR 2024 onwards) ---
def get_month_options():
    start_date = datetime(2024, 4, 1)
    end_date = datetime(2026, 12, 1)
    options = pd.date_range(start=start_date, end=end_date, freq='MS').strftime('%b_%Y').tolist()
    return options[::-1] # Latest first

# --- NEW FILTER SECTION (TOP RIGHT) ---
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
        raw_key = creds_dict["private_key"]
        header, footer = "-----BEGIN PRIVATE KEY-----", "-----END PRIVATE KEY-----"
        if header in raw_key:
            content = re.sub(r'[^A-Za-z0-9+/=]', '', raw_key.split(header)[1].split(footer)[0])
            creds_dict["private_key"] = f"{header}\n{content}\n{footer}\n"
        
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        
        shop_id = "1mYk3sh2U9lucFkwoFU-v7dIpdGeiYtYcQrINp--NoU4"
        shop_df = pd.DataFrame(client.open_by_key(shop_id).worksheet(month_tab).get_all_records())
        
        sr_id = "1l7UDY3BFEgxlSmwejfUU6XgbP1k8OOyq5cCJmVNXyuE"
        
        # --- NEW CROSS-MONTH LOGIC START ---
        sr_book = client.open_by_key(sr_id)
        all_sr_sheets = sr_book.worksheets()
        
        sr_list = []
        for sheet in all_sr_sheets:
            # Matches any tab with an underscore like "Jan_2025"
            if "_" in sheet.title:
                sheet_data = pd.DataFrame(sheet.get_all_records())
                if not sheet_data.empty:
                    sr_list.append(sheet_data)
        
        # Combine all months into one big search pool
        sr_df = pd.concat(sr_list, ignore_index=True) if sr_list else pd.DataFrame()
        # --- NEW CROSS-MONTH LOGIC END ---
        
        def extract_globo_id(s):
            match = re.search(r'(GLOBO\d+)', str(s).upper())
            return match.group(1) if match else str(s).strip()

        shop_df['Match_ID'] = shop_df['Name'].apply(extract_globo_id)
        sr_df['Match_ID'] = sr_df['Order ID'].apply(extract_globo_id)
        # 1. Standard grouping for the Dashboard (Keeps Dashboard exactly as it is now)
        sr_grouped = sr_df.groupby('Match_ID').agg({
            'Order ID': lambda x: "\n".join(x.astype(str).unique()),
            'AWB Number': lambda x: "\n".join(x.astype(str).unique()),
            'Status': lambda x: "\n".join(x.astype(str).unique())
        }).reset_index()

        # 2. CREATE SPECIAL LOGIC FOR DOWNLOAD REPORT ONLY
        def get_report_specific_status(match_id, current_sr_df):
            # Filter all Shiprocket rows related to this Match_ID (e.g., GLOBO1234)
            related_rows = current_sr_df[current_sr_df['Match_ID'] == match_id]
            
            # Logic for Case 1: GLOBO1234 and GLOBO1234-C / GLOBO1234-C1
            # Logic for Case 2: R_GLOBO1234 / R1_GLOBO1234
            # We look for ANY status containing "DELIVERED" in any related Shiprocket ID
            statuses = related_rows['Status'].astype(str).str.upper().tolist()
            
            if any("DELIVERED" in s for s in statuses):
                return "DELIVERED"
            
            # If no Delivered status found, return the combined raw statuses
            unique_stats = [s for s in related_rows['Status'].unique() if str(s).strip() != ""]
            return "\n".join(unique_stats) if unique_stats else "NOT DELIVERED"

        # Apply the special cases logic ONLY for the report data
        merged = pd.merge(shop_df, sr_grouped, on='Match_ID', how='left')
        
        # This column is used ONLY for the Excel Download logic
        merged['Report_Status_Fixed'] = merged['Match_ID'].apply(lambda x: get_report_specific_status(x, sr_df))

        # --- PREPARE 22-COLUMN REPORT DATA ---
        report_df = merged.copy()
        
        # 21 & 22: Status handling (Using the Fixed Status for the Report)
        report_df['Delivery Status'] = report_df['Report_Status_Fixed']
        report_df['Secondary Status'] = report_df['Override Shipping Status'] if 'Override Shipping Status' in report_df.columns else ""
        
        # Define the exact 22 columns requested
        report_cols = [
            'Name', 'Created at', 'Financial Status', 'Fulfillment Status', 'Currency',
            'Subtotal', 'Shipping', 'Taxes', 'Total', 'Shipping Method',
            'Lineitem quantity', 'Lineitem name', 'Outstanding Balance', 'Tax 1 Name',
            'Tax 1 Value', 'Billing Province Name', 'Shipping Province Name', 
            'Lineitem price', 'Payment Method', 'Lineitem fulfillment status',
            'Delivery Status', 'Secondary Status'
        ]
        # Filter columns that exist
        final_report_df = report_df[[c for c in report_cols if c in report_df.columns]]

        # --- DASHBOARD VIEW (Exactly as before) ---
        if 'Override Shipping Status' in merged.columns:
            merged['Status'] = merged.apply(
                lambda row: f"{row['Override Shipping Status']} (O)" if str(row['Override Shipping Status']).strip() != "" else row['Status'], 
                axis=1
            )
        if 'Override Payment Method' in merged.columns:
            merged['Payment Method'] = merged.apply(
                lambda row: f"{row['Override Payment Method']} (O)" if str(row['Override Payment Method']).strip() != "" else row['Payment Method'], 
                axis=1
            )

        column_mapping = {
            'Name': 'Order ID (Shopify)', 'Order ID': 'Shiprocket Order ID',
            'AWB Number': 'AWB Number', 'Status': 'Shipping Status',
            'Subtotal': 'Subtotal', 'Shipping': 'Shipping Revenue',
            'Taxes': 'Taxes', 'Total': 'Total Revenue',
            'Shipping Method': 'Shipping Method', 'Payment Method': 'Payment Method'
        }
        final_dash_df = merged.rename(columns=column_mapping)
        requested_view = ['Order ID (Shopify)', 'Shiprocket Order ID', 'AWB Number', 'Shipping Status', 'Subtotal', 'Shipping Revenue', 'Taxes', 'Total Revenue', 'Shipping Method', 'Payment Method']
        final_view_cols = [c for c in requested_view if c in final_dash_df.columns]
        
        return final_dash_df[final_view_cols], final_report_df
    
    except Exception as e:
        st.error(f"Error connecting to sheets: {e}")
        return None, None

# --- 5. DISPLAY ---
st.info(f"Viewing Month: **{selected_month.replace('_', ' ')}**")

df, report_df = get_master_data(selected_month)

if df is not None:
    # --- UPDATED CALCULATIONS (Matching Special Case Logic) ---
    df['Total Revenue'] = pd.to_numeric(df['Total Revenue'], errors='coerce').fillna(0)
    total_orders = len(df)
    total_rev = df['Total Revenue'].sum()
    
    # 1. We create a calculation status that checks the pool for DELIVERED
    # This ensures Case 1, 2, and 3 are reflected in your Metric Cards
    def check_delivered_logic(match_id, pool_df):
        related_stats = pool_df[pool_df['Match_ID'] == match_id]['Status'].astype(str).upper().tolist()
        return any("DELIVERED" in s for s in related_stats)

    # Apply the logic to find which Shopify Orders are "Logically Delivered"
    df['Is_Delivered_Logic'] = df['Order ID (Shopify)'].apply(lambda x: extract_globo_id(x)).apply(lambda m: check_delivered_logic(m, sr_df))
    
    delivered_df = df[df['Is_Delivered_Logic'] == True]
    delivered_count = len(delivered_df)
    realised_rev = delivered_df['Total Revenue'].sum()
    delivery_perc = (delivered_count / total_orders * 100) if total_orders > 0 else 0
    
    pay_methods = delivered_df.groupby('Payment Method')['Total Revenue'].sum().to_dict()
    # --- END OF UPDATED CALCULATIONS ---

    
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Shopify Total Orders", total_orders)
    m2.metric("Total Revenue", f"₹{total_rev:,.2f}")
    m3.metric("Delivered Orders", delivered_count)
    m4.metric("Realised Revenue", f"₹{realised_rev:,.2f}")
    m5.metric("Delivery %", f"{delivery_perc:.1f}%")

    st.write("**Realised Revenue by Payment Method (Delivered Only):**")
    p_cols = st.columns(len(pay_methods) if pay_methods else 1)
    for i, (method, amt) in enumerate(pay_methods.items()):
        with p_cols[i]:
            st.caption(f"{method}")
            st.write(f"₹{amt:,.2f}")

    st.divider()
    
    st.dataframe(df, use_container_width=True, hide_index=True)
    
    # --- STYLED REPORT DOWNLOAD LOGIC ---
    # --- UPDATED STYLED REPORT LOGIC ---
    def style_report(row):
        # We check the new 'Delivery Status' column we created for the report
        status = str(row['Delivery Status']).upper()
        
        # 1. If it's DELIVERED (including our special cases), keep it white/plain
        if "DELIVERED" in status:
            return [''] * len(row)
            
        # 2. Highlight Canceled orders in Yellow
        elif "CANCELED" in status or "CANCELLED" in status:
            return ['background-color: #ffe599'] * len(row)
            
        # 3. Highlight RTO in Red
        elif "RTO" in status:
            return ['background-color: #ff0000'] * len(row)
            
        # 4. Highlight anything else that isn't empty (In-Transit, etc.) in Magenta
        elif status.strip() != "" and status != "NAN":
            return ['background-color: #ff00ff'] * len(row)
            
        # 5. Default (Empty/Not Found)
        return [''] * len(row)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        report_df.style.apply(style_report, axis=1).to_excel(writer, index=False, sheet_name='Report')
    
    processed_data = output.getvalue()

    st.download_button(
        label="📥 Download This Month's Report",
        data=processed_data,
        file_name=f"Globo_Full_Report_{selected_month}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.warning(f"Could not find tab '{selected_month}' in the sheets.")
