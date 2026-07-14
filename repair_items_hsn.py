import os
import time
import requests
from supabase import create_client, Client

# --- PRODUCTION AUTHENTICATION CONFIGURATION ---
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE_URL") or "globo-retail.myshopify.com"
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ADMIN_ACCESS_TOKEN") or "shpat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://wljftpkvsozgpxivbwiu.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "sb_secret_60ve-Yh8xAvI6MZkhQQR3Q_Fk2mP9If"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
shopify_headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}

def get_4_char_hsn(variant_id):
    """Hits Shopify Variant API and returns exactly the first 4 digits of the HSN code."""
    if not variant_id or str(variant_id).lower() in ["none", ""]:
        return None
    try:
        url = f"https://{SHOPIFY_STORE}/admin/api/2024-04/variants/{variant_id}.json"
        res = requests.get(url, headers=shopify_headers)
        
        if res.status_code == 429:
            print("⚠️ Shopify Rate limit hit. Cooling down for 5 seconds...")
            time.sleep(5)
            return get_4_char_hsn(variant_id)
            
        if res.status_code == 200:
            variant_data = res.json().get('variant', {})
            hsn_raw = variant_data.get('harmonized_system_code')
            
            if hsn_raw:
                # Clean out any non-numeric symbols if present
                clean_hsn = "".join([c for c in str(hsn_raw) if c.isdigit()])
                # Slice down to strictly the first 4 characters as discussed
                return clean_hsn[:4]
    except Exception as e:
        print(f"❌ Error fetching variant {variant_id} from Shopify: {e}")
    return None

def repair_item_level_hsn():
    print("--- 🔍 INITIATING TARGETED SUB-ROW HSN REPAIR ENGINE ---")
    
    # 1. Fetch only line items from the sub-row table where HSN is missing
    db_res = supabase.table("shopify_order_items").select("*").is_("hsn_code", "null").execute()
    items_to_fix = db_res.data
    
    if not items_to_fix:
        print("✅ Perfect! No NULL HSN entries found in shopify_order_items.")
        return
        
    print(f"🚨 Found {len(items_to_fix)} item sub-rows requiring HSN patches.")
    repaired_count = 0
    
    for item in items_to_fix:
        row_id = item.get("id") # The primary key of the line item row
        variant_id = item.get("variant_id")
        order_id = item.get("order_id") # For logging visibility
        
        if not variant_id:
            print(f"⚠️ Row {row_id} (Order {order_id}) has no variant_id saved. Skipping.")
            continue
            
        print(f"Processing Item Variant {variant_id} for Order {order_id}...")
        
        # 2. Get the 4-digit HSN code from Shopify
        hsn_4 = get_4_char_hsn(variant_id)
        
        if hsn_4:
            try:
                # 3. Update only the hsn_code field for this specific sub-row primary key
                supabase.table("shopify_order_items").update({"hsn_code": hsn_4}).eq("id", row_id).execute()
                repaired_count += 1
                print(f" 🎯 Success: Patched 4-Char HSN [{hsn_4}] onto Item Row {row_id}")
            except Exception as db_err:
                print(f" ❌ Database update failed for row {row_id}: {db_err}")
        else:
            print(f" ⚠️ Missing: No HSN code found inside Shopify settings for variant {variant_id}.")
            
        time.sleep(0.5) # Pacing buffer to be safe with API limits

    print(f"\n🎉 Item-level HSN patch complete. Total sub-rows updated: {repaired_count}")

if __name__ == "__main__":
    repair_item_level_hsn()
