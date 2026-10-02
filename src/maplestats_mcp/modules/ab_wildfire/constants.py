"""Constants for the Alberta Wildfire status module. See the package docstring
for what was confirmed live about each layer."""

SOURCE = "ab_wildfire"
DOMAIN = "services.arcgis.com"
SERVICES_ROOT = "https://services.arcgis.com/Eb8P5h4CJk8utIBz/arcgis/rest/services"
MAP_URL = "https://experience.arcgis.com/experience/0e45bd0ef9814d5e9ec3f87900a4cfe9"
LICENCE_URL = "https://open.alberta.ca/licence"
ATTRIBUTION = (
    "Contains information licensed under the Open Government Licence - Alberta "
    "(Alberta Wildfire, Government of Alberta)."
)

# Layer id is part of the URL; (PROD) services are the ones with data (see the
# package docstring, point 7).
FIRES_CURRENT = f"{SERVICES_ROOT}/Wildfire_year_to_date/FeatureServer/0"
FIRES_HISTORY = f"{SERVICES_ROOT}/wildfire_prev5_ytd/FeatureServer/1"
PERIMETERS = {
    "active": f"{SERVICES_ROOT}/Wildfire_Perimeter_Active_(PROD)/FeatureServer/3",
    "extinguished": f"{SERVICES_ROOT}/Wildfire_Perimeter_Extinguished_(PROD)/FeatureServer/3",
}
DANGER = f"{SERVICES_ROOT}/fire_danger_rating/FeatureServer/0"
STATISTICS = f"{SERVICES_ROOT}/Wildfire_Statistics_Prod_View/FeatureServer/0"
THIS_DAY = f"{SERVICES_ROOT}/5_year_summary_on_this_day_prod_view/FeatureServer/2"
FIRE_CONTROL_ORDERS = {
    "Forest Area Closure": f"{SERVICES_ROOT}/alberta_fire_ban_system/FeatureServer/4",
    "Fire Ban": f"{SERVICES_ROOT}/alberta_fire_ban_system/FeatureServer/3",
    "Fire Restriction": f"{SERVICES_ROOT}/alberta_fire_ban_system/FeatureServer/2",
    "Fire Advisory": f"{SERVICES_ROOT}/alberta_fire_ban_system/FeatureServer/1",
}
OHV_RESTRICTION = f"{SERVICES_ROOT}/off_highway_vehicle_ohv_restriction/FeatureServer/0"
OHV_LABEL = "OHV Restriction"

# No published limit; keep in line with the project's other ArcGIS sources.
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 5.0

# Fire points change several times a day in season.
CACHE_TTL_FIRES = 10 * 60
CACHE_TTL_SLOW = 30 * 60
CACHE_TTL_LAYER_INFO = 10 * 60

# maxRecordCount of every layer used is 2000 (confirmed live).
LIMIT_DEFAULT = 20
LIMIT_MAX = 2000
LIMIT_GEOMETRY_MAX = 100
MAX_RADIUS_KM = 300.0

# Statuses that mean the fire is no longer being worked ("Assisstance" is the
# upstream misspelling found in the previous-five-years layer).
INACTIVE_STATUSES = ("Extinguished", "Turned Over", "Assistance Ended", "Assisstance Ended")
STATUS_SPELLING_FIX = {"Assisstance Ended": "Assistance Ended"}

FIRE_TYPES = ("Wildfire", "Mutual Aid")
SIZE_CLASSES = ("A", "B", "C", "D", "E")
SIZE_CLASS_MEANING = "A up to 0.1 ha, B to 4 ha, C to 40 ha, D to 200 ha, E over 200 ha"

# group_by keyword -> upstream field
FIRE_GROUP_FIELDS = {
    "status": "FIRE_STATUS",
    "cause": "GENERAL_CAUSE",
    "size_class": "SIZE_CLASS",
    "forest_area": "RESP_AREA",
    "fire_type": "FIRE_TYPE",
    "fire_year": "FIRE_YEAR",
}

DANGER_CLASSES = ("Low", "Moderate", "High", "Very High", "Extreme")
# Meanings from the fire danger item description on ArcGIS Online.
DANGER_MEANING = {
    "Low": "Fire can still ignite but is not expected to spread to deeper vegetation layers or larger fuels.",
    "Moderate": "Creeping or gentle surface fire is likely.",
    "High": "Forest fuels are dry and fire risk is serious; moderate to vigorous surface fire is expected.",
    "Very High": "High-intensity fire is expected and likely to spread to treetops.",
    "Extreme": "Forest fuels are extremely dry; fast-spreading, high-intensity fires are likely.",
}

# Most severe first.
ALERT_SEVERITY = {
    "Forest Area Closure": 0,
    "Fire Ban": 1,
    "Fire Restriction": 2,
    "Fire Advisory": 3,
    OHV_LABEL: 4,
}
