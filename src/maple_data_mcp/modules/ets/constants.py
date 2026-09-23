SOURCE = "ets"
BASE_URL = "https://gtfs.edmonton.ca/TMGTFSRealTimeWebService"
FEEDS = {
    "vehicles": f"{BASE_URL}/Vehicle/VehiclePositions.pb",
    "trip_updates": f"{BASE_URL}/TripUpdate/TripUpdates.pb",
    "alerts": f"{BASE_URL}/Alert/Alerts.pb",
}
TIMEZONE = "America/Edmonton"

RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 3.0

# The feeds regenerate about every 30 seconds; caching for 20 keeps
# repeated filtered calls from re-downloading the 1.6 MB trip feed.
CACHE_TTL_REALTIME_SECONDS = 20
CACHE_TTL_ALERTS_SECONDS = 5 * 60

LIMIT_DEFAULT = 50
LIMIT_MAX = 1000
