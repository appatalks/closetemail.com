import requests
import datetime
import argparse
import os
import json
import sys

# Constants
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
SAFECAST_URL = "https://api.safecast.org/measurements.json"
MAG_THRESHOLD = 1.0  # Minimum magnitude
DEPTH_THRESHOLD = 2.0  # Maximum depth (in km)
RADIATION_SPIKE_THRESHOLD_CPM = 125  # Threshold for radiation in CPM
REQUEST_TIMEOUT = 15  # Timeout for API requests in seconds

# Debug levels
DEBUG_NONE = 0
DEBUG_ERROR = 1
DEBUG_WARNING = 2
DEBUG_INFO = 3
DEBUG_DETAIL = 4
DEBUG_TRACE = 5

# Global debug level
DEBUG_LEVEL = DEBUG_INFO

def sanitize_message(message):
    """Sanitize sensitive data in debug messages"""
    if isinstance(message, dict):
        return {k: '***' if k.lower() in ['password', 'secret'] else v for k, v in message.items()}
    elif isinstance(message, str):
        return message.replace("password", "***").replace("secret", "***")
    return message

def debug_print(level, message):
    """Print debug messages if debug level is sufficient"""
    levels = {
        DEBUG_ERROR: "[ERROR]",
        DEBUG_WARNING: "[WARNING]",
        DEBUG_INFO: "[INFO]",
        DEBUG_DETAIL: "[DETAIL]",
        DEBUG_TRACE: "[TRACE]"
    }
    sanitized_message = sanitize_message(message)
    if level <= DEBUG_LEVEL and level in levels:
        print(f"{levels[level]} {sanitized_message}")
    elif level <= DEBUG_LEVEL:
        print(f"[DEBUG-{level}] {sanitized_message}")

def pretty_json(data):
    """Return a pretty-printed JSON string"""
    return json.dumps(data, indent=2)

# Bluesky API Functions
def bsky_login_session(pds_url: str, handle: str, password: str):
    debug_print(DEBUG_INFO, f"Attempting Bluesky login with handle: {handle}")
    payload = {"identifier": handle, "password": password}
    debug_print(DEBUG_TRACE, sanitize_message(f"Login payload: {json.dumps(payload)}"))
    
    try:
        debug_print(DEBUG_DETAIL, f"Sending login request to {pds_url}/xrpc/com.atproto.server.createSession")
        resp = requests.post(
            pds_url + "/xrpc/com.atproto.server.createSession",
            json=payload,
        )
        resp.raise_for_status()
        debug_print(DEBUG_INFO, f"Bluesky login successful for {handle}")
        session_data = resp.json()
        debug_print(DEBUG_TRACE, f"Received session data with DID: {session_data.get('did', 'unknown')}")
        return session_data
    except requests.exceptions.HTTPError as e:
        debug_print(DEBUG_ERROR, f"HTTP Error during Bluesky login: {e}")
        debug_print(DEBUG_ERROR, f"Response Status Code: {resp.status_code}")
        debug_print(DEBUG_ERROR, f"Response Content: {resp.text}")
        raise
    except Exception as e:
        debug_print(DEBUG_ERROR, f"Unexpected error during Bluesky login: {str(e)}")
        raise

def create_bsky_post(session, pds_url, post_content, embed=None):
    debug_print(DEBUG_INFO, "Creating Bluesky post")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    post = {
        "$type": "app.bsky.feed.post",
        "text": post_content,
        "createdAt": now,
    }
    if embed:
        post["embed"] = embed
    
    debug_print(DEBUG_DETAIL, f"Post content: {post_content}")
    
    try:
        payload = {
            "repo": session["did"],
            "collection": "app.bsky.feed.post",
            "record": post,
        }
        debug_print(DEBUG_TRACE, f"Post request payload: {pretty_json(payload)}")
        
        debug_print(DEBUG_DETAIL, f"Sending post request to {pds_url}/xrpc/com.atproto.repo.createRecord")
        resp = requests.post(
            pds_url + "/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": "Bearer " + session["accessJwt"]},
            json=payload,
        )
        resp.raise_for_status()
        result = resp.json()
        debug_print(DEBUG_INFO, f"Post successful, received URI: {result.get('uri', 'unknown')}")
        return result
    except requests.exceptions.HTTPError as e:
        debug_print(DEBUG_ERROR, f"HTTP Error during Bluesky post creation: {e}")
        debug_print(DEBUG_ERROR, f"Response Status Code: {resp.status_code}")
        debug_print(DEBUG_ERROR, f"Response Content: {resp.text}")
        raise
    except Exception as e:
        debug_print(DEBUG_ERROR, f"Unexpected error during Bluesky post creation: {str(e)}")
        raise

