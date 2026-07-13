import os
import requests
from supabase import create_client, Client

# --- CONFIGURATION & CREDENTIALS ---
SHIPROCKET_EMAIL = os.environ.get("SHIPROCKET_EMAIL") or "globoretail@gmail.com"
SHIPROCKET_PASSWORD = os.environ.get("SHIPROCKET_PASSWORD") or '8HBSa3WKrk$wWRxo@BYaZTzhdYzAh^pq'

SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://wljftpkvsozgpxivbwiu.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "sb_secret_60ve-Yh8xAvI6MZkhQQR3Q_Fk2mP9If"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def clean_shiprocket_date(date_str):
    """Converts Shiprocket human date format (e.g., '14th Apr 2025 09:11 PM') into clean ISO timestamp."""
    if not date_str:
        return None
    try:
        # Strip out text suffixes like 'th', 'st', 'nd', 'rd' from the day number
        clean_str = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', str(date_str).strip())
        
        # Parse standard string: '14 Apr 2025 09:11 PM'
        parsed_dt = datetime.strptime(clean_str, "%d %b %Y %I:%M %p")
        return parsed_dt.isoformat()
    except Exception as e:
        print(f"Date conversion skip for '{date_str}': {e}")
        return None

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

def sync_latest_shipments():
    print("Initiating Shiprocket data synchronization...")
    
    token = get_shiprocket_token()
    if not token:
        print("Could not fetch a valid auth token. Sync aborted.")
        return
        
    shiprocket_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    # Fetch the 50 most recent shipments from Shiprocket
    url = "https://apiv2.shiprocket.in/v1/external/shipments?per_page=50"
    response = requests.get(url, headers=shiprocket_headers)
    
    if response.status_code != 200:
        print(f"Failed to fetch shipments from Shiprocket: {response.status_code}")
        return
        
    shipments_data = response.json().get("data", [])
    print(f"Found {len(shipments_data)} shipments to process.")
    
    for shipment in shipments_data:
        shipment_id = str(shipment["id"])
        
        # Safe extraction and conversion of created_at date format
        raw_date = shipment.get("created_at")
        iso_date = clean_shiprocket_date(raw_date)
        
        mapped_shipment = {
            "shipment_id": shipment_id,
            "order_id": str(shipment.get("order_id")) if shipment.get("order_id") else None,
            "channel_order_id": str(shipment.get("channel_order_id")),
            "awb_number": shipment.get("awb"),
            "courier_name": shipment.get("courier"),
            "status": shipment.get("status"),
            "status_code": shipment.get("status_code"),
            "onboarding_status": shipment.get("onboarding_status"),
            "created_at": iso_date
        }
        
        # Save securely to Supabase via Upsert
        supabase.table("shiprocket_shipments").upsert(mapped_shipment).execute()
        print(f"Synced shipment: {shipment_id} | AWB: {shipment.get('awb')}")
        
    print("Shiprocket synchronization cycle completed successfully.")

if __name__ == "__main__":
    sync_latest_shipments()
    sync_latest_shipments()
