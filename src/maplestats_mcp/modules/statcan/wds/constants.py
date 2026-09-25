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

# StatCan's documented daily lock window: no reliable data 12am-8:30am ET.
LOCK_WINDOW_START_HOUR_ET = 0
LOCK_WINDOW_END_HOUR_ET = 8.5
