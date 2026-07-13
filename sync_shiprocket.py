import os
import requests
from supabase import create_client, Client

# --- CONFIGURATION & CREDENTIALS ---
SHIPROCKET_EMAIL = os.environ.get("SHIPROCKET_EMAIL") or "globoretail@gmail.com"
SHIPROCKET_PASSWORD = os.environ.get("SHIPROCKET_PASSWORD") or '8HBSa3WKrk$wWRxo@BYaZTzhdYzAh^pq'

SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://wljftpkvsozgpxivbwiu.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "sb_secret_60ve-Yh8xAvI6MZkhQQR3Q_Fk2mP9If"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_shiprocket_token():
    """Authenticates with Shiprocket to obtain a fresh temporary authorization token."""
    url = "https://apiv2.shiprocket.in/v1/external/auth/login"
    payload = {"email": SHIPROCKET_EMAIL, "password": SHIPROCKET_PASSWORD}
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            return response.json().get("token")
        else:
            print(f"Authentication failed with status code: {response.status_code}")
    except Exception as e:
        print(f"Error authenticating with Shiprocket: {e}")
    return None

def sync_all_shipments():
    print("Initiating full paginated Shiprocket historical sync...")
    
    token = get_shiprocket_token()
    if not token:
        print("Could not fetch a valid auth token. Sync aborted.")
        return
        
    shiprocket_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    current_page = 1
    total_processed = 0
    
    while True:
        print(f"Fetching page {current_page} from Shiprocket...")
        url = f"https://apiv2.shiprocket.in/v1/external/shipments?per_page=50&page={current_page}"
        
        try:
            response = requests.get(url, headers=shiprocket_headers)
            
            if response.status_code == 429:
                print("Hit Shiprocket rate limit. Resting for 10 seconds...")
                time.sleep(10)
                continue
                
            if response.status_code != 200:
                print(f"Failed to fetch data for page {current_page}: {response.status_code}")
                break
                
            shipments_data = response.json().get("data", [])
            
            # If the page is empty, we have reached the end of history!
            if not shipments_data:
                print(f"Reached the end of records. Historical sync finished successfully!")
                break
                
            print(f"Processing {len(shipments_data)} records from page {current_page}...")
            
            for shipment in shipments_data:
                shipment_id = str(shipment["id"])
                raw_date = shipment.get("shipment_created_at") or shipment.get("created_at")
                
                # Capture the clean readable order number (e.g., GLOBO1001) safely
                clean_channel_order_id = shipment.get("channel_order_id") or shipment.get("order_no")
                if not clean_channel_order_id or str(clean_channel_order_id).strip().lower() == "none":
                    clean_channel_order_id = shipment.get("order", {}).get("channel_order_id") or "None"

                mapped_shipment = {
                    "shipment_id": shipment_id,
                    "order_id": str(shipment.get("order_id")) if shipment.get("order_id") else None,
                    "channel_order_id": str(clean_channel_order_id).strip(),
                    "awb_number": shipment.get("awb") or shipment.get("awb_code") or "",
                    "courier_name": shipment.get("courier_name") or shipment.get("courier") or None,
                    "status": shipment.get("status"),
                    "status_code": shipment.get("status_code"),
                    "onboarding_status": shipment.get("onboarding_status"),
                    "created_at": str(raw_date) if raw_date else None
                }
                
                # Push data straight to Supabase
                supabase.table("shiprocket_shipments").upsert(mapped_shipment).execute()
                
            total_processed += len(shipments_data)
            print(f"Total shipments tracked so far: {total_processed}")
            
            # Move cleanly to the next page index
            current_page += 1
            time.sleep(1.0) # Light breathing room between pages to satisfy API rules
            
        except Exception as e:
            print(f"An unexpected crash occurred on page {current_page}: {e}")
            break

if __name__ == "__main__":
    sync_all_shipments()
