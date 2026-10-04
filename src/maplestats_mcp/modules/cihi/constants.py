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
# The French library has its own slugs (196 indicators either side, live
# 2026-10-03): /fr/indicateurs/mortalite-a-lhopital-dans-les-30-jours-
# accident-vasculaire-cerebral is the twin of
# /en/indicators/30-day-stroke-in-hospital-mortality.
FR_LIBRARY_URL = f"{BASE_URL}/fr/acceder-aux-donnees-et-aux-rapports/repertoire-des-indicateurs"
FR_INDICATOR_PATH = "/fr/indicateurs/"
# The site's sitemap index (two pages, ~1.6 MB) gives every page's English
# and French addresses as hreflang alternates, the same pair as each
# page's language switch; it pairs the two libraries in two requests
# instead of ~200 page reads.
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
SITEMAP_MAX_PAGES = 10
ALLOWED_HOSTS = frozenset({"www.cihi.ca"})

RATE_LIMIT_SOURCE = "cihi"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_LIBRARY_SECONDS = 7 * 24 * 60 * 60
CACHE_TTL_PAGE_SECONDS = 24 * 60 * 60
CACHE_TTL_DATA_SECONDS = 24 * 60 * 60
CACHE_TTL_PAIRING_SECONDS = 24 * 60 * 60

# Left out of a French query: "taux de réadmission à l'hôpital" must match
# "Réadmission à l'hôpital..." names whatever the articles.
FR_STOP_WORDS = frozenset(
    {"a", "au", "aux", "avec", "d", "dans", "de", "des", "du", "en", "et", "l", "la", "le"}
    | {"les", "ou", "par", "pour", "selon", "sur", "un", "une"}
)
LIBRARY_MAX_PAGES = 30
MAX_FILE_BYTES = 30 * 1024 * 1024
# 2,000 rows of a wide table came to 2.7 MB and 100 rows to 135 KB; the
# default is smaller and every response is also held to a byte budget.
ROWS_DEFAULT = 40
ROWS_MAX = 2000
