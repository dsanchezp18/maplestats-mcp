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

MAX_ROWS = 500

SDMX_NS = {
    "mes": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
    "str": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    "com": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
    "message": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
    "generic": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic",
    "common": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
}
