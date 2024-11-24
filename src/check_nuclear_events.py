import requests
import datetime
import argparse
import os

# Constants
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
SAFECAST_URL = "https://api.safecast.org/measurements.json"
MAG_THRESHOLD = 1.0  # Minimum magnitude
DEPTH_THRESHOLD = 2.0  # Maximum depth (in km)
RADIATION_SPIKE_THRESHOLD_CPM = 125  # Example threshold for radiation in CPM
REQUEST_TIMEOUT = 15  # Timeout for API requests in seconds

# Bluesky API Functions
def bsky_login_session(pds_url: str, handle: str, password: str):
    resp = requests.post(
        pds_url + "/xrpc/com.atproto.server.createSession",
        json={"identifier": handle, "password": password},
    )
    resp.raise_for_status()
    return resp.json()

def create_bsky_post(session, pds_url, post_content, embed=None):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    post = {
        "$type": "app.bsky.feed.post",
        "text": post_content,
        "createdAt": now,
    }
    if embed:
        post["embed"] = embed
    
    try:
        resp = requests.post(
            pds_url + "/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            json={
                "repo": session["did"],
                "collection": "app.bsky.feed.post",
                "record": post,
            },
        )
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e}")
        print(f"Response Status Code: {resp.status_code}")
        print(f"Response Content: {resp.text}")
        raise

    return resp.json()

# Seismic and Radiation Functions
def get_usgs_events():
    now = datetime.datetime.now(datetime.UTC)
    past = now - datetime.timedelta(minutes=10)
    params = {
        "format": "geojson",
        "starttime": past.isoformat(),
        "endtime": now.isoformat(),
        "minmagnitude": 0,
    }
    print(f"[INFO] Fetching USGS events from {past} to {now}...")
    try:
        response = requests.get(USGS_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        events = response.json().get("features", [])
        return events if events else []
    except requests.exceptions.Timeout:
        print("[WARNING] Timeout occurred while fetching USGS data.")
        return []
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Failed to fetch USGS data: {e}")
        return []

def get_nearest_radiation_sample(lat, lon):
    params = {
        "distance": 20,
        "latitude": lat,
        "longitude": lon,
    }
    try:
        print(f"[INFO] Fetching nearest radiation sample near ({lat}, {lon}) with a distance of {params['distance']} km...")
        response = requests.get(SAFECAST_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        # Debug: Log the raw response content
        print(f"[DEBUG] Raw Safecast API Response: {response.text}")

        data = response.json()
        if data and "measurements" in data and data["measurements"]:
            nearest_sample = min(data["measurements"], key=lambda x: x.get("value", float('inf')))
            radiation_value = float(nearest_sample["value"])
            unit = nearest_sample.get("unit", "unknown")
            timestamp = nearest_sample["captured_at"]
            return radiation_value, unit, timestamp
        return None, None, None
    except requests.exceptions.JSONDecodeError:
        print("[ERROR] Invalid JSON response from Safecast API.")
        return None, None, None
    except requests.exceptions.Timeout:
        print("[WARNING] Timeout occurred while fetching Safecast data.")
        return None, None, None
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] An error occurred: {e}")
        return None, None, None

def post_simulation_to_bsky(lat, lon, radiation_level):
    pds_url = "https://bsky.social"
    handle = os.getenv("BLUESKY_CLOSET_H")
    password = os.getenv("BLUESKY_CLOSET_P")

    session = bsky_login_session(pds_url, handle, password)

    post_content = (
        f"🌍 Simulation Results 🌍\n\n"
        f"Simulated Location: ({lat}, {lon})\n"
        f"Simulated Radiation Level: {radiation_level} CPM\n\n"
        f"Simulation completed successfully.\n#Simulation #Radiation"
    )
    
    create_bsky_post(session, pds_url, post_content)

def post_alert_to_bsky(lat, lon, magnitude, depth, radiation_level, radiation_unit, radiation_time):
    pds_url = "https://bsky.social"
    handle = os.getenv("BLUESKY_CLOSET_H")
    password = os.getenv("BLUESKY_CLOSET_P")

    session = bsky_login_session(pds_url, handle, password)

    post_content = (
        f"⚠️ Alert: Possible Detonation Detected ⚠️\n\n"
        f"Location: ({lat}, {lon})\n"
        f"Seismic Event: Magnitude {magnitude}, Depth {depth} km\n"
        f"Radiation Level: {radiation_level:.2f} {radiation_unit}\n"
        f"Captured At: {radiation_time}\n\n"
        f"#SeismicActivity #RadiationAlert"
    )
    
    create_bsky_post(session, pds_url, post_content)

def main(simulate_lat=None, simulate_lon=None, simulate_radiation=None):
    if simulate_lat and simulate_lon and simulate_radiation:
        print(f"[SIMULATION] Simulating event at ({simulate_lat}, {simulate_lon}) with radiation {simulate_radiation} CPM.")
        post_simulation_to_bsky(simulate_lat, simulate_lon, simulate_radiation)
        if float(simulate_radiation) > RADIATION_SPIKE_THRESHOLD_CPM:
            print(f"[ALERT] Simulated radiation exceeds threshold! Possible detonation detected at ({simulate_lat}, {simulate_lon}).")
        else:
            print("[INFO] Simulated radiation does not exceed threshold.")
        return

    events = get_usgs_events()
    if not events:
        print("[INFO] No seismic events detected.")
        return

    latest_event = events[0]
    props = latest_event["properties"]
    geo = latest_event["geometry"]["coordinates"]
    magnitude = props.get("mag", "Unknown")
    depth = geo[2] if len(geo) > 2 else "Unknown"
    lat, lon = geo[1], geo[0]
    event_time = datetime.datetime.fromtimestamp(props["time"] / 1000).strftime("%Y-%m-%d %H:%M:%S UTC")

    radiation_level, radiation_unit, radiation_time = get_nearest_radiation_sample(lat, lon)
    if isinstance(magnitude, (int, float)) and magnitude >= MAG_THRESHOLD and depth <= DEPTH_THRESHOLD:
        if radiation_level and radiation_level > RADIATION_SPIKE_THRESHOLD_CPM:
            print(f"[ALERT] Possible detonation detected at ({lat}, {lon})!")
            print(f"[DETAILS] Detected radiation level: {radiation_level:.2f} {radiation_unit}")
            print(f"[DETAILS] Radiation sample captured at: {radiation_time}")
            post_alert_to_bsky(lat, lon, magnitude, depth, radiation_level, radiation_unit, radiation_time)
            return

    print("[INFO] No significant events detected.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monitor seismic and radiation events.")
    parser.add_argument("--simulate-lat", type=str, help="Latitude for simulated event", default=None)
    parser.add_argument("--simulate-lon", type=str, help="Longitude for simulated event", default=None)
    parser.add_argument("--simulate-radiation", type=str, help="Simulated radiation level", default=None)
    args = parser.parse_args()

    main(simulate_lat=args.simulate_lat, simulate_lon=args.simulate_lon, simulate_radiation=args.simulate_radiation)
