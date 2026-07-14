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
    print(f"❌ CRITICAL: Failed to initialize Supabase client. Check keys. Error: {e}")

shopify_headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}


def get_4_char_hsn(variant_id, order_id=None):
    """Hits Shopify APIs with deep structural debug checks to locate HSN codes."""
    if not variant_id or str(variant_id).lower() in ["none", ""]:
        print(f"   ⚠️ Skipping Variant Lookup: Received empty/invalid variant_id.")
        return None
        
    try:
        url = f"https://{SHOPIFY_STORE}/admin/api/2024-04/variants/{variant_id}.json"
        res = requests.get(url, headers=shopify_headers)
        
        if res.status_code == 429:
            print("   ⚠️ Shopify rate limit (429) hit. Waiting 5 seconds...")
            time.sleep(5)
            return get_4_char_hsn(variant_id, order_id)
            
        if res.status_code == 404:
            print(f"   ❌ Variant {variant_id} returned 404 (Not Found) on Shopify. (May be deleted/archived)")
            return None
            
        if res.status_code != 200:
            print(f"   ❌ Variant API returned unexpected status {res.status_code}. Response: {res.text}")
            return None
            
        # If variant exists, analyze its payload
        variant_data = res.json().get('variant', {})
        hsn_raw = variant_data.get('harmonized_system_code')
        
        # Scenario A: HSN is stored directly on the Variant (like your first 2500 items)
        if hsn_raw:
            clean_hsn = "".join([c for c in str(hsn_raw) if c.isdigit()])
            return clean_hsn[:4]
            
        # Scenario B: Target HSN is nested on the Linked Inventory Item
        inventory_item_id = variant_data.get('inventory_item_id')
        if inventory_item_id:
            inv_url = f"https://{SHOPIFY_STORE}/admin/api/2024-04/inventory_items/{inventory_item_id}.json"
            inv_res = requests.get(inv_url, headers=shopify_headers)
            
            if inv_res.status_code == 200:
                inv_hsn = inv_res.json().get('inventory_item', {}).get('harmonized_system_code')
                if inv_hsn:
                    clean_hsn = "".join([c for c in str(inv_hsn) if c.isdigit()])
                    return clean_hsn[:4]
                else:
                    print(f"   ⚠️ Variant {variant_id} exists, but HSN/Harmonized Code field is completely empty in Shopify.")
            else:
                print(f"   ❌ Failed to query Inventory Item {inventory_item_id}. Status: {inv_res.status_code}")
                
    except Exception as e:
        print(f"   ❌ Connection error trying to reach Shopify for Variant {variant_id}: {e}")
        
    return None


def repair_item_level_hsn():
    print("\n--- 🔍 INITIATING TARGETED SUB-ROW HSN REPAIR ENGINE ---")
    
    # 1. FETCH & PROCESS SAFELY WITHOUT USING BUGGY '.is_' OR '.eq()' BUILDERS
    try:
        print("Querying line items from shopify_order_items...")
        db_res = supabase.table("shopify_order_items").select("*").execute()
        raw_data = db_res.data
        print(f"Successfully retrieved {len(raw_data)} total entries from DB.")
    except Exception as e:
        print(f"❌ CRITICAL DATABASE ERROR: Could not read shopify_order_items table. Details: {e}")
        return

    # Filter out records missing their HSN codes safely in Python memory
    items_to_fix = []
    for row in raw_data:
        hsn_val = row.get("hsn_code")
        if hsn_val is None or str(hsn_val).lower().strip() in ["none", "null", "", "nan"]:
            items_to_fix.append(row)
            
    if not items_to_fix:
        print("✅ Perfect! No missing (NULL) HSN entries found in shopify_order_items table.")
        return
        
    print(f"🚨 Identified {len(items_to_fix)} items that have missing HSN codes in your database.")
    repaired_count = 0
    
    for item in items_to_fix:
        row_id = item.get("id")
        variant_id = item.get("variant_id")
        order_id = item.get("order_id")
        
        if not variant_id:
            print(f"⚠️ Skipping row {row_id} (Order {order_id}) because variant_id is missing/NULL in your DB.")
            continue
            
        print(f"Processing Item Variant {variant_id} for Order {order_id} (Row ID: {row_id})...")
        
        # 2. Fetch the clean HSN
        hsn_4 = get_4_char_hsn(variant_id, order_id=order_id)
        
        if hsn_4:
            try:
                # 3. Update only the single column in Supabase
                supabase.table("shopify_order_items").update({"hsn_code": hsn_4}).eq("id", row_id).execute()
                repaired_count += 1
                print(f" 🎯 SUCCESS: Patched HSN [{hsn_4}] onto Row {row_id}")
            except Exception as db_err:
                print(f" ❌ DATABASE WRITE ERROR: Failed writing HSN [{hsn_4}] to row {row_id}: {db_err}")
        else:
            print(f" ⚠️ SKIP: Could not find HSN code inside Shopify for Variant {variant_id}.")
            
        time.sleep(0.5)  # Safe spacing interval to protect API rates

    print(f"\n🎉 Process Complete! Successfully patched {repaired_count} sub-rows in this run.")


if __name__ == "__main__":
    repair_item_level_hsn()
