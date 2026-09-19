import requests
import datetime
import argparse
import os
import json
import sys
import math

# Constants
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
SAFECAST_URL = "https://api.safecast.org/measurements.json"
MAG_THRESHOLD = 1.0  # Minimum magnitude
DEPTH_THRESHOLD = 2.0  # Maximum depth (in km)
RADIATION_SPIKE_THRESHOLD_CPM = 125  # Threshold for radiation in CPM
REQUEST_TIMEOUT = 15  # Timeout for API requests in seconds
DEFAULT_LOOKBACK_MINUTES = 30
RADIATION_QUERY_DISTANCE_KM = 100
MAX_RADIATION_SAMPLE_DISTANCE_KM = 20
MAX_RADIATION_SAMPLE_AGE_MINUTES = 30

# Debug levels
DEBUG_NONE = 0
DEBUG_ERROR = 1
DEBUG_WARNING = 2
DEBUG_INFO = 3
DEBUG_DETAIL = 4
DEBUG_TRACE = 5

# Global debug level
DEBUG_LEVEL = DEBUG_INFO


class MonitoringDataError(RuntimeError):
    """Raised when a required monitoring source cannot provide usable data."""

def sanitize_message(message):
    """Sanitize sensitive data in debug messages"""
    sensitive_keys = {'password', 'secret'}
    
    def sanitize(value):
        if isinstance(value, dict):
            return {k: sanitize('***' if k.lower() in sensitive_keys else v) for k, v in value.items()}
        elif isinstance(value, list):
            return [sanitize(item) for item in value]
        elif isinstance(value, str):
            for key in sensitive_keys:
                value = value.replace(key, "***")
            return value
        return value
    
    return sanitize(message)

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


def workflow_warning(message):
    """Surface inconclusive checks in GitHub Actions without treating them as negative results."""
    debug_print(DEBUG_WARNING, message)
    if os.getenv("GITHUB_ACTIONS") == "true":
        print(f"::warning::{message}")

def pretty_json(data):
    """Return a pretty-printed JSON string"""
    return json.dumps(data, indent=2)

# Bluesky API Functions
def bsky_login_session(pds_url: str, handle: str, password: str):
    debug_print(DEBUG_INFO, f"Attempting Bluesky login with handle: {handle}")
    payload = {"identifier": handle, "password": password}
    debug_print(DEBUG_TRACE, f"Login payload: {json.dumps({'identifier': handle, 'password': '***'})}")
    
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
def post_to_bsky(post_type, lat, lon, magnitude=None, depth=None, event_time=None, event_url=None, radiation_level=None, radiation_unit=None, radiation_time=None, dry_run=False):
    debug_print(DEBUG_INFO, f"Preparing to post to Bluesky, post type: {post_type}")

    if post_type == "simulation":
        debug_print(DEBUG_INFO, f"Creating simulation post for coordinates: ({lat}, {lon})")
        post_content = (
            f"🌍 Simulation Results 🌍\n\n"
            f"Simulated Location: ({lat}, {lon})\n"
            f"Simulated Radiation Level: {radiation_level} CPM\n\n"
            f"Simulation completed successfully.\n#Simulation #Radiation"
        )
    elif post_type == "alert":
        debug_print(DEBUG_INFO, f"Creating unverified candidate post for potential detonation at: ({lat}, {lon})")
        post_content = (
            f"⚠️ Unverified automated candidate event\n\n"
            f"This is not an official nuclear warning.\n"
            f"Location: ({lat}, {lon})\n"
            f"USGS seismic event: Magnitude {magnitude}, Depth {depth} km\n"
            f"Event time: {event_time}\n"
            f"Radiation Level: {radiation_level:.2f} {radiation_unit}\n"
            f"Radiation sample time: {radiation_time}\n"
            f"USGS source: {event_url}\n\n"
            f"#Unverified #SeismicActivity #Radiation"
        )
    else:
        debug_print(DEBUG_ERROR, f"Invalid post type specified: {post_type}")
        return

    debug_print(DEBUG_DETAIL, f"Final post content: {post_content}")
    if dry_run:
        debug_print(DEBUG_WARNING, "DRY RUN: Bluesky post suppressed")
        return {"dry_run": True, "text": post_content}

    pds_url = "https://bsky.social"
    handle = os.getenv("BLUESKY_CLOSET_H")
    password = os.getenv("BLUESKY_CLOSET_P")
    if not handle or not password:
        debug_print(DEBUG_ERROR, "Missing Bluesky credentials in environment variables")
        return

    session = bsky_login_session(pds_url, handle, password)
    create_bsky_post(session, pds_url, post_content)

