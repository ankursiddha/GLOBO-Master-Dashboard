import streamlit as st
import pandas as pd
import numpy as np
import re
from supabase import create_client, Client

# --- PRODUCTION AUTHENTICATION ---
SUPABASE_URL = "https://wljftpkvsozgpxivbwiu.supabase.co"
SUPABASE_KEY = "sb_secret_60ve-Yh8xAvI6MZkhQQR3Q_Fk2mP9If"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="GLOBO Master Analytics Engine", layout="wide")

st.title("📊 GLOBO Master Report & Advanced Export Ledger")
st.subheader("Transactional Sub-Row Level Granular Analytics Dashboard")

def extract_base_order_number(name_str):
    """Extracts raw digits out of complex strings to perfectly match GLOBO1001 with R_GLOBO1001-C."""
    if not name_str:
        return ""
    digits = re.findall(r'\d+', str(name_str))
    return "".join(digits) if digits else str(name_str).strip()

@st.cache_data(ttl=300)  # Caches data streams for 5 minutes
def fetch_and_build_master_ledger():
    # 1. Gather all raw records out of Supabase
    orders_res = supabase.table("shopify_orders").select("*").execute()
    items_res = supabase.table("shopify_order_items").select("*").execute()
    shipments_res = supabase.table("shiprocket_shipments").select("*").execute()
    
    df_orders = pd.DataFrame(orders_res.data)
    df_items = pd.DataFrame(items_res.data)
    df_shipments = pd.DataFrame(shipments_res.data)
    
    if df_orders.empty:
        return pd.DataFrame()
        
    # --- FIX: FORCE CLEAN TIMEZONE-NEUTRAL DATETIME PARSING ---
    df_orders["created_at_dt"] = pd.to_datetime(df_orders["created_at"], errors='coerce', utc=True).dt.tz_localize(None)
    
    # Pre-calculate base numbers for the flexible wildcard tracking join
    df_orders["base_match_id"] = df_orders["name"].apply(extract_base_order_number)
    
    if not df_shipments.empty:
        df_shipments["base_match_id"] = df_shipments["channel_order_id"].apply(extract_base_order_number)
    
    final_rows = []
    
    # 2. Iterate through each master order to construct strict structural sub-rows
    for _, order in df_orders.iterrows():
        order_id = order.get("order_id")
        base_id = order.get("base_match_id")
        
        o_items = df_items[df_items["order_id"] == order_id] if not df_items.empty else pd.DataFrame()
        o_ships = df_shipments[df_shipments["base_match_id"] == base_id] if not df_shipments.empty else pd.DataFrame()
        
        max_sub_rows = max(len(o_items), len(o_ships), 1)
        
        for i in range(max_sub_rows):
            row_data = {
                # --- MASTER ORDER LEVEL DETAILS ---
                "Name": order.get("name"),
                "Created at": order.get("created_at"),
                "created_at_dt": order.get("created_at_dt"), # Timezone-naive datetime object
                "Financial Status": order.get("financial_status"),
                "Fulfillment Status": order.get("fulfillment_status"),
                "Currency": order.get("currency"),
                "Subtotal": order.get("subtotal_price"),
                "Shipping": order.get("total_shipping_price_set"),
                "Taxes": order.get("total_tax"),
                "Total": order.get("total_price"),
                "Shipping Method": order.get("shipping_method"), 
                "Outstanding Balance": order.get("outstanding_balance"),
                "Billing Province Name": order.get("billing_address_province"),
                "Shipping Province Name": order.get("shipping_address_province"),
                "Payment Mode": order.get("gateway"),
                "SHOPIFY DELIVERY STATUS": order.get("delivery_status"),
                
                # --- ITEM LEVEL VARIABLE SUB-ROWS ---
                "Tax 1 Name": None,
                "Tax 1 Value": None,
                "Lineitem name": None,
                "Lineitem quantity": None,
                "Lineitem price": None,
                "HSN CODE": None,
                
                # --- LOGISTICS LEVEL VARIABLE SUB-ROWS ---
                "SR Order ID": None,
                "awb number": None,
                "SHIPROCKET DELIVERY STATUS": None
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

# --- RUN ENGINE DATA PIPELINE ---
with st.spinner("Compiling relational data matrices..."):
    raw_ledger = fetch_and_build_master_ledger()

if raw_ledger.empty:
    st.error("⚠️ Database connection returned empty datasets. Check master table records.")
else:
    # --- INTERACTIVE DATE & CALENDAR FILTERS ---
    st.sidebar.header("📅 Date Selection Matrix")
    filter_type = st.sidebar.radio("Select Filter Mode:", ["By Exact Calendar Dates", "By Whole Month / Year"])
    
    filtered_df = raw_ledger.copy()
    
    if filter_type == "By Exact Calendar Dates":
        min_date = raw_ledger["created_at_dt"].min().date() if pd.notna(raw_ledger["created_at_dt"].min()) else pd.Timestamp.now().date()
        max_date = raw_ledger["created_at_dt"].max().date() if pd.notna(raw_ledger["created_at_dt"].max()) else pd.Timestamp.now().date()
        
        selected_range = st.sidebar.date_input("Choose Range:", [min_date, max_date])
        
        # Guard clause handling standard single click parameters on Streamlit calendars
        if isinstance(selected_range, (list, tuple)) and len(selected_range) == 2:
            start_date, end_date = selected_range
            # Clean matching metrics comparison logic
            filtered_df = filtered_df[
                (filtered_df["created_at_dt"].dt.date >= start_date) & 
                (filtered_df["created_at_dt"].dt.date <= end_date)
            ]
            
    else:
        available_years = sorted(raw_ledger["created_at_dt"].dt.year.dropna().unique().astype(int), reverse=True)
        if not available_years:
            available_years = [pd.Timestamp.now().year]
            
        selected_year = st.sidebar.selectbox("Choose Year:", available_years)
        
        months_map = {
            1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
            7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December"
        }
        
        # Isolate indices available for this specific year dynamically
        available_months_idx = sorted(raw_ledger[raw_ledger["created_at_dt"].dt.year == selected_year]["created_at_dt"].dt.month.dropna().unique().astype(int))
        available_months_names = [months_map[m] for m in available_months_idx]
        
        if not available_months_names:
            available_months_names = ["No Data Found"]
            
        selected_month_name = st.sidebar.selectbox("Choose Month:", available_months_names)
        
        if selected_month_name != "No Data Found":
            inverse_months_map = {v: k for k, v in months_map.items()}
            selected_month_idx = inverse_months_map[selected_month_name]
            
            filtered_df = filtered_df[
                (filtered_df["created_at_dt"].dt.year == selected_year) & 
                (filtered_df["created_at_dt"].dt.month == selected_month_idx)
            ]

    # --- SEARCH CONTROL CENTER ---
    search_query = st.text_input("🔍 Live Query Filter (Type Order Name, AWB Tracking Number, or State)", "")
    if search_query:
        mask = (
            filtered_df["Name"].astype(str).str.contains(search_query, case=False, na=False) |
            filtered_df["awb number"].astype(str).str.contains(search_query, case=False, na=False) |
            filtered_df["Shipping Province Name"].astype(str).str.contains(search_query, case=False, na=False)
        )
        filtered_df = filtered_df[mask]

    # --- METRIC HEADERS ---
    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    unique_orders_count = filtered_df["Name"].nunique() if not filtered_df.empty else 0
    c1.metric("Unique Orders Filtered", unique_orders_count)
    
    if not filtered_df.empty and "Total" in filtered_df.columns:
        unique_order_totals = filtered_df.drop_duplicates(subset=["Name"])
        total_value = pd.to_numeric(unique_order_totals["Total"], errors='coerce').sum()
        c2.metric("Total Period Revenue", f"₹{total_value:,.2f}")
    else:
        c2.metric("Total Period Revenue", "₹0.00")
        
    dispatched_count = filtered_df["awb number"].dropna().nunique() if not filtered_df.empty else 0
    c3.metric("Unique Packages Dispatched", dispatched_count)

    # --- STRICT DOWNLOAD FORMAT EXPORT CONTROL ---
    EXPORT_COLUMNS = [
        "Name", "SR Order ID", "Created at", "Financial Status", "Fulfillment Status",
        "Currency", "Subtotal", "Shipping", "Taxes", "Total", "Shipping Method",
        "Outstanding Balance", "Tax 1 Name", "Tax 1 Value", "Billing Province Name",
        "Shipping Province Name", "Payment Mode", "Lineitem name", "Lineitem quantity",
        "Lineitem price", "HSN CODE", "SHOPIFY DELIVERY STATUS", "awb number",
        "SHIPROCKET DELIVERY STATUS"
    ]
    
    for col in EXPORT_COLUMNS:
        if col not in filtered_df.columns:
            filtered_df[col] = np.nan
            
    export_ready_df = filtered_df[EXPORT_COLUMNS]

    st.sidebar.markdown("---")
    st.sidebar.subheader("📥 Export Center")
    
    csv_data = export_ready_df.to_csv(index=False).encode('utf-8')
    st.sidebar.download_button(
        label="📥 Download Filtered Report (CSV)",
        data=csv_data,
        file_name=f"GLOBO_Custom_Report_{pd.Timestamp.now().strftime('%d_%b_%Y')}.csv",
        mime="text/csv",
        key="download-filtered-csv"
    )

    # --- UI GRID INTERFACE DISPLAY ---
    st.markdown("### 📋 Interactive Operational Data Ledger View")
    st.dataframe(
        export_ready_df,
        use_container_width=True,
        hide_index=True
    )
