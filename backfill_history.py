import os
import time
import requests
from supabase import create_client, Client

# --- 1. BACKLOG CONTROLS (Safely wired for GitHub Manual Trigger) ---
START_ORDER_NAME = os.environ.get("START_ORDER_INPUT") or "#GLOBO13552"
BATCH_SIZE = 50                  # Number of orders to pull per API request page

# --- 2. CONFIGURATION & KEYS ---
SHOPIFY_STORE = "355b0d-2.myshopify.com"  
SHOPIFY_API_VERSION = "2024-04"           

SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN") or "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"
SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://wljftpkvsozgpxivbwiu.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "sb_secret_60ve-Yh8xAvI6MZkhQQR3Q_Fk2mP9If"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

shopify_headers = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN,
    "Content-Type": "application/json"
}

def fetch_live_hsn_from_shopify(variant_id):
    """Fetches live HSN directly from Shopify's Inventory API (1st 4 chars)."""
    if not variant_id or str(variant_id).strip() == "" or str(variant_id) == "None":
        return None
        
    variant_url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/variants/{str(variant_id).strip()}.json"
    try:
        time.sleep(1.0) # Safe pacing for variants API
        v_response = requests.get(variant_url, headers=shopify_headers)
        if v_response.status_code == 200:
            inventory_item_id = v_response.json().get("variant", {}).get("inventory_item_id")
            
            if inventory_item_id:
                inv_url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/inventory_items/{inventory_item_id}.json"
                inv_response = requests.get(inv_url, headers=shopify_headers)
                
                if inv_response.status_code == 200:
                    raw_hsn = inv_response.json().get("inventory_item", {}).get("harmonized_system_code")
                    if raw_hsn:
                        return str(raw_hsn).strip()[:4]
    except Exception as e:
        print(f"Error fetching HSN for variant {variant_id}: {e}")
    return None

def get_internal_id_from_name(order_name):
    """Converts your human order name string into Shopify's internal numeric ID using advanced query parameters."""
    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/orders.json?query=name:{requests.utils.quote(str(order_name).strip())}&status=any"
    res = requests.get(url, headers=shopify_headers)
    if res.status_code == 200 and res.json().get("orders"):
        return res.json()["orders"][0]["id"]
    return None

def run_historical_backfill():
    print(f"Starting historical migration sequence from target milestone: {START_ORDER_NAME}")
    
    # 1. Resolve your human name text down to Shopify's strict numeric ID order floor
    start_numeric_id = get_internal_id_from_name(START_ORDER_NAME)
    if not start_numeric_id:
        print(f"Could not locate an order matching the name '{START_ORDER_NAME}' inside Shopify. Aborting.")
        return
        
    # Subtract 1 from the ID to make sure we include the starting order itself in the search window
    current_since_id = start_numeric_id - 1
    
    while True:
        # 2. Request a perfectly sequenced chronological page using since_id
        url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/orders.json?limit={BATCH_SIZE}&status=any&since_id={current_since_id}&order=id%20asc"
        
        print(f"Requesting next batch of {BATCH_SIZE} orders following internal reference ID: {current_since_id}...")
        response = requests.get(url, headers=shopify_headers)
        
        if response.status_code != 200:
            print(f"API Rate limit or network block encountered: {response.status_code}. Stopping batch cycle.")
            break
            
        orders = response.json().get("orders", [])
        if not orders:
            print("Reached the absolute end of your historical Shopify records! Backfill process complete.")
            break
            
        print(f"Downloaded {len(orders)} orders. Beginning database write sequence...")
        
        for order in orders:
            order_id = str(order["id"])
            current_order_name = order["name"]
            
            tax_lines = order.get("tax_lines", [])
            tax_1_name = tax_lines[0].get("title") if len(tax_lines) > 0 else None
            tax_1_value = float(tax_lines[0].get("price")) if len(tax_lines) > 0 else 0.0

            # --- Safely extract Shopify's internal shipment status ---
            fulfillments = order.get("fulfillments", [])
            shopify_shipment_status = None
            if fulfillments and len(fulfillments) > 0:
                shopify_shipment_status = fulfillments[0].get("shipment_status")

            # --- MAP PARENT ---
            # Parse the time zone offset string out to force native local calendar dates
            raw_created_at = str(order["created_at"])
            clean_created_at = raw_created_at.replace("T", " ").split("+")[0].split(".")[0].strip()

            parent_order = {
                "order_id": order_id,
                "name": current_order_name,                                
                "created_at": clean_created_at,  # <-- FIXED: Locked to native local time
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
            supabase.table("shopify_orders").upsert(parent_order).execute()
            
            # --- MAP CHILD ITEMS ---
            for item in order.get("line_items", []):
                lineitem_id = str(item["id"])
                variant_id = item.get("variant_id")
                
                existing_item = supabase.table("shopify_order_items").select("hsn_code").eq("lineitem_id", lineitem_id).execute()
                
                if existing_item.data and existing_item.data[0].get("hsn_code") is not None:
                    target_hsn = existing_item.data[0]["hsn_code"]
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
                supabase.table("shopify_order_items").upsert(child_item).execute()
            
            # Update pointer tracking so the pagination loop moves forward accurately
            current_since_id = int(order_id)
            print(f"Processed and verified order: {current_order_name}")
            
        # Mandatory 1.5 second structural rest to keep Shopify API happy between bulk pages
        time.sleep(1.5)

if __name__ == "__main__":
    run_historical_backfill()
