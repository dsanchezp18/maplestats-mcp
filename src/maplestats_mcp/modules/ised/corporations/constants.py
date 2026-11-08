"""Constants for Corporations Canada's federal corporation lookup API."""

DOMAIN = "ised-isde.canada.ca"
BASE_URL = f"https://{DOMAIN}/cc/lgcy/api/corporations"
RATE_LIMIT_SOURCE = "ised-corporations"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_SECONDS = 60 * 60

# cr_ecfrm.html answers 404 since 2026-11; this is the federal corporation search page.
LANDING_PAGE_URL = "https://ised-isde.canada.ca/cc/lgcy/fdrlCrpSrch.html"
