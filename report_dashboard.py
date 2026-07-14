import streamlit as st
import pandas as pd
import numpy as np
import datetime
from supabase import create_client, Client

# --- PRODUCTION AUTHENTICATION ---
SUPABASE_URL = "https://wljftpkvsozgpxivbwiu.supabase.co"
SUPABASE_KEY = "sb_secret_60ve-Yh8xAvI6MZkhQQR3Q_Fk2mP9If"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="GLOBO Master Analytics Engine", layout="wide")

st.title("📊 GLOBO Master Report & Advanced Export Ledger")
st.subheader("⚡ High Performance Server-Cached Database Edition")

def fetch_prebuilt_ledger(start_iso, end_iso):
    """Fetches transactional data rows comprehensively from master_reporting_ledger."""
    all_rows = []
    chunk_size = 1000
    start_idx = 0
    
    while True:
        res = supabase.table("master_reporting_ledger") \
                      .select("*") \
                      .gte("Created at", start_iso) \
                      .lte("Created at", end_iso) \
                      .range(start_idx, start_idx + chunk_size - 1) \
                      .execute()
        
        data_chunk = res.data
        if not data_chunk:
            break
        all_rows.extend(data_chunk)
        if len(data_chunk) < chunk_size:
            break
        start_idx += chunk_size
        
    df = pd.DataFrame(all_rows)
    if not df.empty:
        df["created_at_dt"] = pd.to_datetime(df["Created at"], errors='coerce').dt.tz_localize(None)
    return df

def apply_hierarchical_excel_formatting(df):
    """
    Transforms fully filled database rows into a structured invoice style layout.
    Presents order level values ONLY on the first line, leaving sub-row columns blank.
    """
    if df.empty:
        return df

    # 1. Sort sequentially by original database timestamps (newest orders first)
    # Inside each order, sort by tracking/lineitem details to preserve sub-row pairing structure
    df = df.sort_values(by=["Created at", "shopify_lineitem_id", "shiprocket_shipment_id"], ascending=[False, True, True])

    # 2. Add an explicit sequential Serial Number sequence mapping to unique orders
    unique_orders = df["Name"].unique()
    order_to_serial = {name: float(idx + 1) for idx, name in enumerate(unique_orders)}
    df["Serial No"] = df["Name"].map(order_to_serial)

    # 3. Identify all structural master columns that must remain blank on sub-rows
    master_cols = [
        "Serial No", "Name", "Created at", "Financial Status", "Fulfillment Status", 
        "Currency", "Subtotal", "Shipping", "Taxes", "Total", "Shipping Method", 
        "Outstanding Balance", "Billing Province Name", "Shipping Province Name", "Payment Mode"
    ]

    # Ensure all target columns exist in data matrix safely
    for col in master_cols:
        if col not in df.columns:
            df[col] = np.nan

    # 4. Loop backwards or track duplicates to clear trailing order level cell content
    # Group by 'Name' and clear out duplicate values for all rows except the first row in the group
    df[master_cols] = df.groupby("Name")[master_cols].transform(lambda x: x.mask(x.index != x.index[0]))

    return df

# --- SIDEBAR COMPACT RANGE CONTROLLERS ---
st.sidebar.header("📅 Query Range Controller")
filter_type = st.sidebar.radio("Mode:", ["Exact Calendar Dates", "Whole Month / Year"])

if filter_type == "Exact Calendar Dates":
    today = datetime.date.today()
    start_date = st.sidebar.date_input("Start Date", today - datetime.timedelta(days=30))
    end_date = st.sidebar.date_input("End Date", today)
    start_iso = f"{start_date}T00:00:00Z"
    end_iso = f"{end_date}T23:59:59Z"
else:
    current_year = datetime.date.today().year
    year = st.sidebar.selectbox("Year", list(range(current_year, current_year - 4, -1)))
    months_map = {
        "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
        "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12
    }
    month_name = st.sidebar.selectbox("Month", list(months_map.keys()))
    month_num = months_map[month_name]
    
    start_iso = f"{year}-{month_num:02d}-01T00:00:00Z"
    if month_num == 12:
        end_iso = f"{year}-12-31T23:59:59Z"
    else:
        end_iso = f"{(datetime.date(year, month_num + 1, 1) - datetime.timedelta(days=1)).isoformat()}T23:59:59Z"

# --- EXECUTE PERFORMANCE OPTIMIZED PIPELINE ---
with st.spinner("⚡ Fetching data matrices..."):
    raw_df = fetch_prebuilt_ledger(start_iso, end_iso)

if raw_df.empty:
    st.warning("ℹ️ No records found matching this date slice.")
else:
    # Get basic totals directly from the raw data BEFORE clearing duplicates for display
    unique_orders_count = raw_df["Name"].nunique()
    total_rev = pd.to_numeric(raw_df.drop_duplicates(subset=["Name"])["Total"], errors='coerce').sum()
    unique_awbs_count = raw_df["awb number"].dropna().nunique()

    # Apply the hierarchical visual layout rule
    formatted_df = apply_hierarchical_excel_formatting(raw_df)

    # --- SEARCH BAR ---
    search_query = st.text_input("🔍 Search within filtered results (Order Name, AWB, Province)", "")
    if search_query:
        mask = (
            formatted_df["Name"].astype(str).str.contains(search_query, case=False, na=False) |
            formatted_df["awb number"].astype(str).str.contains(search_query, case=False, na=False) |
            formatted_df["Shipping Province Name"].astype(str).str.contains(search_query, case=False, na=False)
        )
        formatted_df = formatted_df[mask]

    # --- METRICS DISPLAYS ---
    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    c1.metric("Unique Orders Found", unique_orders_count)
    c2.metric("Total Period Revenue", f"₹{total_rev:,.2f}")
    c3.metric("Packages Tracked", unique_awbs_count)

    # --- EXPORT REPORT STRUCTURAL COLUMNS ---
    EXPORT_COLUMNS = [
        "Serial No", "Name", "SR Order ID", "Created at", "Financial Status", "Fulfillment Status",
        "Currency", "Subtotal", "Shipping", "Taxes", "Total", "Shipping Method",
        "Outstanding Balance", "Tax 1 Name", "Tax 1 Value", "Billing Province Name",
        "Shipping Province Name", "Payment Mode", "Lineitem name", "Lineitem quantity",
        "Lineitem price", "HSN CODE", "SHOPIFY DELIVERY STATUS", "awb number", "SHIPROCKET DELIVERY STATUS"
    ]
    
    # Pad columns cleanly if any values were dropped
    for col in EXPORT_COLUMNS:
        if col not in formatted_df.columns: 
            formatted_df[col] = np.nan
            
    export_ready_df = formatted_df[EXPORT_COLUMNS]
    
    # Replace default string NaN representations with blank empty cells for clean Excel rendering
    csv_data = export_ready_df.to_csv(index=False).encode('utf-8')
    st.sidebar.markdown("---")
    st.sidebar.download_button(
        label="📥 Export Current view (CSV)",
        data=csv_data,
        file_name=f"GLOBO_Report_{start_iso[:10]}.csv",
        mime="text/csv"
    )

    st.markdown("### 📋 Structured Data Matrix")
    # Formats presentation display so empty float metrics render natively blank rather than as text strings
    st.dataframe(
        export_ready_df.replace({np.nan: None}), 
        use_container_width=True, 
        hide_index=True
    )
