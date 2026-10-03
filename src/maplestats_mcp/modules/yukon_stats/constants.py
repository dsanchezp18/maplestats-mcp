"""Constants for the Yukon Bureau of Statistics module.

Fetched live on 2026-09-30 and 2026-10-03. The Bureau's tables are CSV
resources (176 on 2026-10-03) of ten datasets in the
`yukon-bureau-of-statistics` organization on open.yukon.ca (CKAN), all under
the Open Government Licence - Yukon 2.0. One `package_search` returns the ten
datasets with their resources (URL, format, size), so discovery is a single
API call. The host asks for 10 seconds between requests; discovery and file
downloads share one bucket paced at one request per 10 seconds.
"""

DOMAIN = "open.yukon.ca"
ORGANIZATION = "yukon-bureau-of-statistics"
API_URL = f"https://{DOMAIN}/api/3/action/"
DOWNLOAD_PATH_PREFIX = "/data/"

RATE_LIMIT_SOURCE = "yukon-stats"
RATE_LIMIT_PER_SECOND = 0.1
RATE_LIMIT_CAPACITY = 1.0
CATALOGUE_TIMEOUT_SECONDS = 60.0

CACHE_TTL_LIST_SECONDS = 6 * 60 * 60
CACHE_TTL_FILE_SECONDS = 6 * 60 * 60

# The population file is 53 MB because a long footnote repeats on every
# row; columns named here are dropped after parsing to keep rows small.
MAX_FILE_BYTES = 80 * 1024 * 1024
DROPPED_COLUMNS = ("footnotes",)
CELL_MAX_CHARS = 300

# 1,000 rows of a wide census table came to about 800 KB; 500 rows and a
# byte budget keep one page well under that.
ROWS_LIMIT_DEFAULT = 50
ROWS_LIMIT_MAX = 500
TABLES_LIMIT_DEFAULT = 50
TABLES_LIMIT_MAX = 200

PROVENANCE_SOURCE = "yukon-bureau-of-statistics"
LICENCE = {
    "en": "Open Government Licence - Yukon",
    "fr": "Licence du gouvernement ouvert - Yukon",
}
