import os
import requests
from supabase import create_client, Client

# --- 1. CONFIGURATION & REAL DEPLOYMENT KEYS ---
SHOPIFY_STORE = "355b0d-2.myshopify.com"  
SHOPIFY_API_VERSION = "2024-04"           

# If keys exist in system environment (GitHub Actions), use them; otherwise fall back to raw keys
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN") or "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"
SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://wljftpkvsozgpxivbwiu.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "sb_secret_60ve-Yh8xAvI6MZkhQQR3Q_Fk2mP9If"

# Initialize Supabase Admin client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

shopify_headers = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN,
    "Content-Type": "application/json"
}

def get_stored_hsn(variant_id):
    """
    Checks separate local database lookup table for the HSN code first.
    If it's a new product variant, it pulls it from Shopify and saves it to the lookup table.
    """
    if not variant_id:
        return None
        
    try:
        # Check if we already have this product's HSN in our lookup table
        stored = supabase.table("shopify_product_hsn").select("hsn_code").eq("variant_id", str(variant_id)).execute()
        if stored.data and stored.data[0].get("hsn_code"):
            return stored.data[0]["hsn_code"]
    except Exception as e:
        print(f"Lookup database error for variant {variant_id}: {e}")
        
    # If not found in our database, make a one-time API call to Shopify to fetch it
    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/variants/{variant_id}.json"
    try:
        response = requests.get(url, headers=shopify_headers)
        if response.status_code == 200:
            variant = response.json().get("variant", {})
            hsn = variant.get("harmonized_system_code")
            
            # Save it to our lookup table so we NEVER have to call the Shopify variant API for this item again
            supabase.table("shopify_product_hsn").upsert({
                "variant_id": str(variant_id),
                "product_title": variant.get("title") or "Unknown Product",
                "variant_title": variant.get("title") or "Unknown Variant",
                "hsn_code": hsn
            }).execute()
            
            return hsn
    except Exception as e:
        print(f"Error fetching variant HSN from Shopify: {e}")
    return None

def sync_latest_orders():
    # Fetch the 50 most recent orders across all statuses to capture updates/changes
    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/orders.json?limit=50&status=any"
    print(f"Connecting to Shopify API to fetch orders...")
    response = requests.get(url, headers=shopify_headers)
    
    if response.status_code != 200:
        print(f"Failed to fetch orders from Shopify: {response.status_code} - {response.text}")
        return

    orders = response.json().get("orders", [])
    print(f"Found {len(orders)} orders to process. Starting sync...")
    
    for order in orders:
        order_id = str(order["id"])
        
        # Parse basic tax information details safely from the first line item tax lines if they exist
        tax_lines = order.get("tax_lines", [])
        tax_1_name = tax_lines[0].get("title") if len(tax_lines) > 0 else None
        tax_1_value = float(tax_lines[0].get("price")) if len(tax_lines) > 0 else 0.0

        # --- 2. MAP PARENT ORDER ROWS ---
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
        
        # Process parent insert or update smoothly
        supabase.table("shopify_orders").upsert(parent_order).execute()
        
        # --- 3. MAP CHILD LINE ITEMS (SUB-ROWS) ---
        for item in order.get("line_items", []):
            lineitem_id = str(item["id"])
            variant_id = item.get("variant_id")
            
            # Fetch the HSN code safely using our optimized lookup function
            current_hsn = get_stored_hsn(variant_id)
            
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
                "hsn_code": current_hsn  
            }
            
            # Process item sub-row updates or additions safely
            supabase.table("shopify_order_items").upsert(child_item).execute()

    print(f"Successfully processed {len(orders)} Shopify orders and verified their structural sub-item mappings.")

if __name__ == "__main__":
    sync_latest_orders()
