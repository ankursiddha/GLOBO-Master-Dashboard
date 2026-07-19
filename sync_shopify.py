import os
import time
import requests
import datetime
from supabase import create_client, Client

# --- 1. BACKLOG & PIPELINE CONTROLS (Preserved Exactly) ---
START_ORDER_NAME = os.environ.get("START_ORDER_INPUT") or "#GLOBO13552"
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
    """Isolates numeric characters strictly and slices the first 4 (From HSN Repair Engine)"""
    if not raw_hsn or str(raw_hsn).lower().strip() in ["none", "null", "nan", ""]:
        return None
    numeric_hsn = "".join([c for c in str(raw_hsn) if c.isdigit()])
    return numeric_hsn[:4] if numeric_hsn else None

def fetch_live_hsn_from_shopify(variant_id):
    """Deep Variant and Inventory Item check with integrated rate-limit back-off handling"""
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
                    
                # Cross-API reference fallbacks to Inventory Level properties
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

def get_internal_id_from_name(order_name):
    """Resolves visible order text milestone markers down to internal Shopify sequence integers"""
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
            
            # Extract basic operational tax information layouts
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

            parent_order = {
                "order_id": order_id,
                "name": current_order_name,                                
                "created_at": clean_created_at,  
                "financial_status": order["financial_status"],        
                "fulfillment_status": order["fulfillment_status"],    
                "currency": order["currency"],
                "subtotal": float(order.get("current_subtotal_price", 0)),
                "shipping": float(order.get("total_shipping_price_set", {}).get("shop_money", {}).get("amount", 0)),
                "taxes": float(order.get("total_tax", 0)),
                "total": float(order.get("total_price", 0)),
                "outstanding_balance": float(order.get("total_outstanding", 0)),
                "shipping_method": order.get("shipping_lines", [{}])[0].get("title") if order.get("shipping_lines") else None,
                "payment_method": order.get("payment_gateway_names", [None])[0] if order.get("payment_gateway_names") else None,
                "billing_province_name": order.get("billing_address").get("province") if order.get("billing_address") else None,
                "shipping_province_name": order.get("shipping_address").get("province") if order.get("shipping_address") else None,
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
                    if str(old_val).strip() != str(new_val).strip():
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
            
            # --- CHILD ITEM VALIDATION SUB-LOOP ---
            for item in order.get("line_items", []):
                lineitem_id = str(item["id"])
                variant_id = item.get("variant_id")
                
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

            # Move pagination forward using the latest processed ID reference string
            current_since_id = int(order_id)
            
        # Pacing window rest to maintain excellent API relationships
        time.sleep(1.5)

if __name__ == "__main__":
    run_historical_backfill()
