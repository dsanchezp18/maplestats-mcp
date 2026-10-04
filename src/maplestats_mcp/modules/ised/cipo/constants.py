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

# Nice classes the search UI's multiselect offers (0 = "Goods or services
# not classed"), checked live 2026-10-03.
NICE_CLASS_MIN = 0
NICE_CLASS_MAX = 45

# The search UI's "Current CIPO Status" multiselect (value -> label),
# read from the page on 2026-10-03. The API filters on these codes, sent as
# a list in `cipotextfield1`; they differ from the statusCode in results
# (a registered mark is filter code 19 but statusCode 12). Two labels
# repeat ("Approved" 4/17, "Advertised" 6/18), so a label selects every
# code that carries it.
CIPO_STATUS_CODES = {
    1: "Pre-formalized",
    2: "Formalized",
    3: "Default- Searched",
    4: "Approved",
    5: "Accepted for Publication",
    6: "Advertised",
    7: "Opposed",
    10: "Searched",
    13: "Refused - Awaiting Appeal",
    14: "Refused - Appeal in Progress",
    15: "Registration Pending",
    16: "Default - Registration Pending",
    17: "Approved",
    18: "Advertised",
    19: "Registered",
    20: "Granted",
    21: "Entered on the List",
    22: "Protected",
    23: "Abandoned Section 36",
    24: "Abandoned Section 40(3)",
    25: "Refused",
    26: "Expunged",
    27: "Cancelled by Owner",
    28: "Withdrawn",
    29: "Inactive - Partial Transfer",
    30: "Merged",
    31: "Abandoned",
    32: "Withdrawn by Owner",
    34: "Abandoned - Section 38(7)",
    35: "Surrendered",
    36: "Removed",
    37: "Cancelled",
    38: "Expunged Section 45(3)",
    39: "Refused in accordance with Trademarks Opposition Board decision",
    40: "Inactivated",
    44: "Revoked",
    45: "Deemed Never Filed",
}

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
