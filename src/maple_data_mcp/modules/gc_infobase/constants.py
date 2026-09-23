"""Constants for the GC InfoBase open datasets.

Confirmed live 2026-09-23:
- Package a35cf382-690c-4221-a971-cf0fd189a46f on open.canada.ca holds
  every GC InfoBase file (52 resources; 35 tagged English).
- Files are UTF-8 with a BOM, 1-3 MB each. Fiscal-year columns use
  several spellings in different files ("2011-12", "2020-2021",
  "FY 2011-12"), so fiscal years are matched on their start year.
- Organization columns are named `org_name`, `organization`, or
  `org_nom`/`organisation` in French files.
"""

PACKAGE_ID = "a35cf382-690c-4221-a971-cf0fd189a46f"
ALLOWED_HOSTS = frozenset({"open.canada.ca", "www.tbs-sct.canada.ca", "cdn-rdc.ea-ad.ca"})

RATE_LIMIT_SOURCE = "gc-infobase"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_FILE_SECONDS = 24 * 60 * 60

ROWS_DEFAULT = 100
ROWS_MAX = 2000
FISCAL_YEAR_COLUMNS = ("fy_ef", "fiscal_year", "exercice", "year")
ORGANIZATION_COLUMNS = (
    "org_name",
    "organization",
    "organization_name",
    "org_nom",
    "organisation",
    "nom_organisation",
)
