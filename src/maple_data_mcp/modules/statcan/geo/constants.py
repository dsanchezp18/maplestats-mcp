"""Constants for StatCan's geo.statcan.gc.ca ArcGIS REST census-geography service.

Confirmed live 2026-09-21. Distinct from every other StatCan module in
this codebase: it is the first genuinely queryable (attribute + spatial
filter) geography service found, as opposed to a static bulk shapefile
download (see `census_profile_archive`/the "Data" catalogue's PUMF
work) or a codelist (RDaaS's Standard Geographical Classification).

Live-confirmed structure: top-level folders are years (2019-2025
confirmed; nothing older is served here -- earlier census geography
stays a bulk-download-only concern). A census year (2021 confirmed)
publishes a full suite of ~10 services (Cartographic boundary files,
Digital boundary files, Agricultural/Population ecumene boundary
files, Road Network File, each in English and French), each service a
MapServer with one layer per geography level (PR/CD/CSD/CMA/ER/FED/
CCS/PC/DPL/ADA/CT/DA/DB/FSA/CAR, 15 layers confirmed for 2021's
Cartographic boundary files). An intercensal year publishes a much
smaller set (CSD-level boundary updates and the Road Network File
only, 4 services confirmed for 2022-2025, 2019-2020 also missing the
road network pair) -- this genuinely varies year to year, so no fixed
layer table is hardcoded; services and layers are discovered live.

Native spatial reference is EPSG:3347 (Statistics Canada Lambert), not
lat/lon -- pass out_sr=4326 (this client's default when geometry is
requested) to get standard WGS84 coordinates.
"""

BASE_URL = "https://geo.statcan.gc.ca/geo_wa/rest/services"

RATE_LIMIT_SOURCE = "statcan-geo"
RATE_LIMIT_PER_SECOND = 5.0
RATE_LIMIT_CAPACITY = 5.0

# Boundary files are revised infrequently (annually at most).
CACHE_TTL_SERVICES_SECONDS = 24 * 60 * 60  # 24h
CACHE_TTL_LAYER_DETAIL_SECONDS = 24 * 60 * 60  # 24h

DEFAULT_OUT_SR = 4326

QUERY_RECORD_COUNT_DEFAULT = 100
QUERY_RECORD_COUNT_MAX = 2000
