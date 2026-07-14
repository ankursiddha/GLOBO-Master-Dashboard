import streamlit as st
import pandas as pd
import numpy as np
import re
import datetime
from supabase import create_client, Client

# --- PRODUCTION AUTHENTICATION ---
SUPABASE_URL = "https://wljftpkvsozgpxivbwiu.supabase.co"
SUPABASE_KEY = "sb_secret_60ve-Yh8xAvI6MZkhQQR3Q_Fk2mP9If"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="GLOBO Master Analytics Engine", layout="wide")

st.title("📊 GLOBO Master Report & Advanced Export Ledger")
st.subheader("Granular Analytics Dashboard — Server-Optimized Edition")

def extract_base_order_number(name_str):
    if not name_str: return ""
    digits = re.findall(r'\d+', str(name_str))
    return "".join(digits) if digits else str(name_str).strip()

def fetch_filtered_data(start_iso, end_iso):
    """Queries Supabase with precise server-side date constraints to maximize speed."""
    # 1. Fetch only matching orders
    orders_res = supabase.table("shopify_orders").select("*").gte("created_at", start_iso).lte("created_at", end_iso).execute()
    df_orders = pd.DataFrame(orders_res.data)
    
    if df_orders.empty:
        return pd.DataFrame()
        
    order_ids = df_orders["order_id"].tolist()
    order_names = df_orders["name"].dropna().tolist()
    base_match_ids = [extract_base_order_number(n) for n in order_names]
    
    # 2. Query child tables using batch chunking to avoid query limit bounds
    df_items = pd.DataFrame()
    if order_ids:
        for i in range(0, len(order_ids), 500):
            chunk = order_ids[i:i+500]
            res = supabase.table("shopify_order_items").select("*").in_("order_id", chunk).execute()
            if res.data:
                df_items = pd.concat([df_items, pd.DataFrame(res.data)], ignore_index=True)
                
    df_shipments = pd.DataFrame()
    if base_match_ids:
        # Build wildcard or list matching checks against Shiprocket rows efficiently
        for i in range(0, len(base_match_ids), 500):
            chunk = base_match_ids[i:i+500]
            res = supabase.table("shiprocket_shipments").select("*").in_("channel_order_id", chunk).execute()
            if res.data:
                df_shipments = pd.concat([df_shipments, pd.DataFrame(res.data)], ignore_index=True)
                
    # Fallback to loose text cleaning matching check if direct batch missed custom flags
    if df_shipments.empty and base_match_ids:
        res = supabase.table("shiprocket_shipments").select("*").limit(1000).execute()
        df_shipments = pd.DataFrame(res.data)

    # 3. Assemble Aligned Relational Matrix
    df_orders["created_at_dt"] = pd.to_datetime(df_orders["created_at"], errors='coerce').dt.tz_localize(None)
    df_orders["base_match_id"] = df_orders["name"].apply(extract_base_order_number)
    
    if not df_shipments.empty:
        df_shipments["base_match_id"] = df_shipments["channel_order_id"].apply(extract_base_order_number)
        
    final_rows = []
    for _, order in df_orders.iterrows():
        oid = order.get("order_id")
        bid = order.get("base_match_id")
        
        o_items = df_items[df_items["order_id"] == oid] if not df_items.empty else pd.DataFrame()
        o_ships = df_shipments[df_shipments["base_match_id"] == bid] if not df_shipments.empty else pd.DataFrame()
        
        max_sub_rows = max(len(o_items), len(o_ships), 1)
        for i in range(max_sub_rows):
            row_data = {
                "Name": order.get("name"), "Created at": order.get("created_at"), "created_at_dt": order.get("created_at_dt"),
                "Financial Status": order.get("financial_status"), "Fulfillment Status": order.get("fulfillment_status"),
                "Currency": order.get("currency"), "Subtotal": order.get("subtotal_price"), "Shipping": order.get("total_shipping_price_set"),
                "Taxes": order.get("total_tax"), "Total": order.get("total_price"), "Shipping Method": order.get("shipping_method"),
                "Outstanding Balance": order.get("outstanding_balance"), "Billing Province Name": order.get("billing_address_province"),
                "Shipping Province Name": order.get("shipping_address_province"), "Payment Mode": order.get("gateway"), "SHOPIFY DELIVERY STATUS": order.get("delivery_status"),
                "Tax 1 Name": None, "Tax 1 Value": None, "Lineitem name": None, "Lineitem quantity": None, "Lineitem price": None, "HSN CODE": None,
                "SR Order ID": None, "awb number": None, "SHIPROCKET DELIVERY STATUS": None
            }
            if i < len(o_items):
                item = o_items.iloc[i]
                row_data["Tax 1 Name"] = item.get("tax_1_name")
                row_data["Tax 1 Value"] = item.get("tax_1_value")
                row_data["Lineitem name"] = item.get("lineitem_name") or item.get("title")
                row_data["Lineitem quantity"] = item.get("lineitem_quantity") or item.get("quantity")
                row_data["Lineitem price"] = item.get("lineitem_price") or item.get("price")
                row_data["HSN CODE"] = item.get("hsn_code")
            if i < len(o_ships):
                ship = o_ships.iloc[i]
                row_data["SR Order ID"] = ship.get("channel_order_id")
                row_data["awb number"] = ship.get("awb_number")
                row_data["SHIPROCKET DELIVERY STATUS"] = ship.get("status")
            final_rows.append(row_data)
            
    master_df = pd.DataFrame(final_rows)
    if not master_df.empty:
        master_df = master_df.sort_values(by="Created at", ascending=False)
    return master_df

