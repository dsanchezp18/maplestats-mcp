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
# The layer's field list and last-edit date (for date fields and as_of).
CACHE_TTL_LAYER_SECONDS = 6 * 60 * 60
# Two missed monthly refreshes before the provenance calls the layer stale.
STALE_AFTER_DAYS = 62

ROWS_LIMIT_DEFAULT = 10
# 1,000 full rows came to about 750 KB; 250 keeps a page under 200 KB.
ROWS_LIMIT_MAX = 250
