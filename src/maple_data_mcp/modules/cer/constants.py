"""Constants for Canada Energy Regulator open data.

Confirmed live 2026-09-23:
- Files live at https://www.cer-rec.gc.ca/open/... (English) and
  .../ouvert/... (French); legacy www.neb-one.gc.ca links 301-redirect
  there.
- English files are UTF-8 with a BOM; French files are Windows-1252
  ("Année" arrives as "Ann\\xe9e" in UTF-8 decoding).
- A mistyped path answers HTTP 200 with the site's HTML page, not 404.
- Throughput files run from ~0.2 to a few MB each.
"""

CATALOGUE_ORG = "cer-rec"
ALLOWED_HOSTS = frozenset({"www.cer-rec.gc.ca", "www.neb-one.gc.ca"})

RATE_LIMIT_SOURCE = "cer"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_FILE_SECONDS = 6 * 60 * 60

ROWS_DEFAULT = 100
ROWS_MAX = 2000
DATE_COLUMNS = ("Date", "Year", "Année", "Annee")
