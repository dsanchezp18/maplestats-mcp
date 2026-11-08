SOURCE = "bc_transit"
BASE_URL = "https://bct.tmix.se/gtfs-realtime"
FEED_FILES = {
    "vehicles": "vehiclepositions.pb",
    "trip_updates": "tripupdates.pb",
    "alerts": "alerts.pb",
}
TERMS_URL = "https://www.bctransit.com/open-data/terms-of-use/"

# Keys match the static agencies in transit/constants.py (a unit test keeps
# the operator ids in step), so a stop or route found with transit_* can be
# looked up here with the same key.
SYSTEMS: dict[str, tuple[str, int]] = {
    "bct_victoria": ("Victoria", 48),
    "bct_kelowna": ("Kelowna", 47),
    "bct_kamloops": ("Kamloops", 46),
    "bct_nanaimo": ("Nanaimo", 41),
    "bct_prince_george": ("Prince George", 22),
    "bct_fraser_valley": ("Fraser Valley (Chilliwack)", 13),
    "bct_north_okanagan": ("North Okanagan (Vernon)", 14),
    "bct_comox_valley": ("Comox Valley", 45),
    "bct_cowichan_valley": ("Cowichan Valley", 10),
    "bct_campbell_river": ("Campbell River", 12),
    "bct_squamish": ("Squamish", 43),
    "bct_whistler": ("Whistler", 44),
}


def feed_url(feed: str, operator_id: int) -> str:
    return f"{BASE_URL}/{FEED_FILES[feed]}?operatorIds={operator_id}"


RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 3.0

# Positions and predictions move every few seconds; 20 s keeps repeated
# filtered calls from re-downloading Victoria's ~600-800 KB trip feed.
CACHE_TTL_REALTIME_SECONDS = 20
CACHE_TTL_ALERTS_SECONDS = 5 * 60

LIMIT_DEFAULT = 50
LIMIT_MAX = 1000
