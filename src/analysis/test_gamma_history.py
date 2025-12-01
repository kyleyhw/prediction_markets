import requests

def test_gamma_history():
    # ID from previous logs: "2890" (NBA Mavericks vs Grizzlies)
    # This is an Event ID, not a Market ID.
    # Market IDs in Gamma are usually integers too but different.
    
    # Let's try to find a valid Market ID first.
    url = "https://gamma-api.polymarket.com/events?limit=1&closed=true"
    resp = requests.get(url)
    data = resp.json()
    
    if not data:
        print("No events found.")
        return

    event = data[0]
    print(f"Event: {event.get('title')} (ID: {event.get('id')})")
    
    for m in event.get('markets', []):
        mid = m.get('id')
        
        # Parse CLOB ID properly
        raw_clob = m.get('clobTokenIds')
        if isinstance(raw_clob, str):
            try:
                clob_ids = json.loads(raw_clob)
            except:
                clob_ids = []
        else:
            clob_ids = raw_clob if raw_clob else []
            
        clob_id = clob_ids[0] if clob_ids else None
        
        print(f"  Market: {m.get('question')}")
        print(f"    Gamma ID: {mid}")
        print(f"    CLOB ID: {clob_id}")
        
        # Test Gamma API with Gamma ID
        g_url = "https://gamma-api.polymarket.com/prices-history"
        try:
            r = requests.get(g_url, params={"market": mid, "interval": "max"})
            print(f"    Gamma API (ID={mid}): Status={r.status_code}")
            if r.status_code != 200:
                print(f"    Response: {r.text[:200]}")
            else:
                try:
                    data = r.json()
                    print(f"    History Len: {len(data.get('history', []))}")
                except:
                    print(f"    JSON Parse Error. Text: {r.text[:200]}")
        except Exception as e:
            print(f"    Gamma API (ID={mid}) Failed: {e}")

        # Test CLOB API with CLOB ID
        if clob_id:
            c_url = "https://clob.polymarket.com/prices-history"
            try:
                r = requests.get(c_url, params={"market": clob_id, "interval": "max"})
                print(f"    CLOB API (ID={clob_id}): Status={r.status_code}")
                if r.status_code == 200:
                    print(f"    History Len: {len(r.json().get('history', []))}")
                else:
                    print(f"    Response: {r.text[:200]}")
            except Exception as e:
                print(f"    CLOB API (ID={clob_id}) Failed: {e}")

if __name__ == "__main__":
    # Test specific CLOB ID from 2022 (MATIC market)
    clob_id = "39608921829286159279395177465346248643664679934724914307971785633803345140210"
    print(f"Testing specific CLOB ID: {clob_id}")
    
    c_url = "https://clob.polymarket.com/prices-history"
    try:
        # Try different intervals
        for interval in ["max", "1d", "1h"]:
            print(f"  Testing interval={interval}...")
            r = requests.get(c_url, params={"market": clob_id, "interval": interval})
            print(f"    Status={r.status_code}")
            if r.status_code == 200:
                data = r.json()
                hist = data.get('history', [])
                print(f"    History Len: {len(hist)}")
                if hist:
                    print(f"    Sample: {hist[0]}")
            else:
                print(f"    Response: {r.text[:200]}")
    except Exception as e:
        print(f"    Failed: {e}")

    # test_gamma_history() # Skip the general search for now
