"""Constants for the CWFIS GeoServer's National Burned Area Composite (NBAC) layer."""

DOMAIN = "cwfis.cfs.nrcan.gc.ca"
BASE_URL = f"https://{DOMAIN}/geoserver/ows"
TYPE_NAME = "public:nbac"
RATE_LIMIT_SOURCE = "nrcan-nbac"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_QUERY_SECONDS = 24 * 60 * 60  # 24h: NBAC is compiled annually, not live-updated

ROWS_LIMIT_DEFAULT = 20
ROWS_LIMIT_MAX = 1000

# The full set of confirmed-live NBAC attribute fields, minus geometry --
# used as the default propertyName list when a caller doesn't request
# geometry, so a query stays lightweight by default (NBAC's polygons can
# be large; the full shapefile export is >1GB).
ATTRIBUTE_FIELDS = (
    "year,nfireid,basrc,firemaps,firemapm,firecaus,hs_sdate,hs_edate,"
    "ag_sdate,ag_edate,capdate,poly_ha,adj_ha,adj_flag,admin_area,"
    "natpark,prescribed,version"
)

DEFAULT_SRS = "EPSG:4326"
