"""Constants for the DriveBC Open511 module. See the package docstring for
what was confirmed live."""

SOURCE = "drivebc"
BASE_URL = "https://api.open511.gov.bc.ca"
EVENTS_URL = f"{BASE_URL}/events"
AREAS_URL = f"{BASE_URL}/areas"
HELP_URL = f"{BASE_URL}/help"
CATALOGUE_URL = "https://catalogue.data.gov.bc.ca/dataset/open511-drivebc-api"
LICENCE = (
    "Contains information licensed under the Open Government Licence - British Columbia "
    "(https://www2.gov.bc.ca/gov/content?id=A519A56BC2BF44E4A008B33FCF527F61). Source: "
    "DriveBC, BC Ministry of Transportation and Transit, Open511 API (BC Government API "
    "Terms of Use)."
)

# Measured 2026-10-03: requests 2-3 s apart alternated 200 and 429.
RATE_LIMIT_PER_SECOND = 0.2
RATE_LIMIT_CAPACITY = 1.0

# Documented page maximum.
PAGE_SIZE = 500
MAX_PAGES = 10

# Events change by the minute; districts are static.
CACHE_TTL_EVENTS = 3 * 60
CACHE_TTL_AREAS = 24 * 60 * 60

LIMIT_DEFAULT = 25
LIMIT_MAX = 500

EVENT_TYPES = ("CONSTRUCTION", "INCIDENT", "ROAD_CONDITION", "WEATHER_CONDITION", "SPECIAL_EVENT")
SEVERITIES = ("MINOR", "MODERATE", "MAJOR", "UNKNOWN")
GROUP_FIELDS = ("event_type", "severity", "area", "road", "subtype")
