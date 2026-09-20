"""Constants for the Canadian Trademarks Database (CIPO) search API."""

DOMAIN = "ised-isde.canada.ca"
BASE_URL = f"https://{DOMAIN}/cipo/trademark-search/srch"
RATE_LIMIT_SOURCE = "ised-cipo"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 3.0

CACHE_TTL_SECONDS = 60 * 60

MAX_RETURN_DEFAULT = 20
MAX_RETURN_MAX = 500

MEDIA_BASE_URL = "https://ised-isde.canada.ca/cipo/trademark-search"
LANDING_PAGE_URL = "https://ised-isde.canada.ca/cipo/trademark-search/srch"

# Confirmed live 2026-09-20 from the search UI's "Select a search field"
# dropdown -- these are the only searchfield1 values the API accepts.
# Any other value returns HTTP 500 (confirmed: a real portal-side
# behavior, not documented anywhere).
SEARCH_FIELD_TO_API = {
    "all": "all",
    "trademark": "tm",
    "trademark_description": "tmdesc",
    "owner_name": "ownname",
    "old_owner_name": "ip_relat",
    "goods": "wares",
    "services": "services",
    "application_number": "appnum",
    "original_application_number": "initialAppNum",
    "registration_number": "regnum",
    "international_registration_number": "intrnlRegNum",
    "nice_classification": "nice_for_search",
    "cipo_status": "cipo_status",
    "disclaimer": "disclaimer",
    "vienna_code": "viennaCode",
    "vienna_description": "viennaDesc",
}
