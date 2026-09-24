"""Constants for the Earthquakes Canada FDSN event service.

Per the FDSN event standard: `format=text` answers a pipe-separated
table whose header is
#EventID|Time|Latitude|Longitude|Depth/km|Author|Catalog|Contributor|
ContributorID|MagType|Magnitude|MagAuthor|EventLocationName, and no
match is HTTP 204 (or 404 on servers that ignore `nodata`).
"""

BASE_URL = "https://earthquakescanada.nrcan.gc.ca/fdsnws/event/1/query"

RATE_LIMIT_SOURCE = "earthquakes-canada"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_SECONDS = 5 * 60

DAYS_DEFAULT = 30
MAX_SPAN_DAYS = 366 * 5
LIMIT_DEFAULT = 50
LIMIT_MAX = 1000
