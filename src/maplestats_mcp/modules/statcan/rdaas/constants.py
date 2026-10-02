"""Constants for the StatCan Reference Data as a Service (RDaaS) submodule.

Base URL and the 12 confirmed endpoints per the live OpenAPI 3.0 spec
fetched this session:
https://open.canada.ca/data/dataset/71fad0cb-bc36-4682-815f-0984e9d9a3bb/resource/c2750b5d-3eaa-49a8-81f0-1d242359cbd5/download/rdaas-spec-en-v1_2.json

Different host than WDS/SDMX (api.statcan.gc.ca, not
www150.statcan.gc.ca) — its own rate-limit bucket.
"""

BASE_URL = "https://api.statcan.gc.ca/rdaas"

RATE_LIMIT_SOURCE = "statcan-rdaas"
RATE_LIMIT_PER_SECOND = 10.0
RATE_LIMIT_CAPACITY = 10.0

# StatCan publishes classification/concordance updates infrequently.
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h

DEFAULT_SEARCH_LIMIT = 10
MAX_SEARCH_LIMIT = 500

# Index and detailed-category endpoints ignore start/limit (verified live
# 2026-10-02: NAICS 2022 indexes are 8.3 MB whatever is asked), so the full
# list is cached and paged here.
DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 1000
