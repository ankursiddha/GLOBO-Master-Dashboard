import os
import re
import math
import pandas as pd
import numpy as np
from supabase import create_client, Client

# --- PRODUCTION AUTHENTICATION CONFIGURATION ---
SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://wljftpkvsozgpxivbwiu.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "sb_secret_60ve-Yh8xAvI6MZkhQQR3Q_Fk2mP9If"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def clean_shopify_name(name_str):
    if not name_str:
        return ""
    return str(name_str).replace("#", "").strip().upper()

def is_shiprocket_wildcard_match(shopify_clean_name, sr_channel_order_id):
    if not shopify_clean_name or not sr_channel_order_id:
        return False
    sr_id = str(sr_channel_order_id).strip().upper()
    escaped_target = re.escape(shopify_clean_name)
    pattern = rf"(?:^|[^A-Z0-9]){escaped_target}(?:[^A-Z0-9]|$)"
    return bool(re.search(pattern, sr_id))

def fetch_all_rows_paginated(table_name):
    """Pulls all records comprehensively from a table in chunks of 1000."""
    all_data = []
    chunk_size = 1000
    start_idx = 0
    while True:
        res = supabase.table(table_name).select("*").range(start_idx, start_idx + chunk_size - 1).execute()
        data_chunk = res.data
        if not data_chunk:
            break
        all_data.extend(data_chunk)
        if len(data_chunk) < chunk_size:
            break
        start_idx += chunk_size
    return pd.DataFrame(all_data)

def is_invalid_value(val):
    """Checks if a value is an illegal JSON float (NaN or Infinity)."""
    if val is None:
        return False
    if isinstance(val, float):
        return math.isnan(val) or math.isinf(val)
    if isinstance(val, pd.Timestamp) or pd.isna(val):
        return True
    return False

