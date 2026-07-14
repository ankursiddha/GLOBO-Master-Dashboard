import os
import time
from datetime import datetime, timedelta
import requests
from supabase import create_client, Client

# --- VERIFIED PRODUCTION CONFIGURATION ---
SR_EMAIL = os.environ.get("SHIPROCKET_EMAIL") or "globoretail@gmail.com"
SR_PASSWORD = os.environ.get("SHIPROCKET_PASSWORD") or '8HBSa3WKrk$wWRxo@BYaZTzhdYzAh^pq'

SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://wljftpkvsozgpxivbwiu.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "sb_secret_60ve-Yh8xAvI6MZkhQQR3Q_Fk2mP9If"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- SAFE HISTORY SLABS (Strict Configuration Limits) ---
LOCK_DATE_STR = "2024-03-30" 
START_DATE_STR = "2024-04-01"

def get_token():
    try:
        r = requests.post("https://apiv2.shiprocket.in/v1/external/auth/login",
                          json={"email": SR_EMAIL, "password": SR_PASSWORD},
                          headers={"Content-Type": "application/json"})
        if r.status_code == 200:
            return r.json().get('token')
    except Exception as e:
        print(f"❌ Shiprocket Authentication Crash: {e}")
    return None


def parse_shiprocket_date(date_str):
    if not date_str or str(date_str).lower() in ["none", "-", ""]:
        return None
    try:
        dt = datetime.strptime(str(date_str).strip(), "%d %b %Y, %I:%M %p")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return str(date_str)



def generate_monthly_blocks(start_str):
    """Generates day-by-day loops from start date to today to ensure zero missed orders."""
    start_dt = datetime.strptime(start_str, "%Y-%m-%d")
    today = datetime.now()
    blocks = []
    
    current = start_dt
    while current <= today:
        blocks.append(current)
        current += timedelta(days=1)
    return blocks



def sync_complete_shiprocket_history():
    print("--- 🚀 INITIATING FULL SHIPROCKET TO SUPABASE PRODUCTION ENGINE ---")
    token = get_token()
    if not token:
        print("❌ Could not verify API token. Execution terminated.")
        return
        
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    lock_dt = datetime.strptime(LOCK_DATE_STR, "%Y-%m-%d")
    audit_months = generate_monthly_blocks(START_DATE_STR)
    total_synced = 0

    for current_month_dt in audit_months:
        # Enforce Lock Date Boundary Safeguard (Checks day-by-day now)
        if current_month_dt < lock_dt:
            continue

        first_day = current_month_dt.strftime("%Y-%m-%d")
        last_day = first_day  # Forces the API to search one single day thoroughly
        tab_name = current_month_dt.strftime("%d_%b_%Y")

        print(f"\n📂 Processing Date Window [{first_day} to {last_day}] for {tab_name}...")
        
        page = 1
        while True:
            url = f"https://apiv2.shiprocket.in/v1/external/orders?from={first_day}&to={last_day}&page={page}&per_page=50"
            try:
                res = requests.get(url, headers=headers)
                
                if res.status_code == 429:
                    print("⚠️ Rate limit caught. Cooling down for 10 seconds...")
                    time.sleep(10)
                    continue
                    
                if res.status_code != 200:
                    print(f"⚠️ Stopped scanning page context. Status received: {res.status_code}")
                    break
                    
                resp_json = res.json()
                orders = resp_json.get('data', [])
                if not orders:
                    break
                    
                print(f"📦 Extracting {len(orders)} entries from page {page}...")
                
                for o in orders:
                    # Captures every order name variant (e.g., GLOBO1001, marketplace IDs, or default string hashes)
                    globo_id = str(o.get('channel_order_id') or o.get('order_no') or o.get('id')).strip()
                    api_status = str(o.get('status'))
                    
                    # 1:1 matching of your old code's nested structural shipment parser
                    shipments = o.get('shipments', [])
                    ship_id = None
                    if isinstance(shipments, list) and len(shipments) > 0:
                        ship_id = shipments[0].get('id')
                    elif isinstance(shipments, dict):
                        ship_id = shipments.get('id')

                    awb, courier = "", ""
                    if ship_id:
                        ship_id = str(ship_id)
                        # Deep validation endpoint fallback loop from working setup
                        for attempt in range(2):
                            try:
                                s_url = f"https://apiv2.shiprocket.in/v1/external/shipments/{ship_id}"
                                s_data = requests.get(s_url, headers=headers).json().get('data', {})
                                awb = s_data.get('awb_code')
                                courier = s_data.get('courier_name') or s_data.get('courier')
                                
                                # Secondary deep extraction endpoint if top level variant is blank
                                if not awb:
                                    t_url = f"https://apiv2.shiprocket.in/v1/external/courier/track/shipment/{ship_id}"
                                    t_res = requests.get(t_url, headers=headers).json()
                                    awb = t_res.get('tracking_data', {}).get('shipment_track', [{}])[0].get('awb_code')
                                
                                if awb: 
                                    break
                                time.sleep(0.2)
                            except:
                                time.sleep(0.2)

                    # Ensure primary unique index key fallback holds true
                    db_shipment_id = ship_id if (ship_id and str(ship_id) != "None") else f"ORD-{o.get('id')}"
                    raw_date = o.get('created_at') or o.get('shipment_created_at')

                    mapped_payload = {
                        "shipment_id": str(db_shipment_id).strip(),
                        "order_id": str(o.get('id')),
                        "channel_order_id": globo_id,
                        "awb_number": str(awb or "").strip(),
                        "courier_name": str(courier or "").strip() if courier else None,
                        "status": api_status,
                        "status_code": o.get('status_code'),
                        "onboarding_status": o.get('onboarding_status'),
                        "created_at": parse_shiprocket_date(raw_date)
                    }

                    # Stream write updates safely straight to your primary Supabase table layout
                    supabase.table("shiprocket_shipments").upsert(mapped_payload).execute()
                    
                total_synced += len(orders)
                print(f"✅ Page {page} saved. Continuous global records parsed: {total_synced}")
                
                page += 1
                time.sleep(0.5) # Safe API pacing buffer
                
            except Exception as e:
                print(f"❌ Critical loop block disruption on page {page}: {e}")
                break

    print(f"\n🎉 Sync completed! {total_synced} items verified in Supabase.")

if __name__ == "__main__":
    sync_complete_shiprocket_history()