# --- SIDEBAR COMPACT FILTERS ---
st.sidebar.header("📅 Query Range Controller")
filter_type = st.sidebar.radio("Mode:", ["Exact Calendar Dates", "Whole Month / Year"])

# Calculate date constraints before fetching data
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

# --- RUN PERFORMANCE OPTIMIZED PIPELINE ---
with st.spinner("⚡ Querying database targets..."):
    filtered_df = fetch_filtered_data(start_iso, end_iso)

if filtered_df.empty:
    st.warning("ℹ️ No records found matching this date slice.")
else:
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
    
    unique_order_totals = filtered_df.drop_duplicates(subset=["Name"])
    total_rev = pd.to_numeric(unique_order_totals["Total"], errors='coerce').sum()
    c2.metric("Total Period Revenue", f"₹{total_rev:,.2f}")
    c3.metric("Packages Tracked", filtered_df["awb number"].dropna().nunique())

    # --- EXPORT ledgers ---
    EXPORT_COLUMNS = [
        "Name", "SR Order ID", "Created at", "Financial Status", "Fulfillment Status",
        "Currency", "Subtotal", "Shipping", "Taxes", "Total", "Shipping Method",
        "Outstanding Balance", "Tax 1 Name", "Tax 1 Value", "Billing Province Name",
        "Shipping Province Name", "Payment Mode", "Lineitem name", "Lineitem quantity",
        "Lineitem price", "HSN CODE", "SHOPIFY DELIVERY STATUS", "awb number", "SHIPROCKET DELIVERY STATUS"
    ]
    for col in EXPORT_COLUMNS:
        if col not in filtered_df.columns: filtered_df[col] = np.nan
        
    export_ready_df = filtered_df[EXPORT_COLUMNS]
    
    csv_data = export_ready_df.to_csv(index=False).encode('utf-8')
    st.sidebar.markdown("---")
    st.sidebar.download_button("📥 Export Current view (CSV)", csv_data, f"GLOBO_Report_{start_iso[:10]}.csv", "text/csv")

    st.markdown("### 📋 Structured Data Matrix")
    st.dataframe(export_ready_df, use_container_width=True, hide_index=True)
