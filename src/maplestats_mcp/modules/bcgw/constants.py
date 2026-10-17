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
# bcgw_query_layer with geometry: a polygon layer can hold megabytes per
# feature, and 1000 rows of it would be returned to the model and cached.
# With geometry at most this many rows are requested per call, the polygons
# returned stop at GEOMETRY_BYTES_MAX (later ones come back without their
# geometry, with a note), and the GeoJSON is read only up to
# GEOMETRY_RESPONSE_BYTES_MAX (GeoServer streams it chunked with no
# Content-Length, so the cap is enforced while reading). Parsed, 20 MB is on
# the order of 100 MB of Python objects, which the hosted instance (512 MB)
# can hold once. The same limits the NBAC module applies to its polygons.
GEOMETRY_ROWS_MAX = 25
GEOMETRY_BYTES_MAX = 2_000_000
GEOMETRY_RESPONSE_BYTES_MAX = 20 * 1024 * 1024

# Current-fire status changes during a fire season; short TTL so a caller
# never gets a stale "Out of Control" fire that has since been contained.
CACHE_TTL_WILDFIRE_SECONDS = 5 * 60
# Mining tenure changes on the order of weeks (new claims, terminations),
# confirmed live via ISSUE_DATE/TERMINATION_DATE spacing on real records.
CACHE_TTL_MINING_TENURE_SECONDS = 24 * 60 * 60
# The generic layer tool can point at anything from a live-updated layer
# to a static one -- a short-ish default that favours freshness.
CACHE_TTL_GENERIC_SECONDS = 15 * 60
# A layer's field list (DescribeFeatureType) changes only with a schema release.
CACHE_TTL_DESCRIBE_SECONDS = 24 * 60 * 60

# Confirmed live 2026-09-22 via WFS DescribeFeatureType against
# WHSE_LAND_AND_NATURAL_RESOURCE.PROT_CURRENT_FIRE_POLYS_SP: this is the
# complete field list (minus geometry/OBJECTID/SE_ANNO_CAD_DATA) -- there
# is no fire-centre/region field on this particular layer.
WILDFIRE_TYPE_NAME = "WHSE_LAND_AND_NATURAL_RESOURCE.PROT_CURRENT_FIRE_POLYS_SP"
WILDFIRE_ATTRIBUTE_FIELDS = (
    "FIRE_NUMBER,FIRE_YEAR,FIRE_SIZE_HECTARES,SOURCE,TRACK_DATE,LOAD_DATE,FIRE_STATUS,FIRE_URL"
)
# Extinguished fires; left out of the wildfire tool unless asked for.
WILDFIRE_OUT_STATUS = "Out"
# Largest fires first; OBJECTID breaks ties so pages stay stable (a
# two-key sortBy was accepted live 2026-10-03).
WILDFIRE_SORT = "FIRE_SIZE_HECTARES D,OBJECTID A"

# Confirmed live 2026-09-22 against a real feature (a Teck Highland Valley
# Copper claim). TENURE_TYPE_CODE is 'M' (mineral) or 'P' (placer).
MINING_TENURE_TYPE_NAME = "WHSE_MINERAL_TENURE.MTA_ACQUIRED_TENURE_SVW"
MINING_TENURE_ATTRIBUTE_FIELDS = (
    "TENURE_NUMBER_ID,CLAIM_NAME,TENURE_TYPE_CODE,TENURE_TYPE_DESCRIPTION,"
    "TENURE_SUB_TYPE_DESCRIPTION,TITLE_TYPE_DESCRIPTION,ISSUE_DATE,GOOD_TO_DATE,"
    "AREA_IN_HECTARES,OWNER_NAME,PERCENT_OWNERSHIP,NUMBER_OF_OWNERS,"
    "STATEMENT_OF_WORK_EVENT_COUNT,TERMINATION_DATE"
)
