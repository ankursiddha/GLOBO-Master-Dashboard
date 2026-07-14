import os
import time
import requests
from supabase import create_client, Client

# --- PRODUCTION AUTHENTICATION CONFIGURATION ---
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE_URL") or "355b0d-2.myshopify.com"
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ADMIN_ACCESS_TOKEN") or "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"

SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://wljftpkvsozgpxivbwiu.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "sb_secret_60ve-Yh8xAvI6MZkhQQR3Q_Fk2mP9If"

print("--- ⚙️ INITIALIZING CREDENTIAL CHECK ---")
print(f"Target Store: {SHOPIFY_STORE}")
print(f"Supabase Endpoint: {SUPABASE_URL}")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase client initialized successfully.")
except Exception as e:
    print(f"❌ CRITICAL: Failed to initialize Supabase client. Error: {e}")

shopify_headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}


def get_4_char_hsn(variant_id, order_id=None):
    """Hits Shopify APIs to locate HSN codes."""
    if not variant_id or str(variant_id).lower() in ["none", ""]:
        return None
        
    try:
        url = f"https://{SHOPIFY_STORE}/admin/api/2024-04/variants/{variant_id}.json"
        res = requests.get(url, headers=shopify_headers)
        
        if res.status_code == 429:
            time.sleep(5)
            return get_4_char_hsn(variant_id, order_id)
            
        if res.status_code == 200:
            variant_data = res.json().get('variant', {})
            hsn_raw = variant_data.get('harmonized_system_code')
            
            # 1. Try direct variant data check
            if hsn_raw:
                clean_hsn = "".join([c for c in str(hsn_raw) if c.isdigit()])
                return clean_hsn[:4]
                
            # 2. Try connected inventory item endpoint fallback
            inventory_item_id = variant_data.get('inventory_item_id')
            if inventory_item_id:
                inv_url = f"https://{SHOPIFY_STORE}/admin/api/2024-04/inventory_items/{inventory_item_id}.json"
                inv_res = requests.get(inv_url, headers=shopify_headers)
                if inv_res.status_code == 200:
                    inv_hsn = inv_res.json().get('inventory_item', {}).get('harmonized_system_code')
                    if inv_hsn:
                        clean_hsn = "".join([c for c in str(inv_hsn) if c.isdigit()])
                        return clean_hsn[:4]
                        
    except Exception as e:
        print(f"   ❌ Connection error reaching Shopify for Variant {variant_id}: {e}")
        
    return None


def repair_item_level_hsn():
    print("\n--- 🔍 INITIATING TARGETED SUB-ROW HSN REPAIR ENGINE ---")
    
    try:
        db_res = supabase.table("shopify_order_items").select("*").execute()
        raw_data = db_res.data
    except Exception as e:
        print(f"❌ CRITICAL DATABASE ERROR: Could not read table. Details: {e}")
        return

    # Filter out missing records
    items_to_fix = []
    for row in raw_data:
        hsn_val = row.get("hsn_code")
        if hsn_val is None or str(hsn_val).lower().strip() in ["none", "null", "", "nan"]:
            items_to_fix.append(row)
            
    if not items_to_fix:
        print("✅ Perfect! No missing (NULL) HSN entries found in shopify_order_items table.")
        return
        
    print(f"🚨 Identified {len(items_to_fix)} items requiring HSN updates.")
    repaired_count = 0
    
    for item in items_to_fix:
        # --- FIXED KEY MATCHING: CHANGED FROM 'id' TO 'lineitem_id' ---
        row_id = item.get("lineitem_id") 
        variant_id = item.get("variant_id")
        order_id = item.get("order_id")
        
        if not row_id:
            print(f"⚠️ Skipping row: lineitem_id is completely missing from this data row record.")
            continue
            
        if not variant_id:
            continue
            
        print(f"Processing Line Item {row_id} (Variant {variant_id}) for Order {order_id}...")
        
        hsn_4 = get_4_char_hsn(variant_id, order_id=order_id)
        
        if hsn_4:
            try:
                # --- FIXED UPDATE MATCHING COLUMN KEY ---
                supabase.table("shopify_order_items").update({"hsn_code": hsn_4}).eq("lineitem_id", row_id).execute()
                repaired_count += 1
                print(f" 🎯 SUCCESS: Patched HSN [{hsn_4}] onto Line Item {row_id}")
            except Exception as db_err:
                print(f" ❌ DATABASE WRITE ERROR: Failed writing HSN [{hsn_4}] to lineitem_id {row_id}: {db_err}")
        else:
            print(f" ⚠️ SKIP: Could not find HSN code inside Shopify for Variant {variant_id}.")
            
        time.sleep(0.5)

    print(f"\n🎉 Process Complete! Successfully patched {repaired_count} sub-rows in this run.")


if __name__ == "__main__":
    repair_item_level_hsn()
