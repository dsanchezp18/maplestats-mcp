"""Constants for the StatCan SDMX REST submodule.

Confirmed live this session: StatCan's SDMX REST API
(www150.statcan.gc.ca/t1/wds/sdmx/statcan/rest/) returns SDMX-ML
(Generic Data / SDMX 2.1 XML) for both structure and data queries — the
`format=jsondata`/`sdmx-json` query parameter has no effect, and no
Accept header produced a JSON response. This contradicts a passing
assumption in some benchmark documentation of a "SDMX-JSON" response;
the client in this module parses the real XML format directly rather
than a JSON shape that could not be reproduced against the live API.
Same host as WDS, so it shares WDS's rate limiter bucket.
"""

BASE_URL = "https://www150.statcan.gc.ca/t1/wds/sdmx/statcan/rest/"

RATE_LIMIT_SOURCE = "statcan-wds"  # same host as WDS (www150.statcan.gc.ca)
RATE_LIMIT_PER_SECOND = 20.0
RATE_LIMIT_CAPACITY = 20.0

# Per-series cap on observations returned (the newest are kept).
MAX_ROWS = 500
# Observations per series when the caller gives no period filter at all. Before
# this default, an unfiltered key returned the OLDEST 500 observations (1914-01
# to 1955-08 for CPI), the opposite of what a caller wants.
DEFAULT_LAST_N = 100
# Cap on series per response (a wildcarded key can match thousands).
MAX_SERIES = 200

# Structure browsing: codes per dimension in one response. Table 98100002's
# full structure is 3.5 MB of XML (466k characters of JSON).
DEFAULT_CODE_LIMIT = 100
MAX_CODE_LIMIT = 1000

# Cached parsed structures and per-table dimension counts (they change only
# when StatCan revises a table's classification).
CACHE_TTL_STRUCTURE_SECONDS = 24 * 60 * 60

# SDMX time-period syntax accepted by StatCan: 2026, 2026-03, 2026-03-15,
# 2026-Q1, 2026-S1, 2026-W12 (the live API answers 406 "Wrong date format or
# value" for anything else, e.g. 2026/03).
PERIOD_PATTERN = r"^\d{4}(-(\d{2}(-\d{2})?|[QSW]\d{1,2}))?$"

SDMX_NS = {
    "mes": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
    "str": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    "com": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
    "message": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
    "generic": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic",
    "common": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
}
