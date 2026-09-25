"""Constants for the DFO/CHS Integrated Water Level System API.

Confirmed live 2026-09-23 against https://api-iwls.dfo-mpo.gc.ca/api/v1:
- `/stations` returns every station (~1,575) in one unpaginated array;
  `/stations?code=07120` filters to one five-digit CHS station code.
- `/stations/{id}/data` rejects windows longer than 7 days with HTTP 400
  "date interval should not be bigger than 7 days".
- `resolution` accepts ONE_MINUTE, FIVE_MINUTES, FIFTEEN_MINUTES and
  SIXTY_MINUTES (THIRTY_MINUTES is rejected). Sending any resolution with
  `wlp-hilo` silently returns `[]`, so it is never sent for that series.
- An unknown series for a station answers HTTP 404; a malformed id or
  date answers HTTP 400 with an `errors` list.
"""

BASE_URL = "https://api-iwls.dfo-mpo.gc.ca/api/v1"
RATE_LIMIT_SOURCE = "dfo-iwls"
RATE_LIMIT_PER_SECOND = 3.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_STATIONS_SECONDS = 24 * 60 * 60
CACHE_TTL_METADATA_SECONDS = 24 * 60 * 60
CACHE_TTL_DATA_SECONDS = 10 * 60

MAX_WINDOW_DAYS = 7
SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 200

# Series whose values are tide events, not a regular time grid.
EVENT_SERIES = frozenset({"wlp-hilo"})