def sync_master_reporting_table():
    print("--- 🔍 STARTING DIAGNOSTIC LEDGER POPULATION ENGINE ---")
    
    # 1. Fetch data from source tables
    print("Fetching active tables from Supabase...")
    df_orders = fetch_all_rows_paginated("shopify_orders")
    df_items = fetch_all_rows_paginated("shopify_order_items")
    df_shipments = fetch_all_rows_paginated("shiprocket_shipments")
    
    if df_orders.empty:
        print("❌ No data found in shopify_orders. Exiting sync.")
        return

    print(f"Loaded {len(df_orders)} orders, {len(df_items)} items, and {len(df_shipments)} shipments.")

    # 2. Pre-Scan Source Data for Immediate System Warnings
    print("\n--- 🩺 PHASE 1: PRE-SCANNING SOURCE DATASETS FOR INVALID FLOATS ---")
    numeric_order_cols = ["subtotal_price", "total_shipping_price_set", "total_tax", "total_price", "outstanding_balance"]
    numeric_item_cols = ["tax_1_value", "lineitem_price"]
    
    order_nan_count = 0
    for _, row in df_orders.iterrows():
        for col in numeric_order_cols:
            val = pd.to_numeric(row.get(col), errors='coerce')
            if is_invalid_value(val):
                order_nan_count += 1
                if order_nan_count <= 10:  # Cap printout size to avoid log overload
                    print(f"  ⚠️ SOURCE WARNING [shopify_orders]: Order Name: {row.get('name')} has invalid float/NaN in column: '{col}'")
                    
    item_nan_count = 0
    for _, row in df_items.iterrows():
        for col in numeric_item_cols:
            val = pd.to_numeric(row.get(col), errors='coerce')
            if is_invalid_value(val):
                item_nan_count += 1
                if item_nan_count <= 10:
                    print(f"  ⚠️ SOURCE WARNING [shopify_order_items]: Item ID: {row.get('lineitem_id')} (Order ID: {row.get('order_id')}) has invalid float/NaN in column: '{col}'")

    print(f"📊 Pre-Scan Summary: Found {order_nan_count} illegal fields in shopify_orders and {item_nan_count} in shopify_order_items.")

    # 3. Process records with strict sub-row alignment rules
    print("\n--- 🔄 PHASE 2: PROCESSING RELATIONAL MAPPING & EXTRACTING SUB-ROWS ---")
    compiled_rows = []
    total_processed_subrows = 0
    
    for _, order in df_orders.iterrows():
        order_id = order.get("order_id")
        raw_name = order.get("name")
        clean_name = clean_shopify_name(raw_name)
        
        o_items = df_items[df_items["order_id"] == order_id] if not df_items.empty else pd.DataFrame()
        
        if not df_shipments.empty and clean_name:
            matched_ships_mask = df_shipments["channel_order_id"].apply(lambda x: is_shiprocket_wildcard_match(clean_name, x))
            o_ships = df_shipments[matched_ships_mask]
        else:
            o_ships = pd.DataFrame()
            
        max_sub_rows = max(len(o_items), len(o_ships), 1)
        
        for i in range(max_sub_rows):
            row_data = {
                "shopify_order_id": str(order_id),
                "shopify_lineitem_id": None,
                "shiprocket_shipment_id": None,
                "Name": raw_name,
                "SR Order ID": None,
                "Created at": order.get("created_at"),
                "Financial Status": order.get("financial_status"),
                "Fulfillment Status": order.get("fulfillment_status"),
                "Currency": order.get("currency"),
                "Subtotal": pd.to_numeric(order.get("subtotal_price"), errors='coerce'),
                "Shipping": pd.to_numeric(order.get("total_shipping_price_set"), errors='coerce'),
                "Taxes": pd.to_numeric(order.get("total_tax"), errors='coerce'),
                "Total": pd.to_numeric(order.get("total_price"), errors='coerce'),
                "Shipping Method": order.get("shipping_method"),
                "Outstanding Balance": pd.to_numeric(order.get("outstanding_balance"), errors='coerce'),
                "Tax 1 Name": None,
                "Tax 1 Value": pd.to_numeric(None, errors='coerce'),
                "Billing Province Name": order.get("billing_address_province"),
                "Shipping Province Name": order.get("shipping_address_province"),
                "Payment Mode": order.get("gateway"),
                "Lineitem name": None,
                "Lineitem quantity": None,
                "Lineitem price": pd.to_numeric(None, errors='coerce'),
                "HSN CODE": None,
                "SHOPIFY DELIVERY STATUS": order.get("delivery_status"),
                "awb number": None,
                "SHIPROCKET DELIVERY STATUS": order.get("status")
            }
            
            if i < len(o_items):
                item = o_items.iloc[i]
                row_data["shopify_lineitem_id"] = str(item.get("lineitem_id"))
                row_data["Tax 1 Name"] = item.get("tax_1_name")
                row_data["Tax 1 Value"] = pd.to_numeric(item.get("tax_1_value"), errors='coerce')
                row_data["Lineitem name"] = item.get("lineitem_name") or item.get("title")
                row_data["Lineitem quantity"] = int(item.get("lineitem_quantity")) if item.get("lineitem_quantity") else None
                row_data["Lineitem price"] = pd.to_numeric(item.get("lineitem_price"), errors='coerce')
                row_data["HSN CODE"] = item.get("hsn_code")
                
            if i < len(o_ships):
                ship = o_ships.iloc[i]
                row_data["shiprocket_shipment_id"] = str(ship.get("id"))
                row_data["SR Order ID"] = ship.get("channel_order_id")
                row_data["awb number"] = ship.get("awb_number")
                row_data["SHIPROCKET DELIVERY STATUS"] = ship.get("status")
                
            compiled_rows.append(row_data)
            total_processed_subrows += 1

    # 4. Strict Real-Time Payload Interception & JSON Check
    print("\n--- 🔎 PHASE 3: INTERCEPTING PROCESSED BATCHES FOR JSON COMPLIANCE ---")
    checked_cleaned_rows = []
    payload_nan_errors = 0
    
    numeric_keys_to_verify = ["Subtotal", "Shipping", "Taxes", "Total", "Outstanding Balance", "Tax 1 Value", "Lineitem price"]
    
    for idx, row in enumerate(compiled_rows):
        has_error_in_row = False
        for key in numeric_keys_to_verify:
            val = row[key]
            if is_invalid_value(val):
                payload_nan_errors += 1
                has_error_in_row = True
                if payload_nan_errors <= 15:
                    print(f"  🚨 JSON CRITICAL FAULT at Processed Row index {idx} | Order: {row['Name']} | Key: '{key}' has value '{val}' (Illegal Float)")
                
                # Convert the bad value specifically to None for debugging visibility, tracking the location
                row[key] = None
                
        checked_cleaned_rows.append(row)

    print(f"\n📢 Interception Complete: Found {payload_nan_errors} illegal values embedded inside the compiled JSON structures.")

    # 5. Purge and Batch Push Clear Records
    print("\n--- 💾 PHASE 4: CLEARING LEDGER & EXECUTING DATABASE WRITE ---")
    print("Purging old entries from master_reporting_ledger...")
    supabase.table("master_reporting_ledger").delete().neq("Name", "FORCE_DELETE_ALL_ROWS").execute()

    print(f"Uploading {len(checked_cleaned_rows)} processed transactional sub-rows to Supabase...")
    batch_size = 500
    for idx in range(0, len(checked_cleaned_rows), batch_size):
        chunk = checked_cleaned_rows[idx:idx + batch_size]
        try:
            supabase.table("master_reporting_ledger").insert(chunk).execute()
            print(f" Pushed records {idx} to {idx + len(chunk)} successfully.")
        except Exception as e:
            print(f" ❌ Database write blocked at index block {idx}: {e}")
            
    print("\n🎉 Processed ledger optimization engine run complete.")

if __name__ == "__main__":
    sync_master_reporting_table()
