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

def get_4_char_hsn(variant_id, order_id=None):
    """Fetches HSN via variant id. If it throws a 404, falls back to reading the order context data directly."""
    if not variant_id or str(variant_id).lower() in ["none", ""]:
        return None
    try:
        # Step 1: Attempt standard variant endpoint call
        url = f"https://{SHOPIFY_STORE}/admin/api/2024-04/variants/{variant_id}.json"
        res = requests.get(url, headers=shopify_headers)
        
        if res.status_code == 200:
            variant_data = res.json().get('variant', {})
            inventory_item_id = variant_data.get('inventory_item_id')
            if inventory_item_id:
                inv_url = f"https://{SHOPIFY_STORE}/admin/api/2024-04/inventory_items/{inventory_item_id}.json"
                inv_res = requests.get(inv_url, headers=shopify_headers)
                if inv_res.status_code == 200:
                    hsn_raw = inv_res.json().get('inventory_item', {}).get('harmonized_system_code')
                    if hsn_raw:
                        return "".join([c for c in str(hsn_raw) if c.isdigit()])[:4]
                        
        # Step 2: Fallback if the variant is deleted or missing (Status 404)
        if (res.status_code == 404 or not hsn_raw) and order_id:
            print(f"🔄 Variant 404 caught. Querying historical Order {order_id} payload for archive matching...")
            order_url = f"https://{SHOPIFY_STORE}/admin/api/2024-04/orders/{order_id}.json"
            o_res = requests.get(order_url, headers=shopify_headers)
            
            if o_res.status_code == 200:
                line_items = o_res.json().get('order', {}).get('line_items', [])
                for item in line_items:
                    # Match by variant_id or fallback string matching on name if id properties shifted
                    if str(item.get('variant_id')) == str(variant_id):
                        # Some older API payloads store the target code directly in the line item customs details
                        hsn_raw = item.get('tax_lines', [{}])[0].get('rate') # deep checkout fallback check
                        # If not inside tax properties, pull item properties array
                        properties = item.get('properties', [])
                        for p in properties:
                            if 'hsn' in str(p.get('name')).lower():
                                hsn_raw = p.get('value')
                
                if hsn_raw:
                    return "".join([c for c in str(hsn_raw) if c.isdigit()])[:4]

    except Exception as e:
        print(f"❌ Error during fallback engine search: {e}")
    return None




def repair_item_level_hsn():
    print("--- 🔍 INITIATING TARGETED SUB-ROW HSN REPAIR ENGINE ---")
    
    # 1. Pull data and filter blanks in local Python memory to avoid Supabase library version syntax errors
    db_res = supabase.table("shopify_order_items").select("*").execute()
    items_to_fix = [row for row in db_res.data if row.get("hsn_code") is None or str(row.get("hsn_code")).lower() in ["none", "null", ""]]
    
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
        
        # 2. Get the real 4-digit HSN code from the Inventory setup
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