# Seismic and Radiation Functions
def get_usgs_events(lookback_minutes, monitoring_end=None):
    monitoring_end = monitoring_end or datetime.datetime.now(datetime.UTC)
    past = monitoring_end - datetime.timedelta(minutes=lookback_minutes)
    params = {
        "format": "geojson",
        "starttime": past.isoformat(),
        "endtime": monitoring_end.isoformat(),
        "minmagnitude": 0,
    }
    debug_print(DEBUG_INFO, f"Fetching USGS events from {past.isoformat()} to {monitoring_end.isoformat()}")
    debug_print(DEBUG_DETAIL, f"USGS API request parameters: {pretty_json(params)}")
    debug_print(DEBUG_DETAIL, f"USGS API URL: {USGS_URL}")
    
    try:
        debug_print(DEBUG_TRACE, "Sending request to USGS API...")
        response = requests.get(USGS_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
        events = data.get("features")
        if not isinstance(events, list):
            raise MonitoringDataError("USGS response did not contain an events list")
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
            
        return events
    except requests.exceptions.Timeout as error:
        raise MonitoringDataError("Timed out while fetching USGS data") from error
    except requests.exceptions.RequestException as e:
        raise MonitoringDataError(f"Failed to fetch USGS data: {e}") from e
    except MonitoringDataError:
        raise
    except Exception as e:
        raise MonitoringDataError(f"Unexpected error while processing USGS data: {e}") from e


def haversine_distance_km(lat_a, lon_a, lat_b, lon_b):
    """Return the great-circle distance between two latitude/longitude pairs."""
    earth_radius_km = 6371.0
    lat_delta = math.radians(lat_b - lat_a)
    lon_delta = math.radians(lon_b - lon_a)
    latitude_a = math.radians(lat_a)
    latitude_b = math.radians(lat_b)
    haversine = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(latitude_a) * math.cos(latitude_b) * math.sin(lon_delta / 2) ** 2
    )
    return 2 * earth_radius_km * math.asin(math.sqrt(haversine))


def parse_capture_time(captured_at):
    if isinstance(captured_at, (int, float)):
        return datetime.datetime.fromtimestamp(captured_at, datetime.UTC)
    if not isinstance(captured_at, str):
        return None

    try:
        parsed = datetime.datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def is_cpm_unit(unit):
    normalized = "".join(character for character in str(unit).lower() if character.isalnum())
    return normalized in {"cpm", "countsperminute"}

