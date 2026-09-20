"""Constants for the Ontario Data Catalogue CKAN deployment."""

BASE_URL = "https://data.ontario.ca/api/3/action/"
RATE_LIMIT_SOURCE = "ckan-on"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 5.0

CACHE_TTL_SEARCH_SECONDS = 10 * 60
CACHE_TTL_PACKAGE_SECONDS = 60 * 60
CACHE_TTL_ORGANIZATION_LIST_SECONDS = 24 * 60 * 60
CACHE_TTL_ORGANIZATION_SECONDS = CACHE_TTL_ORGANIZATION_LIST_SECONDS
CACHE_TTL_RESOURCE_SECONDS = 60 * 60
CACHE_TTL_LICENSE_LIST_SECONDS = 7 * 24 * 60 * 60
CACHE_TTL_TAG_LIST_SECONDS = 60 * 60
CACHE_TTL_GROUP_LIST_SECONDS = 24 * 60 * 60

SEARCH_ROWS_DEFAULT = 10
SEARCH_ROWS_MAX = 100
NOTES_EXCERPT_LENGTH = 300
TAG_LIST_MAX = 200

DATASET_LANDING_URL = "https://data.ontario.ca/{lang}/dataset/"
ORGANIZATION_LANDING_URL = "https://data.ontario.ca/{lang}/organization/"
GROUP_LANDING_URL = "https://data.ontario.ca/{lang}/group/"


CACHE_TTL_DATASTORE_SECONDS = 15 * 60  # 15m: DataStore-backed data can update daily

# Mirrors ckan_federal/ckan_bc's DATASTORE_ROWS_MAX reasoning: kept far
# below whatever this deployment's own datastore_search ceiling is, for
# agent-facing compactness rather than exposing the raw server limit.
DATASTORE_ROWS_DEFAULT = 20
DATASTORE_ROWS_MAX = 1000