# Combined Posting Function
def post_to_bsky(post_type, lat, lon, magnitude=None, depth=None, radiation_level=None, radiation_unit=None, radiation_time=None):
    debug_print(DEBUG_INFO, f"Preparing to post to Bluesky, post type: {post_type}")
    pds_url = "https://bsky.social"
    handle = os.getenv("BLUESKY_CLOSET_H")
    password = os.getenv("BLUESKY_CLOSET_P")
    
    if not handle or not password:
        debug_print(DEBUG_ERROR, "Missing Bluesky credentials in environment variables")
        return

    session = bsky_login_session(pds_url, handle, password)

    if post_type == "simulation":
        debug_print(DEBUG_INFO, f"Creating simulation post for coordinates: ({lat}, {lon})")
        post_content = (
            f"🌍 Simulation Results 🌍\n\n"
            f"Simulated Location: ({lat}, {lon})\n"
            f"Simulated Radiation Level: {radiation_level} CPM\n\n"
            f"Simulation completed successfully.\n#Simulation #Radiation"
        )
    elif post_type == "alert":
        debug_print(DEBUG_INFO, f"Creating alert post for potential detonation at: ({lat}, {lon})")
        post_content = (
            f"⚠️ Alert: Possible Detonation Detected ⚠️\n\n"
            f"Location: ({lat}, {lon})\n"
            f"Seismic Event: Magnitude {magnitude}, Depth {depth} km\n"
            f"Radiation Level: {radiation_level:.2f} {radiation_unit}\n"
            f"Captured At: {radiation_time}\n\n"
            f"#SeismicActivity #RadiationAlert"
        )
    else:
        debug_print(DEBUG_ERROR, f"Invalid post type specified: {post_type}")
        return

    debug_print(DEBUG_DETAIL, f"Final post content: {post_content}")
    create_bsky_post(session, pds_url, post_content)

