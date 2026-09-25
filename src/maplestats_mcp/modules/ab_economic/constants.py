"""Constants for the Alberta Economic Dashboard data API.

Confirmed live 2026-09-23 against https://api.economicdata.alberta.ca:
- `api/chart-editor/data-tables` lists every table name (260).
- `api/chart-editor/field-info/{table}` lists each column with its SQL
  type and distinct values (dates as MM/DD/YYYY there, ISO in data).
- `api/chart-editor/indicator-info/{table}` gives a display name and
  period ("Monthly"); the JSON key is misspelled upstream: `indicaorName`.
- `data?table={table}&{Column}={value}` returns rows as JSON. Column
  names and values match case-insensitively. An unknown table or column
  answers HTTP 400 "Invalid object name" / "Invalid column name". An
  unfiltered table can be ~13 MB, so rows are trimmed client-side.
- `api/tile-data/dashboard/{code}` returns the Key Indicators page's
  catalogue (11 topics, 49 indicators, last-update times).
- Each indicator page has an "API Keys" section: the Government of
  Alberta's published `data?table=...&column=value` links for every
  chart on the page, each with a human-readable name. These are the
  supported entry points; the chart-editor routes above only help
  discover tables and filter values.
"""

BASE_URL = "https://api.economicdata.alberta.ca"
DASHBOARD_URL = "https://economicdashboard.alberta.ca/dashboard/"
KEY_INDICATORS_CODE = "c892fed7-6018-47b0-b437-d1a06d650d51"
INDICATOR_PAGE_URL = "https://economicdashboard.alberta.ca/dashboard/{slug}/"

# Indicator pages live at /dashboard/<slug>/, where the slug is the
# indicator name in kebab case for 45 of 49 key indicators (checked live
# 2026-09-23). Known exceptions are mapped here; an unknown page falls
# back to the kebab-case name.
SLUG_OVERRIDES = {
    "Investment (Annual) - Construction": "investment-annual",
}

RATE_LIMIT_SOURCE = "ab-economic"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_CATALOGUE_SECONDS = 24 * 60 * 60
CACHE_TTL_FIELDS_SECONDS = 6 * 60 * 60
CACHE_TTL_DATA_SECONDS = 60 * 60

ROWS_DEFAULT = 120
ROWS_MAX = 2000
FIELD_VALUES_MAX = 100
