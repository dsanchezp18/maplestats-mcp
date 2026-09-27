"""Constants for the OpenParliament.ca API.

Confirmed live 2026-09-24: list endpoints accept `limit` up to 500 and
page through `pagination.next_url`; bilingual fields are `{"en", "fr"}`
dicts, some with only `en`; an unknown object answers 404 with an HTML
page, not JSON. The API asks clients to send `API-Version` and an
identifying User-Agent.
"""

BASE_URL = "https://api.openparliament.ca"
SITE_URL = "https://openparliament.ca"
HEADERS = {"Accept": "application/json", "API-Version": "v1"}

RATE_LIMIT_SOURCE = "openparliament"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_SECONDS = 15 * 60
ROSTER_TTL_SECONDS = 24 * 60 * 60

PAGE_SIZE = 500
MAX_ROWS = 5000
LIMIT_DEFAULT = 50
LIMIT_MAX = 500

# Committee rosters change a few times a session. Confirmed live
# 2026-09-26: /committees/ lists only top-level committees (subcommittees
# appear only in a committee's `subcommittees`), and committee data
# starts with session 39-1 (2006).
COMMITTEE_TTL_SECONDS = 24 * 60 * 60
RECENT_MEETINGS = 10