# Seismic and Radiation Functions
def get_usgs_events():
    now = datetime.datetime.now(datetime.UTC)
    past = now - datetime.timedelta(minutes=15)  # Check back in time 15 minutes for seismic events indicative of ground burst
    params = {
        "format": "geojson",
        "starttime": past.isoformat(),
        "endtime": now.isoformat(),
        "minmagnitude": 0,
    }
    debug_print(DEBUG_INFO, f"Fetching USGS events from {past.isoformat()} to {now.isoformat()}")
    debug_print(DEBUG_DETAIL, f"USGS API request parameters: {pretty_json(params)}")
    debug_print(DEBUG_DETAIL, f"USGS API URL: {USGS_URL}")
    
    try:
        debug_print(DEBUG_TRACE, "Sending request to USGS API...")
        response = requests.get(USGS_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
        events = data.get("features", [])
        event_count = len(events)
        debug_print(DEBUG_INFO, f"USGS API returned {event_count} seismic events")
        
        if DEBUG_LEVEL >= DEBUG_DETAIL and event_count > 0:
            debug_print(DEBUG_DETAIL, "Event details:")
            for i, event in enumerate(events[:5]):  # Show details for up to first 5 events
                props = event["properties"]
                geo = event["geometry"]["coordinates"]
                mag = props.get("mag", "Unknown")
                place = props.get("place", "Unknown location")
                event_time = datetime.datetime.fromtimestamp(props["time"] / 1000).strftime("%Y-%m-%d %H:%M:%S UTC")
                debug_print(DEBUG_DETAIL, f"  {i+1}. Magnitude {mag} at {place}, Coordinates: ({geo[1]}, {geo[0]}), Depth: {geo[2]} km, Time: {event_time}")
            
            if event_count > 5:
                debug_print(DEBUG_DETAIL, f"  ... and {event_count - 5} more events")
        
        if DEBUG_LEVEL >= DEBUG_TRACE:
            debug_print(DEBUG_TRACE, f"Full USGS API response: {pretty_json(data)}")
            
        return events if events else []
    except requests.exceptions.Timeout:
        debug_print(DEBUG_WARNING, "Timeout occurred while fetching USGS data")
        return []
    except requests.exceptions.RequestException as e:
        debug_print(DEBUG_ERROR, f"Failed to fetch USGS data: {e}")
        return []
    except Exception as e:
        debug_print(DEBUG_ERROR, f"Unexpected error while processing USGS data: {str(e)}")
        return []

def get_nearest_radiation_sample(lat, lon):
    params = {
        "distance": 20,
        "latitude": lat,
        "longitude": lon,
    }
    debug_print(DEBUG_INFO, f"Fetching nearest radiation sample near ({lat}, {lon}) with a distance of {params['distance']} km")
    debug_print(DEBUG_DETAIL, f"Safecast API request parameters: {pretty_json(params)}")
    debug_print(DEBUG_DETAIL, f"Safecast API URL: {SAFECAST_URL}")
    
    try:
        debug_print(DEBUG_TRACE, "Sending request to Safecast API...")
        response = requests.get(SAFECAST_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        # Debug: Log the raw response content at TRACE level
        debug_print(DEBUG_TRACE, f"Raw Safecast API Response: {response.text[:1000]}..." if len(response.text) > 1000 else response.text)

        data = response.json()
        
        # Check specifically for measurements
        measurements = []
        if isinstance(data, dict) and "measurements" in data:
            measurements = data["measurements"]
        elif isinstance(data, list):
            measurements = data
            
        measurement_count = len(measurements)
        debug_print(DEBUG_INFO, f"Safecast API returned {measurement_count} radiation measurements")
        
        if measurement_count > 0:
            # Debug details of the radiation samples
            if DEBUG_LEVEL >= DEBUG_DETAIL:
                debug_print(DEBUG_DETAIL, "Radiation measurement details:")
                for i, measurement in enumerate(measurements[:5]):  # Show details for up to first 5 measurements
                    value = measurement.get("value", "Unknown")
                    unit = measurement.get("unit", "Unknown")
                    timestamp = measurement.get("captured_at", "Unknown time")
                    location = f"({measurement.get('latitude', '?')}, {measurement.get('longitude', '?')})"
                    debug_print(DEBUG_DETAIL, f"  {i+1}. Value: {value} {unit}, Location: {location}, Time: {timestamp}")
                
                if measurement_count > 5:
                    debug_print(DEBUG_DETAIL, f"  ... and {measurement_count - 5} more measurements")
            
            # Find the nearest sample (using the min value as a heuristic)
            nearest_sample = min(measurements, key=lambda x: x.get("value", float('inf')))
            radiation_value = float(nearest_sample.get("value", 0))
            unit = nearest_sample.get("unit", "unknown")
            timestamp = nearest_sample.get("captured_at", "unknown time")
            
            debug_print(DEBUG_INFO, f"Nearest radiation sample: {radiation_value} {unit} captured at {timestamp}")
            return radiation_value, unit, timestamp
        else:
            debug_print(DEBUG_WARNING, "No radiation measurements found in the area")
            return None, None, None
    except requests.exceptions.JSONDecodeError:
        debug_print(DEBUG_ERROR, "Invalid JSON response from Safecast API")
        return None, None, None
    except requests.exceptions.Timeout:
        debug_print(DEBUG_WARNING, "Timeout occurred while fetching Safecast data")
        return None, None, None
    except requests.exceptions.RequestException as e:
        debug_print(DEBUG_ERROR, f"API request error: {e}")
        return None, None, None
    except Exception as e:
        debug_print(DEBUG_ERROR, f"Unexpected error while processing Safecast data: {str(e)}")
        return None, None, None

# Main Function
def main(simulate_lat=None, simulate_lon=None, simulate_radiation=None):
    debug_print(DEBUG_INFO, "Starting nuclear event monitoring process")
    
    # Simulation mode
    if simulate_lat and simulate_lon and simulate_radiation:
        debug_print(DEBUG_INFO, f"Running in SIMULATION mode with parameters:")
        debug_print(DEBUG_INFO, f"  - Latitude: {simulate_lat}")
        debug_print(DEBUG_INFO, f"  - Longitude: {simulate_lon}")
        debug_print(DEBUG_INFO, f"  - Radiation: {simulate_radiation} CPM")
        
        post_to_bsky("simulation", simulate_lat, simulate_lon, radiation_level=simulate_radiation)
        
        radiation_value = float(simulate_radiation)
        if radiation_value > RADIATION_SPIKE_THRESHOLD_CPM:
            debug_print(DEBUG_WARNING, f"SIMULATION: Radiation exceeds threshold of {RADIATION_SPIKE_THRESHOLD_CPM} CPM!")
            debug_print(DEBUG_WARNING, f"SIMULATION: Possible detonation detected at ({simulate_lat}, {simulate_lon}) with radiation {radiation_value} CPM")
        else:
            debug_print(DEBUG_INFO, f"SIMULATION: Radiation level {radiation_value} CPM does not exceed threshold of {RADIATION_SPIKE_THRESHOLD_CPM} CPM")
        return

    # Normal monitoring mode
    debug_print(DEBUG_INFO, "Running in normal monitoring mode")
    debug_print(DEBUG_INFO, f"Thresholds: Magnitude >= {MAG_THRESHOLD}, Depth <= {DEPTH_THRESHOLD} km, Radiation > {RADIATION_SPIKE_THRESHOLD_CPM} CPM")
    
    events = get_usgs_events()
    if not events:
        debug_print(DEBUG_INFO, "No seismic events detected in the monitoring window")
        return

    debug_print(DEBUG_INFO, f"Processing {len(events)} seismic events")
    
    # Process all events, not just the first one
    events_examined = 0
    for event in events:
        events_examined += 1
        props = event["properties"]
        geo = event["geometry"]["coordinates"]
        magnitude = props.get("mag", None)
        depth = geo[2] if len(geo) > 2 else None
        lat, lon = geo[1], geo[0]
        place = props.get("place", "Unknown location")
        event_time = datetime.datetime.fromtimestamp(props["time"] / 1000).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        debug_print(DEBUG_INFO, f"Examining event #{events_examined}: Magnitude {magnitude} at {place}")
        debug_print(DEBUG_DETAIL, f"  - Coordinates: ({lat}, {lon})")
        debug_print(DEBUG_DETAIL, f"  - Depth: {depth} km")
        debug_print(DEBUG_DETAIL, f"  - Time: {event_time}")
        
        # Check if this event meets the seismic criteria for a potential nuclear event
        if isinstance(magnitude, (int, float)) and magnitude >= MAG_THRESHOLD and depth <= DEPTH_THRESHOLD:
            debug_print(DEBUG_WARNING, f"Event meets seismic criteria: Magnitude {magnitude} >= {MAG_THRESHOLD} and Depth {depth} km <= {DEPTH_THRESHOLD} km")
            
            # Now check for radiation levels near the event
            debug_print(DEBUG_INFO, f"Checking radiation levels near ({lat}, {lon})")
            radiation_level, radiation_unit, radiation_time = get_nearest_radiation_sample(lat, lon)
            
            if radiation_level is not None:
                debug_print(DEBUG_DETAIL, f"Found radiation level: {radiation_level} {radiation_unit} at {radiation_time}")
                
                if radiation_level > RADIATION_SPIKE_THRESHOLD_CPM:
                    debug_print(DEBUG_WARNING, f"ALERT: Radiation level {radiation_level} {radiation_unit} exceeds threshold of {RADIATION_SPIKE_THRESHOLD_CPM} CPM!")
                    debug_print(DEBUG_WARNING, f"ALERT: Possible nuclear detonation detected at ({lat}, {lon})!")
                    
                    post_to_bsky("alert", lat, lon, magnitude, depth, radiation_level, radiation_unit, radiation_time)
                    return  # Stop after posting an alert
                else:
                    debug_print(DEBUG_INFO, f"Radiation level {radiation_level} {radiation_unit} does not exceed threshold of {RADIATION_SPIKE_THRESHOLD_CPM} CPM")
            else:
                debug_print(DEBUG_WARNING, f"Could not retrieve radiation data for location ({lat}, {lon})")
        else:
            debug_print(DEBUG_DETAIL, f"Event does not meet seismic criteria (requires mag >= {MAG_THRESHOLD} and depth <= {DEPTH_THRESHOLD} km)")
    
    debug_print(DEBUG_INFO, "Monitoring complete - No significant events detected")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monitor seismic and radiation events for potential nuclear detonations.")
    parser.add_argument("--simulate-lat", type=str, help="Latitude for simulated event", default=None)
    parser.add_argument("--simulate-lon", type=str, help="Longitude for simulated event", default=None)
    parser.add_argument("--simulate-radiation", type=str, help="Simulated radiation level", default=None)
    parser.add_argument("--debug-level", type=int, help="Debug level (0-5)", default=DEBUG_INFO)
    parser.add_argument("--output", type=str, help="Output debug to file", default=None)
    args = parser.parse_args()
    
    # Set debug level from command line
    DEBUG_LEVEL = args.debug_level
    debug_print(DEBUG_INFO, f"Debug level set to {DEBUG_LEVEL}")
    
    # Set up file output if requested
    if args.output:
        try:
            sys.stdout = open(args.output, 'w')
            debug_print(DEBUG_INFO, f"Debug output will be written to {args.output}")
        except Exception as e:
            print(f"Error setting up output file: {str(e)}")
    
    # Print basic system info
    debug_print(DEBUG_INFO, f"Script started at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    debug_print(DEBUG_DETAIL, f"Python version: {sys.version}")
    debug_print(DEBUG_DETAIL, f"Running on: {sys.platform}")
    
    try:
        main(simulate_lat=args.simulate_lat, simulate_lon=args.simulate_lon, simulate_radiation=args.simulate_radiation)
        debug_print(DEBUG_INFO, "Script completed successfully")
    except Exception as e:
        debug_print(DEBUG_ERROR, f"Script failed with error: {str(e)}")
        import traceback
        debug_print(DEBUG_ERROR, traceback.format_exc())
        sys.exit(1)
