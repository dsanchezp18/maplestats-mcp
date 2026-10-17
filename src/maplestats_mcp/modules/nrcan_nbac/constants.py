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
# NBAC polygons are huge: five 2023 BC fires with geometry were 32.9 MB
# (live 2026-10-03). With geometry, at most this many rows are requested and
# the returned polygons stop at GEOMETRY_BYTES_MAX; a single polygon larger
# than that comes back without its geometry.
GEOMETRY_ROWS_MAX = 10
GEOMETRY_BYTES_MAX = 2_000_000
# The GeoJSON of a geometry request is read only up to this size: GeoServer
# streams it chunked, with no Content-Length (live 2026-10-17), so the cap is
# enforced while reading, and the polygons are trimmed to GEOMETRY_BYTES_MAX
# before the result is cached. Parsed, 20 MB is on the order of 100 MB of
# Python objects, which the hosted instance (512 MB) can hold once.
GEOMETRY_RESPONSE_BYTES_MAX = 20 * 1024 * 1024

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
