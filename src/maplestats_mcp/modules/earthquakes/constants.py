"""Constants for the Earthquakes Canada FDSN event service.

Confirmed live 2026-09-24: the host is www.earthquakescanada (the bare
host 301-redirects); `format=text` answers a pipe-separated table with
header #EventID|Time|Latitude|Longitude|Depth/km|MagType|Magnitude|
EventLocationName, whose location is "English/French" in one field; no
match is HTTP 204; bad parameters are HTTP 422 with a JSON `errors`
list. Event IDs come back as YYYYMMDD.HHmmNNN but `eventid=` accepts
only YYYYMMDD.HHmm.
"""

BASE_URL = "https://www.earthquakescanada.nrcan.gc.ca/fdsnws/event/1/query"

RATE_LIMIT_SOURCE = "earthquakes-canada"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_SECONDS = 5 * 60

DAYS_DEFAULT = 30
MAX_SPAN_DAYS = 366 * 5
LIMIT_DEFAULT = 50
LIMIT_MAX = 1000
