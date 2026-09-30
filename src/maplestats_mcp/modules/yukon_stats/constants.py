"""Constants for the Yukon Bureau of Statistics module.

Fetched live on 2026-09-30. The Bureau's tables are CSV resources of ten
datasets in the `yukon-bureau-of-statistics` organization on open.yukon.ca
(CKAN), Open Government Licence - Yukon. The portal's robots.txt sets
`Crawl-Delay: 10` and disallows `/api/`; the CSV downloads under `/data/`
are not disallowed, and dataset discovery reuses the shipped `ckan_` client
for the `yt` portal.
"""

DOMAIN = "open.yukon.ca"
ORGANIZATION = "yukon-bureau-of-statistics"
PORTAL = "yt"
DOWNLOAD_PATH_PREFIX = "/data/"

# One request per 10 seconds, with room for a short burst.
RATE_LIMIT_SOURCE = "yukon-stats"
RATE_LIMIT_PER_SECOND = 0.1
RATE_LIMIT_CAPACITY = 2.0

CACHE_TTL_LIST_SECONDS = 6 * 60 * 60
CACHE_TTL_FILE_SECONDS = 6 * 60 * 60

# The population file is 53 MB because a long footnote repeats on every
# row; columns named here are dropped after parsing to keep rows small.
MAX_FILE_BYTES = 80 * 1024 * 1024
DROPPED_COLUMNS = ("footnotes",)
CELL_MAX_CHARS = 300

ROWS_LIMIT_DEFAULT = 50
ROWS_LIMIT_MAX = 1000
TABLES_LIMIT_MAX = 200

PROVENANCE_SOURCE = "yukon-bureau-of-statistics"
LICENCE = {
    "en": "Open Government Licence - Yukon",
    "fr": "Licence du gouvernement ouvert - Yukon",
}
