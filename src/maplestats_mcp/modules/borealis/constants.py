"""Constants for Borealis' Dataverse search API."""

SEARCH_URL = "https://borealisdata.ca/api/search"
DATASET_URL = "https://borealisdata.ca/dataset.xhtml?persistentId={pid}"
FILE_URL = "https://borealisdata.ca/api/access/datafile/{file_id}"
FILES_URL = "https://borealisdata.ca/api/datasets/:persistentId/versions/:latest/files"
RATE_LIMIT_SOURCE = "borealis"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0
CACHE_TTL_SECONDS = 6 * 60 * 60

LIMIT_DEFAULT = 20
# The search API's per_page maximum is 1000; a larger page reset the
# connection when tried live 2026-09-25, and 100 answers promptly.
LIMIT_MAX = 100

# Datasets whose files are listed per search; each costs one request.
DATASETS_MAX = 10
DATA_EXTENSIONS = (".csv", ".xlsx", ".xls", ".txt", ".dat", ".sav", ".dta", ".zip")
