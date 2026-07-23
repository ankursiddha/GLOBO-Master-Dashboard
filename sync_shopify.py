import os
import re
import time
import requests
import datetime
from supabase import create_client, Client

# --- 1. BACKLOG & PIPELINE CONTROLS ---
START_ORDER_NAME = os.environ.get("START_ORDER_INPUT") or "#GLOBO1001"
BATCH_SIZE = 50                  # Number of orders to pull per API request page

# --- 2. CONFIGURATION & DEPLOYMENT KEYS ---
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE_URL") or "355b0d-2.myshopify.com"
SHOPIFY_API_VERSION = "2024-04"
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN") or "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"

SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://wljftpkvsozgpxivbwiu.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "sb_secret_60ve-Yh8xAvI6MZkhQQR3Q_Fk2mP9If"

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase production database interface connected successfully.")
except Exception as e:
    print(f"❌ CRITICAL INITIALIZATION FAULT: Failed to connect to Supabase: {e}")

shopify_headers = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN,
    "Content-Type": "application/json"
}

def clean_and_slice_hsn(raw_hsn):
    """Isolates numeric characters strictly and slices the first 4."""
    if not raw_hsn or str(raw_hsn).lower().strip() in ["none", "null", "nan", ""]:
        return None
    numeric_hsn = "".join([c for c in str(raw_hsn) if c.isdigit()])
    return numeric_hsn[:4] if numeric_hsn else None

def fetch_live_hsn_from_shopify(variant_id):
    """Deep Variant and Inventory Item check with integrated rate-limit back-off handling."""
    if not variant_id or str(variant_id).lower().strip() in ["none", "null", ""]:
        return None
        
    variant_url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/variants/{str(variant_id).strip()}.json"
    for retry in range(3):
        try:
            res = requests.get(variant_url, headers=shopify_headers)
            if res.status_code == 429:
                time.sleep(5)
                continue
            if res.status_code == 200:
                variant_data = res.json().get("variant", {})
                hsn_code = clean_and_slice_hsn(variant_data.get("harmonized_system_code"))
                if hsn_code:
                    return hsn_code
                    
                inventory_item_id = variant_data.get("inventory_item_id")
                if inventory_item_id:
                    inv_url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/inventory_items/{inventory_item_id}.json"
                    inv_res = requests.get(inv_url, headers=shopify_headers)
                    if inv_res.status_code == 200:
                        return clean_and_slice_hsn(inv_res.json().get("inventory_item", {}).get("harmonized_system_code"))
            break
        except Exception as e:
            print(f"  ⚠️ Connection barrier hitting Shopify for Variant {variant_id}: {e}")
            time.sleep(2)
    return None



