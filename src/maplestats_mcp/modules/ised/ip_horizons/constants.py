"""Constants for CIPO's IP Horizons researcher datasets on open.canada.ca."""

CKAN_BASE_URL = "https://open.canada.ca/data/api/3/action/package_show"
DATASET_PAGE_URL = "https://open.canada.ca/data/en/dataset/{id}"
RATE_LIMIT_SOURCE = "ised-ip-horizons"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 3.0

# The catalogue changes a few times a year; the dictionaries even less.
CATALOGUE_TTL_SECONDS = 6 * 60 * 60
DICTIONARY_TTL_SECONDS = 24 * 60 * 60

# The three IP Horizons packages published by CIPO on open.canada.ca,
# confirmed live 2026-09-25 by searching for "IP Horizons".
PACKAGE_IDS = {
    "patent": "fe1dfbb9-0fc3-42ca-b2a9-6ca4c05dbac9",
    "industrial_design": "d92aacca-769f-4e8e-9d79-0bcf3078ff21",
    "trademark": "4bf74760-7ae7-4c83-ace8-b84a3b9aea8d",
}

# Only patents and industrial designs have a dictionary: the trademark
# URL following the same pattern answers an HTML 404 page (checked live
# 2026-09-25), and the trademark package lists none.
DICTIONARY_URLS = {
    "patent": "https://opic-cipo.ca/cipo/client_downloads/IP_Horizon_Resources/PT_Data_Dictionary.zip",
    "industrial_design": "https://opic-cipo.ca/cipo/client_downloads/IP_Horizon_Resources/ID_Data_Dictionary.zip",
}
MAX_DICTIONARY_BYTES = 5 * 1024 * 1024
