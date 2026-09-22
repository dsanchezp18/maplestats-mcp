"""Constants for DataBC's public WFS 2.0 endpoint (BC Geographic Warehouse)."""

DOMAIN = "openmaps.gov.bc.ca"
BASE_URL = f"https://{DOMAIN}/geo/pub/wfs"
RATE_LIMIT_SOURCE = "bcgw"
# No published rate limit found; kept conservative like this project's
# other unpublished-limit legacy/government portals.
RATE_LIMIT_PER_SECOND = 5.0
RATE_LIMIT_CAPACITY = 10.0

DEFAULT_SRS = "EPSG:4326"

# Confirmed live 2026-09-22: this GeoServer instance answers HTTP 400
# ("Cannot do natural order without a primary key") for a request that
# genuinely pages (more rows match than the requested count) with no
# explicit sortBy -- reproduced against the mining tenure layer.
# OBJECTID is BCGW's standard ArcSDE row identifier and present on every
# layer checked, so it is the default sort field client-wide.
DEFAULT_SORT_FIELD = "OBJECTID"

ROWS_LIMIT_DEFAULT = 20
ROWS_LIMIT_MAX = 1000

# Current-fire status changes during a fire season; short TTL so a caller
# never gets a stale "Out of Control" fire that has since been contained.
CACHE_TTL_WILDFIRE_SECONDS = 5 * 60
# Mining tenure changes on the order of weeks (new claims, terminations),
# confirmed live via ISSUE_DATE/TERMINATION_DATE spacing on real records.
CACHE_TTL_MINING_TENURE_SECONDS = 24 * 60 * 60
# The generic layer tool can point at anything from a live-updated layer
# to a static one -- a short-ish default that favours freshness.
CACHE_TTL_GENERIC_SECONDS = 15 * 60

# Confirmed live 2026-09-22 via WFS DescribeFeatureType against
# WHSE_LAND_AND_NATURAL_RESOURCE.PROT_CURRENT_FIRE_POLYS_SP: this is the
# complete field list (minus geometry/OBJECTID/SE_ANNO_CAD_DATA) -- there
# is no fire-centre/region field on this particular layer.
WILDFIRE_TYPE_NAME = "WHSE_LAND_AND_NATURAL_RESOURCE.PROT_CURRENT_FIRE_POLYS_SP"
WILDFIRE_ATTRIBUTE_FIELDS = (
    "FIRE_NUMBER,FIRE_YEAR,FIRE_SIZE_HECTARES,SOURCE,TRACK_DATE,LOAD_DATE,FIRE_STATUS,FIRE_URL"
)

# Confirmed live 2026-09-22 against a real feature (a Teck Highland Valley
# Copper claim). TENURE_TYPE_CODE is 'M' (mineral) or 'P' (placer).
MINING_TENURE_TYPE_NAME = "WHSE_MINERAL_TENURE.MTA_ACQUIRED_TENURE_SVW"
MINING_TENURE_ATTRIBUTE_FIELDS = (
    "TENURE_NUMBER_ID,CLAIM_NAME,TENURE_TYPE_CODE,TENURE_TYPE_DESCRIPTION,"
    "TENURE_SUB_TYPE_DESCRIPTION,TITLE_TYPE_DESCRIPTION,ISSUE_DATE,GOOD_TO_DATE,"
    "AREA_IN_HECTARES,OWNER_NAME,PERCENT_OWNERSHIP,NUMBER_OF_OWNERS,"
    "STATEMENT_OF_WORK_EVENT_COUNT,TERMINATION_DATE"
)
