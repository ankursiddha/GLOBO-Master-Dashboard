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
    """Fetches transactional data sub-rows cleanly from master_reporting_ledger."""
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

def visually_aggregate_ledger(df):
    """
    Groups duplicate rows by Order Name. Order-level fields stay single, 
    while multi-line items and tracking matches merge cleanly into 
    multi-line strings inside a single row cell block.
    """
    if df.empty:
        return df

    # Replace None values with empty text to avoid string join issues
    string_cols = [
        "SR Order ID", "Tax 1 Name", "Tax 1 Value", "Lineitem name", 
        "Lineitem quantity", "Lineitem price", "HSN CODE", "awb number", 
        "SHIPROCKET DELIVERY STATUS"
    ]
    for c in string_cols:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str)

    # Sorting sequentially by original creation timeline
    df = df.sort_values(by="Created at", ascending=False)

    # Define aggregation behavior map
    agg_rules = {
        "Created at": "first",
        "created_at_dt": "first",
        "Financial Status": "first",
        "Fulfillment Status": "first",
        "Currency": "first",
        "Subtotal": "first",
        "Shipping": "first",
        "Taxes": "first",
        "Total": "first",
        "Shipping Method": "first",
        "Outstanding Balance": "first",
        "Billing Province Name": "first",
        "Shipping Province Name": "first",
        "Payment Mode": "first",
        "SHOPIFY DELIVERY STATUS": "first",
        
        # Unique tracking/item columns merge using newlines (\n) to segment the cells
        "SR Order ID": lambda x: "\n".join([v for v in x if v.strip()]),
        "Tax 1 Name": lambda x: "\n".join([v for v in x if v.strip()]),
        "Tax 1 Value": lambda x: "\n".join([v for v in x if v.strip()]),
        "Lineitem name": lambda x: "\n".join([v for v in x if v.strip()]),
        "Lineitem quantity": lambda x: "\n".join([v for v in x if v.strip()]),
        "Lineitem price": lambda x: "\n".join([v for v in x if v.strip()]),
        "HSN CODE": lambda x: "\n".join([v for v in x if v.strip()]),
        "awb number": lambda x: "\n".join([v for v in x if v.strip()]),
        "SHIPROCKET DELIVERY STATUS": lambda x: "\n".join([v for v in x if v.strip()])
    }

    # Execute structural grouping by main Order Name identifier
    grouped = df.groupby("Name", as_index=False).agg(agg_rules)
    return grouped.sort_values(by="Created at", ascending=False)

# --- SIDEBAR COMPACT FILTERS ---
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

# --- EXECUTE HIGH SPEED FETCH ---
with st.spinner("⚡ Fetching compiled data matrices..."):
    raw_df = fetch_prebuilt_ledger(start_iso, end_iso)

if raw_df.empty:
    st.warning("ℹ️ No records found matching this date slice.")
else:
    # Apply our custom cell merge aggregation layer
    filtered_df = visually_aggregate_ledger(raw_df)

    # --- SEARCH BAR ---
    search_query = st.text_input("🔍 Search within filtered results (Order Name, AWB, Province)", "")
    if search_query:
        mask = (
            filtered_df["Name"].astype(str).str.contains(search_query, case=False, na=False) |
            filtered_df["awb number"].astype(str).str.contains(search_query, case=False, na=False) |
            filtered_df["Shipping Province Name"].astype(str).str.contains(search_query, case=False, na=False)
        )
        filtered_df = filtered_df[mask]

    # --- METRICS ---
    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    c1.metric("Unique Orders Found", filtered_df["Name"].nunique())
    
    total_rev = pd.to_numeric(filtered_df["Total"], errors='coerce').sum()
    c2.metric("Total Period Revenue", f"₹{total_rev:,.2f}")
    
    # Clean split lines extraction to count true discrete tracking entities
    all_awbs = "\n".join(filtered_df["awb number"].dropna().tolist()).split("\n")
    unique_awbs_count = len(set([a.strip() for a in all_awbs if a.strip()]))
    c3.metric("Packages Tracked", unique_awbs_count)

    # --- EXPORT LEDGERS ---
    EXPORT_COLUMNS = [
        "Name", "SR Order ID", "Created at", "Financial Status", "Fulfillment Status",
        "Currency", "Subtotal", "Shipping", "Taxes", "Total", "Shipping Method",
        "Outstanding Balance", "Tax 1 Name", "Tax 1 Value", "Billing Province Name",
        "Shipping Province Name", "Payment Mode", "Lineitem name", "Lineitem quantity",
        "Lineitem price", "HSN CODE", "SHOPIFY DELIVERY STATUS", "awb number", "SHIPROCKET DELIVERY STATUS"
    ]
    
    for col in EXPORT_COLUMNS:
        if col not in filtered_df.columns: 
            filtered_df[col] = np.nan
            
    export_ready_df = filtered_df[EXPORT_COLUMNS]
    
    csv_data = export_ready_df.to_csv(index=False).encode('utf-8')
    st.sidebar.markdown("---")
    st.sidebar.download_button("📥 Export Current view (CSV)", csv_data, f"GLOBO_Report_{start_iso[:10]}.csv", "text/csv")

    st.markdown("### 📋 Structured Data Matrix")
    st.dataframe(export_ready_df, use_container_width=True, hide_index=True)
