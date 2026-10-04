"""Constants for the NRCan mineral production module (checked live 2026-10-03)."""

SITE = "https://mmsd.nrcan-rncan.gc.ca"
ANNUAL_PAGE = SITE + "/prod-prod/ann-ann-eng.aspx"
CSV_URL = SITE + "/PDF/MIS{year}TableG01-en.csv"

FIRST_YEAR = 1990

RATE_LIMIT_SOURCE = "nrcan_minerals"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

# The preliminary estimate comes out once a year; past years are revised rarely.
YEARS_TTL_SECONDS = 24 * 60 * 60
CSV_TTL_SECONDS = 24 * 60 * 60
# Each year's file was 170-245 KB.
MAX_FILE_BYTES = 8 * 1024 * 1024

ROWS_DEFAULT_LIMIT = 500
ROWS_MAX_LIMIT = 5000

PROVINCES: dict[str, str] = {
    "NL": "Newfoundland and Labrador",
    "PE": "Prince Edward Island",
    "NS": "Nova Scotia",
    "NB": "New Brunswick",
    "QC": "Quebec",
    "ON": "Ontario",
    "MB": "Manitoba",
    "SK": "Saskatchewan",
    "AB": "Alberta",
    "BC": "British Columbia",
    "YT": "Yukon",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
    "CA": "Canada",
}

TERMS = (
    "Natural Resources Canada terms on canada.ca: reproduction for non-commercial purposes "
    "with attribution; commercial reproduction needs written permission. Source: Natural "
    "Resources Canada (1990-2018) and Statistics Canada (2019 onward, collected under the "
    "Statistics Act)."
)
