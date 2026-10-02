"""Constants for the Open North Represent API.

Confirmed live 2026-10-02:
- Free up to 60 requests per minute (86,400 a day), per /api/; above that
  the server answers HTTP 503. The shared limiter paces calls to 1 a second.
- List endpoints return `{"objects": [...], "meta": {...}}`; `limit` is
  capped at 1000 (a larger value is clamped, not rejected).
- Only the detail endpoint of a boundary set carries `licence_url` and
  `last_updated`; the list endpoint has name, domain and urls only.
- Representative sets carry no update date and no licence at all.
- Paths need the trailing slash (without it the server answers 301).
- An unknown postcode or boundary set answers 404 with an HTML page; a bad
  `point` answers 400 with plain text; an unknown representative set slug
  answers 200 with an empty list.
- `Accept-Language` changes nothing in the JSON (labels stay English), so
  `lang` only chooses the language of this server's own notes.
"""

BASE_URL = "https://represent.opennorth.ca"
SITE_URL = "https://represent.opennorth.ca/api/"
HEADERS = {"Accept": "application/json"}

RATE_LIMIT_SOURCE = "represent"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 3.0
RATE_LIMIT_PER_MINUTE = 60

# Representatives change at elections and by-elections; boundary sets and
# set lists change a few times a year.
CACHE_TTL_SECONDS = 60 * 60
SETS_TTL_SECONDS = 24 * 60 * 60

PAGE_SIZE = 1000
LIMIT_DEFAULT = 20
LIMIT_MAX = 100
# 3,810 representatives at 2026-10-02, so a full scan is four pages.
MAX_SCAN_PAGES = 8
# Distinct boundary sets one lookup will fetch details for (a postcode
# matches up to about 13); each detail call costs one request of the budget.
MAX_SET_DETAILS = 25

FEDERAL_SET = "house-of-commons"
# Provincial legislatures are the sets whose slug ends in "-legislature",
# plus Quebec's Assemblée nationale (confirmed against all 121 sets).
PROVINCIAL_SUFFIX = "-legislature"
PROVINCIAL_EXTRA = frozenset({"quebec-assemblee-nationale"})

STALE_YEARS = 5.0