def get_nearest_radiation_sample(lat, lon, event_time, monitoring_end=None):
    monitoring_end = monitoring_end or datetime.datetime.now(datetime.UTC)
    params = {
        "distance": RADIATION_QUERY_DISTANCE_KM,
        "latitude": lat,
        "longitude": lon,
        "captured_after": event_time.isoformat(),
        "captured_before": monitoring_end.isoformat(),
    }
    debug_print(DEBUG_INFO, f"Fetching radiation samples within {params['distance']} km of ({lat}, {lon})")
    debug_print(DEBUG_DETAIL, f"Safecast API request parameters: {pretty_json(params)}")
    debug_print(DEBUG_DETAIL, f"Safecast API URL: {SAFECAST_URL}")
    
    try:
        debug_print(DEBUG_TRACE, "Sending request to Safecast API...")
        response = requests.get(SAFECAST_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

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
            
            candidates = []
            for measurement in measurements:
                try:
                    radiation_value = float(measurement["value"])
                    sample_latitude = float(measurement["latitude"])
                    sample_longitude = float(measurement["longitude"])
                except (KeyError, TypeError, ValueError):
                    debug_print(DEBUG_TRACE, "Ignoring radiation sample with missing or invalid value or coordinates")
                    continue

                captured_at = measurement.get("captured_at")
                captured_time = parse_capture_time(captured_at)
                distance_km = haversine_distance_km(lat, lon, sample_latitude, sample_longitude)
                sample_age = monitoring_end - captured_time if captured_time else None
                if (
                    not math.isfinite(radiation_value)
                    or not is_cpm_unit(measurement.get("unit"))
                    or captured_time is None
                    or captured_time < event_time
                    or captured_time > monitoring_end
                    or sample_age < datetime.timedelta()
                    or sample_age > datetime.timedelta(minutes=MAX_RADIATION_SAMPLE_AGE_MINUTES)
                    or distance_km > MAX_RADIATION_SAMPLE_DISTANCE_KM
                ):
                    debug_print(DEBUG_TRACE, "Ignoring radiation sample that predates the event, is stale, non-CPM, or outside the search radius")
                    continue

                candidates.append((distance_km, radiation_value, measurement["unit"], captured_at))

            if candidates:
                distance_km, radiation_value, unit, timestamp = min(candidates, key=lambda sample: sample[0])
                debug_print(DEBUG_INFO, f"Nearest usable radiation sample: {radiation_value} {unit} at {distance_km:.1f} km, captured at {timestamp}")
                return radiation_value, unit, timestamp

            workflow_warning(
                f"No recent CPM radiation measurements within {MAX_RADIATION_SAMPLE_DISTANCE_KM} km of the seismic event; result is inconclusive"
            )
            return None, None, None
        else:
            workflow_warning(
                f"Safecast returned no radiation measurements within {RADIATION_QUERY_DISTANCE_KM} km of the seismic event; result is inconclusive"
            )
            return None, None, None
    except requests.exceptions.JSONDecodeError as error:
        raise MonitoringDataError("Safecast returned invalid JSON") from error
    except requests.exceptions.Timeout as error:
        raise MonitoringDataError("Timed out while fetching Safecast data") from error
    except requests.exceptions.RequestException as e:
        raise MonitoringDataError(f"Safecast API request failed: {e}") from e
    except MonitoringDataError:
        raise
    except Exception as e:
        raise MonitoringDataError(f"Unexpected error while processing Safecast data: {e}") from e

# Main Function
def main(simulate_lat=None, simulate_lon=None, simulate_radiation=None, lookback_minutes=DEFAULT_LOOKBACK_MINUTES, dry_run=False):
    debug_print(DEBUG_INFO, "Starting nuclear event monitoring process")
    if dry_run:
        debug_print(DEBUG_WARNING, "DRY RUN: Bluesky notifications are disabled")

    if lookback_minutes <= 0:
        raise ValueError("Lookback minutes must be greater than zero")

    simulation_values = (simulate_lat, simulate_lon, simulate_radiation)
    if any(value is not None for value in simulation_values) and not all(simulation_values):
        raise ValueError("Simulation requires latitude, longitude, and radiation values")
    
    # Simulation mode
    if simulate_lat and simulate_lon and simulate_radiation:
        debug_print(DEBUG_INFO, f"Running in SIMULATION mode with parameters:")
        debug_print(DEBUG_INFO, f"  - Latitude: {simulate_lat}")
        debug_print(DEBUG_INFO, f"  - Longitude: {simulate_lon}")
        debug_print(DEBUG_INFO, f"  - Radiation: {simulate_radiation} CPM")
        
        post_to_bsky(
            "simulation",
            simulate_lat,
            simulate_lon,
            radiation_level=simulate_radiation,
            dry_run=dry_run,
        )
        
        radiation_value = float(simulate_radiation)
        if radiation_value > RADIATION_SPIKE_THRESHOLD_CPM:
            debug_print(DEBUG_WARNING, f"SIMULATION: Radiation exceeds threshold of {RADIATION_SPIKE_THRESHOLD_CPM} CPM!")
            debug_print(DEBUG_WARNING, f"SIMULATION: Possible detonation detected at ({simulate_lat}, {simulate_lon}) with radiation {radiation_value} CPM")
        else:
            debug_print(DEBUG_INFO, f"SIMULATION: Radiation level {radiation_value} CPM does not exceed threshold of {RADIATION_SPIKE_THRESHOLD_CPM} CPM")
        return "simulation"

    # Normal monitoring mode
    debug_print(DEBUG_INFO, "Running in normal monitoring mode")
    debug_print(DEBUG_INFO, f"Thresholds: Magnitude >= {MAG_THRESHOLD}, Depth <= {DEPTH_THRESHOLD} km, Radiation > {RADIATION_SPIKE_THRESHOLD_CPM} CPM")
    
    monitoring_end = datetime.datetime.now(datetime.UTC)
    events = get_usgs_events(lookback_minutes, monitoring_end)
    if not events:
        debug_print(DEBUG_INFO, "No seismic events detected in the monitoring window")
        return "no_events"

    debug_print(DEBUG_INFO, f"Processing {len(events)} seismic events")
    
    # Process all events, not just the first one
    events_examined = 0
    inconclusive_events = 0
    for event in events:
        events_examined += 1
        props = event["properties"]
        geo = event["geometry"]["coordinates"]
        magnitude = props.get("mag", None)
        depth = geo[2] if len(geo) > 2 else None
        lat, lon = geo[1], geo[0]
        place = props.get("place", "Unknown location")
        event_observed_at = datetime.datetime.fromtimestamp(props["time"] / 1000, datetime.UTC)
        event_time = event_observed_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        event_url = props.get("url", "Unavailable")
        
        debug_print(DEBUG_INFO, f"Examining event #{events_examined}: Magnitude {magnitude} at {place}")
        debug_print(DEBUG_DETAIL, f"  - Coordinates: ({lat}, {lon})")
        debug_print(DEBUG_DETAIL, f"  - Depth: {depth} km")
        debug_print(DEBUG_DETAIL, f"  - Time: {event_time}")
        
        # Check if this event meets the seismic criteria for a potential nuclear event
        if (
            isinstance(magnitude, (int, float))
            and isinstance(depth, (int, float))
            and math.isfinite(magnitude)
            and math.isfinite(depth)
            and magnitude >= MAG_THRESHOLD
            and depth <= DEPTH_THRESHOLD
        ):
            debug_print(DEBUG_WARNING, f"Event meets seismic criteria: Magnitude {magnitude} >= {MAG_THRESHOLD} and Depth {depth} km <= {DEPTH_THRESHOLD} km")
            
            # Now check for radiation levels near the event
            debug_print(DEBUG_INFO, f"Checking radiation levels near ({lat}, {lon})")
            radiation_level, radiation_unit, radiation_time = get_nearest_radiation_sample(
                lat,
                lon,
                event_observed_at,
                monitoring_end,
            )
            
            if radiation_level is not None:
                debug_print(DEBUG_DETAIL, f"Found radiation level: {radiation_level} {radiation_unit} at {radiation_time}")
                
                if radiation_level > RADIATION_SPIKE_THRESHOLD_CPM:
                    debug_print(DEBUG_WARNING, f"CANDIDATE: Radiation level {radiation_level} {radiation_unit} exceeds threshold of {RADIATION_SPIKE_THRESHOLD_CPM} CPM!")
                    debug_print(DEBUG_WARNING, f"CANDIDATE: Unverified seismic and radiation correlation at ({lat}, {lon})!")
                    
                    post_to_bsky(
                        "alert",
                        lat,
                        lon,
                        magnitude=magnitude,
                        depth=depth,
                        event_time=event_time,
                        event_url=event_url,
                        radiation_level=radiation_level,
                        radiation_unit=radiation_unit,
                        radiation_time=radiation_time,
                        dry_run=dry_run,
                    )
                    return "candidate"
                else:
                    debug_print(DEBUG_INFO, f"Radiation level {radiation_level} {radiation_unit} does not exceed threshold of {RADIATION_SPIKE_THRESHOLD_CPM} CPM")
            else:
                inconclusive_events += 1
                debug_print(DEBUG_WARNING, f"Could not retrieve usable radiation data for location ({lat}, {lon})")
        else:
            debug_print(DEBUG_DETAIL, f"Event does not meet seismic criteria (requires mag >= {MAG_THRESHOLD} and depth <= {DEPTH_THRESHOLD} km)")

    if inconclusive_events:
        workflow_warning(
            f"Monitoring complete: {inconclusive_events} qualifying seismic event(s) lacked usable radiation evidence; result is inconclusive"
        )
        return "inconclusive"

    debug_print(DEBUG_INFO, "Monitoring complete - No candidate events detected")
    return "no_candidate"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monitor seismic and radiation events for potential nuclear detonations.")
    parser.add_argument("--simulate-lat", type=str, help="Latitude for simulated event", default=None)
    parser.add_argument("--simulate-lon", type=str, help="Longitude for simulated event", default=None)
    parser.add_argument("--simulate-radiation", type=str, help="Simulated radiation level", default=None)
    parser.add_argument("--debug-level", type=int, help="Debug level (0-5)", default=DEBUG_INFO)
    parser.add_argument("--lookback-minutes", type=int, help="USGS lookback window in minutes", default=DEFAULT_LOOKBACK_MINUTES)
    parser.add_argument("--dry-run", action="store_true", help="Evaluate candidates without posting to Bluesky")
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
        main(
            simulate_lat=args.simulate_lat,
            simulate_lon=args.simulate_lon,
            simulate_radiation=args.simulate_radiation,
            lookback_minutes=args.lookback_minutes,
            dry_run=args.dry_run,
        )
        debug_print(DEBUG_INFO, "Script completed successfully")
    except Exception as e:
        debug_print(DEBUG_ERROR, f"Script failed with error: {str(e)}")
        import traceback
        debug_print(DEBUG_ERROR, traceback.format_exc())
        sys.exit(1)
