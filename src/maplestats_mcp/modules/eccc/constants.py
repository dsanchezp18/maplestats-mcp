"""Constants for the MSC GeoMet-OGC-API module.

Base URL and endpoint shapes confirmed live against
https://api.weather.gc.ca this session (see client.py's module
docstring for the full list of what was verified). Server identifies
itself as "pygeoapi 0.20.0" via the X-Powered-By response header.
"""

BASE_URL = "https://api.weather.gc.ca"

# ECCC's own usage page (https://eccc-msc.github.io/open-data/msc-geomet/
# readme_en/) states access is "anonymous and free of charge" with no
# published numeric rate limit, and no X-RateLimit-*/Retry-After header
# was present on any live response checked this session (collections
# list, collection detail, queryables, items). 10 req/s matches this
# project's shared conservative default used elsewhere for the same
# reason (see modules/boc/constants.py).
RATE_LIMIT_SOURCE = "eccc"
RATE_LIMIT_PER_SECOND = 10.0
RATE_LIMIT_CAPACITY = 10.0

# /collections?f=json is one ~100-entry, mostly-static inventory
# (confirmed live) - cached like boc's series/group lists.
CACHE_TTL_COLLECTIONS_SECONDS = 24 * 60 * 60  # 24h

# A single collection's own metadata (title/description/extent) and its
# queryables (property names/types) change rarely.
CACHE_TTL_COLLECTION_DETAIL_SECONDS = 24 * 60 * 60  # 24h

# Item queries range from a ~90-row collection (weather-alerts) to one
# confirmed live at 435,000+ rows (hydrometric-realtime) - too volatile
# and too large to cache broadly; a short TTL only smooths a caller
# re-running the exact same query moments apart.
CACHE_TTL_ITEMS_SECONDS = 5 * 60  # 5 min

# The server itself enforces no upper bound on `limit` (confirmed live:
# limit=100000 against an 88-row collection was honoured without error
# or truncation) - several collections here have hundreds of thousands
# of rows (see CACHE_TTL_ITEMS_SECONDS above), so this client enforces
# its own cap rather than trusting a caller-supplied limit to stay
# reasonable.
ITEMS_LIMIT_DEFAULT = 10
ITEMS_LIMIT_MAX = 1000

# /collections?f=json itself has no limit/offset - the full list is
# fetched once per CACHE_TTL_COLLECTIONS_SECONDS window and paginated
# client-side by eccc_search_collections/eccc_list_collections.
COLLECTIONS_SEARCH_LIMIT_DEFAULT = 25
