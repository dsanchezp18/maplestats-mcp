"""Constants for the StatCan Web Data Service (WDS) submodule.

Base URL, rate limit, and cache TTLs per the official user guide
(https://www.statcan.gc.ca/en/developers/wds/user-guide) and the
benchmark audit in docs/statcan-api-standard.md.
"""

BASE_URL = "https://www150.statcan.gc.ca/t1/wds/rest/"

# StatCan documents 25 req/s per IP; stay conservatively below it.
RATE_LIMIT_SOURCE = "statcan-wds"
RATE_LIMIT_PER_SECOND = 20.0
RATE_LIMIT_CAPACITY = 20.0

CACHE_TTL_CUBES_LIST_SECONDS = 60 * 60  # 1h
CACHE_TTL_CUBE_METADATA_SECONDS = 24 * 60 * 60  # 24h
CACHE_TTL_CODE_SETS_SECONDS = 7 * 24 * 60 * 60  # 7d
CACHE_TTL_OBSERVATIONS_SECONDS = 60 * 60  # 1h

# WDS coordinates are always exactly this many dot-separated dimensions.
COORDINATE_DIMENSIONS = 10

# Response caps. Uncapped, wds_search_cubes with no query was 4.4 MB, one census
# table's metadata 1.25 MB and getCodeSets 309 kB (checked 2026-10-02).
SEARCH_LIMIT_DEFAULT = 25
SEARCH_LIMIT_MAX = 500
MEMBER_LIMIT_DEFAULT = 100
MEMBER_LIMIT_MAX = 2000
# wds_get_leaf_members: 18-10-0004's 249 CPI leaves and 36-10-0434's 188 NAICS
# leaves fit in one page; a census geography does not.
LEAF_LIMIT_DEFAULT = 500
FOOTNOTE_LIMIT_DEFAULT = 25
CODE_SET_LIMIT_DEFAULT = 100

# wds_query_series: the server runs one read-only SQL query over the fetched
# observations and returns only its result. The vector cap keeps it a "handful
# of series" tool (whole tables go to wds_get_full_table_download); 3,000
# periods reaches back to 1914 for a monthly series (the CPI has 1,353).
QUERY_MAX_VECTORS = 20
QUERY_MAX_LATEST_N = 3000
QUERY_ROW_CAP = 500
QUERY_MAX_SQL_CHARS = 10_000
QUERY_MAX_SECONDS = 20.0

# The cube list is about 5 MB. Probed 2026-09-27 from GitHub runners: usually
# under a second, but one runner took 31-70 s on every try, past the shared
# 30 s default.
CUBES_LIST_TIMEOUT_SECONDS = 120.0