def fetch_order_transactions_metrics(order):
    """
    Evaluates real-time transaction level breakdowns to resolve:
    1. Condition 1: Cash Refunds vs Store Credit Refunds.
    2. Condition 2: Split payments (excluding Store Credit share from cash total).
    3. Condition 3: Filtering out failed transaction attempts and keeping valid non-store-credit gateways.
    4. Condition 4: Pending COD + Manual Completion (Preserves 'GoKwik Cash On Delivery' instead of 'manual').
    """
    order_id = order["id"]
    default_total = float(order.get("current_total_price", 0)) if order.get("current_total_price") is not None else float(order.get("total_price", 0))
    raw_gateways = order.get("payment_gateway_names", [])
    
    # Clean fallback: Filter out 'manual' from raw gateways if a real gateway exists
    clean_raw_gateways = [g for g in raw_gateways if str(g).lower().strip() != "manual"]
    default_gateway = clean_raw_gateways[0] if clean_raw_gateways else (raw_gateways[0] if raw_gateways else "Unknown")

    tx_url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/orders/{order_id}/transactions.json"
    try:
        tx_res = requests.get(tx_url, headers=shopify_headers)
        if tx_res.status_code != 200:
            return default_total, default_gateway

        transactions = tx_res.json().get("transactions", [])
        if not transactions:
            return default_total, default_gateway

        # --- CONDITION 3: DROP FAILED / ERRORED ATTEMPTS FIRST ---
        valid_transactions = [
            t for t in transactions 
            if str(t.get("status")).lower() not in ["failure", "error"]
        ]

        if not valid_transactions:
            return default_total, default_gateway

        # --- CONDITION 4: SCAN ALL VALID TRANSACTIONS FOR REAL GATEWAYS ---
        # Checks pending & successful entries to preserve 'GoKwik Cash On Delivery' over 'manual'
        valid_real_gateways = []
        for t in valid_transactions:
            gw = str(t.get("gateway", "")).strip()
            if gw and gw.lower() != "manual" and "store_credit" not in gw.lower():
                valid_real_gateways.append(gw)

        if valid_real_gateways:
            # Deduplicate while preserving order
            resolved_payment_mode = " / ".join(list(dict.fromkeys(valid_real_gateways)))
        else:
            resolved_payment_mode = default_gateway

        # --- FINANCIAL CALCULATIONS (SUCCESSFUL TRANSACTIONS ONLY) ---
        successful_sales = [
            t for t in valid_transactions 
            if str(t.get("status")).lower() == "success" and str(t.get("kind")).lower() in ["sale", "capture"]
        ]

        if not successful_sales:
            return default_total, resolved_payment_mode

        # Filter out Store Credit for cash totals
        non_sc_sales = [t for t in successful_sales if "store_credit" not in str(t.get("gateway")).lower()]
        
        if non_sc_sales:
            # Check if there is already a non-manual sale transaction
            has_other_sale_tx = any(str(t.get("gateway")).lower() != "manual" for t in successful_sales)
            
            seen_amounts = []
            non_sc_sales_amount = 0.0
            
            for t in non_sc_sales:
                amt = float(t.get("amount", 0))
                gw = str(t.get("gateway")).lower()
                
                # Prevent double-counting if 'manual' completion is added on top of an existing sale
                if gw == "manual" and (has_other_sale_tx or amt in seen_amounts):
                    continue
                
                non_sc_sales_amount += amt
                seen_amounts.append(amt)
        else:
            non_sc_sales_amount = sum(float(t.get("amount", 0)) for t in successful_sales)

        # Handle Refunds
        successful_refunds = [
            t for t in valid_transactions 
            if str(t.get("status")).lower() == "success" and str(t.get("kind")).lower() == "refund"
        ]

        cash_refund_amount = sum(
            float(r.get("amount", 0)) for r in successful_refunds 
            if "store_credit" not in str(r.get("gateway")).lower()
        )

        final_total = max(0.0, non_sc_sales_amount - cash_refund_amount)

        # Safeguard fallback
        if final_total == 0.0 and order.get("financial_status") not in ["refunded", "voided"]:
            final_total = default_total

        return final_total, resolved_payment_mode

    except Exception as e:
        print(f"⚠️ Error parsing transaction layer for order {order_id}: {e}")
        return default_total, default_gateway


def extract_ctp_final_value(order_tags):
    """Parses CTP_..._FV-XXXX.XX tag to get exact net paid rupees."""
    if not order_tags:
        return None
    import re
    match = re.search(r'CTP_.*?_FV-([\d\.]+)', str(order_tags))
    return float(match.group(1)) if match else None




def get_internal_id_from_name(order_name):
    """Resolves visible order text milestone markers down to internal Shopify sequence integers."""
    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/orders.json?query=name:{requests.utils.quote(str(order_name).strip())}&status=any"
    try:
        res = requests.get(url, headers=shopify_headers)
        if res.status_code == 200 and res.json().get("orders"):
            return res.json()["orders"][0]["id"]
    except Exception as e:
        print(f"❌ Error locating numeric conversion milestone for '{order_name}': {e}")
    return None

