import os
import requests
from supabase import create_client, Client

# --- 1. CONFIGURATION & DEPLOYMENT KEYS ---
SHOPIFY_STORE = "355b0d-2.myshopify.com"  
SHOPIFY_API_VERSION = "2024-04"           

# Secure credential fallbacks
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN") or "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"
SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://wljftpkvsozgpxivbwiu.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "sb_secret_60ve-Yh8xAvI6MZkhQQR3Q_Fk2mP9If"

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

shopify_headers = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN,
    "Content-Type": "application/json"
}

def fetch_live_hsn_from_shopify(variant_id):
    """
    Fetches the current live HSN code directly from Shopify's Inventory API
    and returns only the first 4 characters.
    """
    if not variant_id:
        return None
        
    variant_url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/variants/{variant_id}.json"
    try:
        v_response = requests.get(variant_url, headers=shopify_headers)
        if v_response.status_code == 200:
            inventory_item_id = v_response.json().get("variant", {}).get("inventory_item_id")
            
            if inventory_item_id:
                inv_url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/inventory_items/{inventory_item_id}.json"
                inv_response = requests.get(inv_url, headers=shopify_headers)
                
                if inv_response.status_code == 200:
                    raw_hsn = inv_response.json().get("inventory_item", {}).get("harmonized_system_code")
                    
                    if raw_hsn:
                        clean_hsn = str(raw_hsn).strip()
                        # Capture and return exactly the first 4 characters
                        return clean_hsn[:4]
    except Exception as e:
        print(f"Error fetching live HSN for variant {variant_id}: {e}")
    return None

def sync_latest_orders():
    # Fetch the 50 most recent orders across all statuses to capture updates/changes
    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/orders.json?limit=50&status=any"
    print("Connecting to Shopify API...")
    response = requests.get(url, headers=shopify_headers)
    
    if response.status_code != 200:
        print(f"Failed to fetch orders: {response.status_code}")
        return

    orders = response.json().get("orders", [])
    print(f"Found {len(orders)} orders to process. Starting sync...")
    
    for order in orders:
        order_id = str(order["id"])
        
        # Parse basic tax information details safely from the first line item tax lines if they exist
        tax_lines = order.get("tax_lines", [])
        tax_1_name = tax_lines[0].get("title") if len(tax_lines) > 0 else None
        tax_1_value = float(tax_lines[0].get("price")) if len(tax_lines) > 0 else 0.0

        # --- 2. MAP PARENT ORDER (One row per order) ---
        parent_order = {
            "order_id": order_id,
            "name": order["name"],                                
            "created_at": order["created_at"],
            "financial_status": order["financial_status"],        
            "fulfillment_status": order["fulfillment_status"],    
            "currency": order["currency"],
            "subtotal": float(order.get("current_subtotal_price", 0)),
            "shipping": float(order.get("total_shipping_price_set", {}).get("shop_money", {}).get("amount", 0)),
            "taxes": float(order.get("total_tax", 0)),
            "total": float(order.get("total_price", 0)),
            "outstanding_balance": float(order.get("total_outstanding", 0)),
            "shipping_method": order.get("shipping_lines", [{}])[0].get("title") if order.get("shipping_lines") else None,
            "payment_method": order.get("payment_gateway_names", [None])[0],
            "billing_province_name": order.get("billing_address", {}).get("province"),
            "shipping_province_name": order.get("shipping_address", {}).get("province")
        }
        supabase.table("shopify_orders").upsert(parent_order).execute()
        
        # --- 3. MAP CHILD LINE ITEMS (Multiple sub-rows per order) ---
        for item in order.get("line_items", []):
            lineitem_id = str(item["id"])
            variant_id = item.get("variant_id")
            
            # Check if this specific line item already exists with an HSN code locked down
            existing_item = supabase.table("shopify_order_items").select("hsn_code").eq("lineitem_id", lineitem_id).execute()
            
            if existing_item.data and existing_item.data[0].get("hsn_code") is not None:
                # Keep the historic HSN exactly as it was captured on day one (Locked)
                target_hsn = existing_item.data[0]["hsn_code"]
            else:
                # It's a brand new order line or previously NULL; pull fresh HSN from Shopify and slice to 4 chars
                print(f"New or empty item row detected ({item['name']}). Fetching fresh 4-character HSN...")
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
                "hsn_code": target_hsn  # Locked permanently
            }
            supabase.table("shopify_order_items").upsert(child_item).execute()

    print(f"Successfully synced {len(orders)} orders with perfect transactional locking and 4-character HSN slicing.")

if __name__ == "__main__":
    sync_latest_orders()
