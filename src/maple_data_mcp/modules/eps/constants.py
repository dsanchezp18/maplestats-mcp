SOURCE = "eps"
SERVICES_ROOT = "https://services9.arcgis.com/pkzvt2xlZJnPgk1Z/arcgis/rest/services"
PORTAL_URL = "https://communitysafetydataportal.edmontonpolice.ca/"

# Dataset key -> hosted feature service; see the module docstring for
# the coverage confirmed live for each.
DATASETS = {
    "current": f"{SERVICES_ROOT}/EPS_OCC_30DAY/FeatureServer/0",
    "2023": f"{SERVICES_ROOT}/Historic_Occurrences_CSDP_2_view/FeatureServer/0",
}
DATASET_COVERAGE = {
    "current": "rolling ~12 months to the last refresh",
    "2023": "calendar year 2023 only",
}
LOAD_DATE_URL = f"{SERVICES_ROOT}/FME_Load_Date/FeatureServer/0"

# No published limit; Esri's hosted services are generous, but keep this
# in line with the project's other ArcGIS sources.
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_QUERY_SECONDS = 30 * 60
CACHE_TTL_LOAD_DATE_SECONDS = 60 * 60

# The layer's maxRecordCount is 2000 (confirmed live).
LIMIT_DEFAULT = 50
LIMIT_MAX = 2000

GROUP_BY_FIELDS = {
    "category": ["Occurrence_Category"],
    "group": ["Occurrence_Category", "Occurrence_Group"],
    "type": ["Occurrence_Category", "Occurrence_Group", "Occurrence_Type_Group"],
    "month": ["Reported_Year", "Reported_Month"],
    "intersection": ["Intersection"],
}