def run_historical_backfill():
    print(f"\n--- 🚀 RUNNING UNIFIED SYNC PIPELINE FROM MILESTONE: {START_ORDER_NAME} ---")
    
    start_numeric_id = get_internal_id_from_name(START_ORDER_NAME)
    if not start_numeric_id:
        print(f"❌ Error: Milestone checkpoint order identity '{START_ORDER_NAME}' not found inside store. Aborting execution.")
        return
        
    current_since_id = start_numeric_id - 1
    
    while True:
        url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/orders.json?limit={BATCH_SIZE}&status=any&since_id={current_since_id}&order=id%20asc"
        print(f"\n📥 Querying batch layer containing up to {BATCH_SIZE} profiles following ID: {current_since_id}...")
        
        try:
            response = requests.get(url, headers=shopify_headers)
        except Exception as conn_err:
            print(f"⚠️ Connection failure reaching API endpoints: {conn_err}. Retrying batch query...")
            time.sleep(5)
            continue
            
        if response.status_code != 200:
            print(f"⚠️ API rate warning or restriction block encountered: {response.status_code}. Stopping operations loop.")
            break
            
        orders = response.json().get("orders", [])
        if not orders:
            print("🏁 Reached absolute synchronization point! Database matching operations are complete.")
            break
            
        print(f"🔄 Downloaded {len(orders)} order records. Parsing matrix structural metrics...")
        
        for order in orders:
            order_id = str(order["id"])
            current_order_name = order["name"]
            
            # Extract basic tax parameters safely
            tax_lines = order.get("tax_lines", [])
            tax_1_name = tax_lines[0].get("title") if len(tax_lines) > 0 else None
            tax_1_value = float(tax_lines[0].get("price")) if len(tax_lines) > 0 else 0.0

            # Dynamic fulfillment extraction paths
            fulfillments = order.get("fulfillments", [])
            shopify_shipment_status = None
            if fulfillments and len(fulfillments) > 0:
                shopify_shipment_status = fulfillments[0].get("shipment_status")

            # Local calendar string parsing adjustments (Stripping UTC drift artifacts)
            raw_created_at = str(order["created_at"])
            clean_created_at = raw_created_at.replace("T", " ").split("+")[0].split(".")[0].strip()

            

            # --- SAFE PAYMENT MODE & SHIPPING METHOD EXTRACTION ---
            order_tags = str(order.get("tags", ""))
            
            if "COD_TO_PREPAID_CONVERTED" in order_tags or "CTP_" in order_tags:
                payment_mode = "Razorpay (COD to Prepaid Conversion)"
                shipping_method = "PREPAID"
                shipping_cost = 0.0
                
                ctp_paid_amount = extract_ctp_final_value(order_tags)
                if ctp_paid_amount is not None and ctp_paid_amount > 0:
                    calculated_total = ctp_paid_amount
                else:
                    calculated_total = float(order.get("current_total_price", 0)) if order.get("current_total_price") is not None else float(order.get("total_price", 0))
            else:
                calculated_total, resolved_payment_mode = fetch_order_transactions_metrics(order)
                payment_mode = resolved_payment_mode
                
                shipping_lines = order.get("shipping_lines", [])
                primary_shipping_line = shipping_lines[0] if shipping_lines else {}
                shipping_method = primary_shipping_line.get("title")

                
                
                # Calculate total refunded shipping across all refund adjustments
                total_shipping_refunded = 0.0
                for refund in order.get("refunds", []):
                    for adj in refund.get("order_adjustments", []):
                        if adj.get("kind") == "shipping_refund":
                            total_shipping_refunded += abs(float(adj.get("amount", 0)))

                raw_shipping_cost = float(order.get("total_shipping_price_set", {}).get("shop_money", {}).get("amount", 0))

                if primary_shipping_line.get("is_removed", False) or (raw_shipping_cost > 0 and total_shipping_refunded >= raw_shipping_cost) or order.get("financial_status") == "voided":
                    shipping_cost = 0.0
                else:
                    shipping_cost = max(0.0, raw_shipping_cost - total_shipping_refunded)

            

            parent_order = {
                "order_id": order_id,
                "name": current_order_name,                                
                "created_at": clean_created_at,  
                "financial_status": order["financial_status"],        
                "fulfillment_status": order["fulfillment_status"],    
                "currency": order["currency"],
                "subtotal": float(order.get("current_subtotal_price", 0)),
                "shipping": shipping_cost,
                "taxes": float(order.get("current_total_tax", 0)) if order.get("current_total_tax") is not None else float(order.get("total_tax", 0)),
                "total": calculated_total,
                "outstanding_balance": float(order.get("total_outstanding", 0)),
                "shipping_method": shipping_method,
                "payment_method": payment_mode,
                "billing_province_name": order.get("billing_address", {}).get("province") if order.get("billing_address") else None,
                "shipping_province_name": order.get("shipping_address", {}).get("province") if order.get("shipping_address") else None,
                "delivery_status": shopify_shipment_status,
                "secondary_status": order.get("cancel_reason"),
            }

            # --- LIVE AUDITING MODULE: TRACK TRANSACTION MUTATIONS ---
            existing_parent = None
            for retry in range(3):
                try:
                    existing_parent = supabase.table("shopify_orders").select("*").eq("order_id", order_id).execute()
                    break
                except Exception:
                    time.sleep(2)

            if not existing_parent or not existing_parent.data:
                print(f"✨ [NEW ORDER] Inserted: {current_order_name} (ID: {order_id})")
            else:
                old_data = existing_parent.data[0]
                mutations = []
                for key, new_val in parent_order.items():
                    old_val = old_data.get(key)
                    # Standardize ISO timestamps for comparison to prevent false timezone mutation logs
                    clean_old = str(old_val).replace("T", " ").split("+")[0].split(".")[0].strip() if old_val else ""
                    clean_new = str(new_val).replace("T", " ").split("+")[0].split(".")[0].strip() if new_val else ""
                    
                    if clean_old != clean_new:
                        mutations.append(f"'{key}': {old_val} ➡️ {new_val}")
                
                if mutations:
                    print(f"🔄 [UPDATED ORDER] {current_order_name} structural changes: {', '.join(mutations)}")
                else:
                    print(f"💤 [NO CHANGES DETECTED] Order: {current_order_name}")

            # Database write deployment with error isolation retry wrappers
            for retry in range(3):
                try:
                    supabase.table("shopify_orders").upsert(parent_order).execute()
                    break
                except Exception as db_err:
                    if retry == 2: print(f"❌ Connection timeout writing parent tracking to table: {db_err}")
                    time.sleep(4)
            
          # --- EXTRACT ONLY LEGITIMATE ACTIVE LINE ITEMS ---
            active_fulfillment_item_ids = set()
            for ful in order.get("fulfillments", []):
                if ful.get("status") == "success":
                    for f_item in ful.get("line_items", []):
                        active_fulfillment_item_ids.add(str(f_item.get("id")))

            for item in order.get("line_items", []):
                lineitem_id = str(item["id"])
                variant_id = item.get("variant_id")
                
                # CRITICAL FILTER: Ignore edited out / removed ghost items
                if active_fulfillment_item_ids and lineitem_id not in active_fulfillment_item_ids:
                    print(f"🗑️ [SKIPPING REMOVED ITEM] Ignored ghost sub-row: {item['name']} (ID: {lineitem_id})")
                    continue

                

                if int(item.get("quantity", 0)) == 0:
                    continue

                # Collect valid item IDs to track what should exist in Supabase
                active_fulfillment_item_ids.append(lineitem_id)
                
                
                existing_item = None
                for retry in range(3):
                    try:
                        existing_item = supabase.table("shopify_order_items").select("hsn_code").eq("lineitem_id", lineitem_id).execute()
                        break
                    except Exception:
                        time.sleep(2)
                
                hsn_check = None
                if existing_item and existing_item.data:
                    hsn_check = existing_item.data[0].get("hsn_code")
                    
                if hsn_check is not None and str(hsn_check).lower().strip() not in ["none", "null", "nan", ""]:
                    target_hsn = clean_and_slice_hsn(hsn_check)
                else:
                    target_hsn = fetch_live_hsn_from_shopify(variant_id)
                
                child_item = {
                    "lineitem_id": lineitem_id,
                    "order_id": order_id,
                    "variant_id": str(variant_id) if variant_id else None,
                    "lineitem_name": item["name"],
                    "lineitem_quantity": int(item["quantity"]),
                    "lineitem_price": float(item["price"]),
                    "lineitem_fulfillment_status": item["fulfillment_status"],
                    "tax_1_name": tax_1_name,
                    "tax_1_value": tax_1_value,
                    "hsn_code": target_hsn,
                }
                
                for retry in range(3):
                    try:
                        supabase.table("shopify_order_items").upsert(child_item).execute()
                        break
                    except Exception as db_err:
                        if retry == 2: print(f"❌ Connection timeout writing sub-row line item mapping: {db_err}")
                        time.sleep(4)




            # --- DETECT AND PURGE DELETED LINE ITEMS FROM SUPABASE WITH LOGGING ---
            try:
                # Fetch all line items currently stored in Supabase for this order
                db_items = supabase.table("shopify_order_items").select("lineitem_id, lineitem_name").eq("order_id", order_id).execute()
                
                if db_items and db_items.data:
                    for db_row in db_items.data:
                        stored_id = str(db_row.get("lineitem_id"))
                        item_name = db_row.get("lineitem_name", "Unknown Item")
                        
                        # If an item exists in DB but is no longer in the active list, purge it!
                        if stored_id not in active_fulfillment_item_ids:
                            print(f"🔥 [PURGING STALE ITEM FROM DATABASE] Order: {current_order_name} | Removing deleted line item: '{item_name}' (ID: {stored_id})")
                            supabase.table("shopify_order_items").delete().eq("lineitem_id", stored_id).execute()
            except Exception as purge_err:
                print(f"⚠️ Error during line item purge tracking for Order {current_order_name}: {purge_err}")



            
            # Move pagination forward using the latest processed ID reference string
            current_since_id = int(order_id)
            
        # Pacing window rest to maintain excellent API relationships
        time.sleep(1.5)

if __name__ == "__main__":
    run_historical_backfill()
