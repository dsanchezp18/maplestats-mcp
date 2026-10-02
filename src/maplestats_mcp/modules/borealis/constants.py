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

# ODESI: the Ontario/Canadian social-science data portal's collection on
# Borealis (dataverse alias "odesi"), described in DDI. Checked live
# 2026-10-02: 5,350 datasets under it. `subtree=` takes several aliases.
# The public collections held only public files in a 40-dataset sample each
# (pumfs 3,401 datasets, polls 561, aggregate 546, census 284, other 26,
# international 80); the DLI collection (alias "dli", 414 datasets) is
# DLI-licensed: 37 of the 40 sampled datasets had every file restricted and
# the other 3 had a restricted data file beside a public PDF, so this module
# searches around it instead of listing it.
ODESI_COLLECTIONS = {
    "pumfs": ["pumfs"],
    "polls": ["pop"],
    "aggregate": ["aggregate"],
    "census": ["census"],
    "other": ["other"],
    "international": ["international"],
}
ODESI_PUBLIC_ALIASES = ["pumfs", "pop", "aggregate", "census", "other", "international"]
DDI_EXPORT_URL = "https://borealisdata.ca/api/datasets/export"
DDI_NAMESPACE = {"d": "ddi:codebook:2_5"}
DESCRIPTION_CHARS = 600
VARIABLES_LIMIT_DEFAULT = 30
VARIABLES_LIMIT_MAX = 200
