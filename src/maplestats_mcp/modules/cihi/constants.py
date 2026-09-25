"""Constants for CIHI's Indicator Library.

Confirmed live 2026-09-23:
- The library lists indicators 20 per page at
  /en/access-data-and-reports/indicator-library?page=N (10 pages, ~196
  indicators), each linking to /en/indicators/<slug>.
- Indicator pages carry `<link hreflang="fr">` to their French page and
  a link to `/sites/default/files/document/data-file/<id>-<slug>-data-
  table-{en,fr}.xlsx` (~2 MB). Workbooks have an "Instructions" sheet
  and one or more "Table N"/"Tableau N" sheets whose first row is the
  title and second row the header.
- The all-indicators XLSX (~98 MB, Excel's row limit) is not used.
"""

BASE_URL = "https://www.cihi.ca"
LIBRARY_URL = f"{BASE_URL}/en/access-data-and-reports/indicator-library"
INDICATOR_PATH = "/en/indicators/"
ALLOWED_HOSTS = frozenset({"www.cihi.ca"})

RATE_LIMIT_SOURCE = "cihi"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_LIBRARY_SECONDS = 7 * 24 * 60 * 60
CACHE_TTL_PAGE_SECONDS = 24 * 60 * 60
CACHE_TTL_DATA_SECONDS = 24 * 60 * 60

LIBRARY_MAX_PAGES = 30
MAX_FILE_BYTES = 30 * 1024 * 1024
ROWS_DEFAULT = 100
ROWS_MAX = 2000
