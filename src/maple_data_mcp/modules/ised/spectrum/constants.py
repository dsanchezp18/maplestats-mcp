"""Constants for ISED's Spectrum Management System licence site data.

Confirmed live 2026-09-19: unlike this codebase's ArcGIS Hub modules,
this is a single, fixed, Esri-hosted FeatureServer with no Hub Search
catalogue in front of it -- there is exactly one dataset here, so no
search/discovery step is needed before querying it.
"""

DOMAIN = "services.arcgis.com"
SERVICE_URL = (
    "https://services.arcgis.com/wjcPoefzjpzCgffS/ArcGIS/rest/services/"
    "Spectrum_Licences_Site_Data/FeatureServer"
)
LAYER_INDEX = 0
RATE_LIMIT_SOURCE = "ised-spectrum"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_ROWS_SECONDS = 15 * 60

ROWS_LIMIT_DEFAULT = 10
ROWS_LIMIT_MAX = 1000
