"""Constants for the PMRA pesticide registry module (checked live 2026-10-03)."""

EXTRACT_URL = "https://pest-control.canada.ca/pesticide-registry-api/api/extract/"
DATASET_URL = "https://open.canada.ca/data/{lang}/dataset/e10b0d6e-04ac-4014-a64a-666c3874bbe0"

RATE_LIMIT_SOURCE = "pmra"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0

# The database is refreshed once a night (2:30-3:30 a.m. Eastern, per the API guide).
EXTRACT_TTL_SECONDS = 6 * 60 * 60
PRODUCT_TTL_SECONDS = 60 * 60
# The largest extract, application, was 16 MB; product was 11-12 MB.
MAX_EXTRACT_BYTES = 40 * 1024 * 1024

SEARCH_DEFAULT_LIMIT = 50
SEARCH_MAX_LIMIT = 500
MRL_DEFAULT_LIMIT = 200
MRL_MAX_LIMIT = 2000

# Sites of use and pests are cut at 2,000 characters in the extracts.
TRUNCATED_AT = 2000

# Column counts of each extract, the same in English and French (only the
# header text differs), checked against the header row on every read.
PRODUCT_COLUMNS = 16
INGREDIENT_COLUMNS = 4
MRL_COLUMNS = 5

LICENCE = (
    "Contains information licensed under the Open Government Licence - Canada "
    "(https://open.canada.ca/en/open-government-licence-canada). Source: Health Canada, "
    "Pest Management Regulatory Agency."
)
