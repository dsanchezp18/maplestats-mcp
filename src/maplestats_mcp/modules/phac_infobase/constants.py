"""Constants for PHAC's Health Infobase data files.

Confirmed live 2026-09-26 against health-infobase.canada.ca:
- Dashboards load plain CSV files from /src/data/<product>/... and a few
  older open-data snapshots from /open/...; files answer HTTP 200 with a
  Last-Modified header (IIS), which is the best "last updated" signal.
- A missing file answers HTTP 302 to /404.html (itself HTTP 200 HTML),
  not 404, so a redirect to that page means "no such file".
- Encodings vary file by file: UTF-8 with and without a BOM, Windows-1252
  (the French opioid ZIP, the 2018 CCDI, PASS and positive mental health
  snapshots, the enteric outbreak list), and one DOS code page 850 file
  (the French congenital anomalies snapshot, where "é" arrives as "‚"
  under Windows-1252).
- /api/<database>/table/<table> returns a whole table as a JSON array
  (documented on the site's API quick-start page). Only the small CNISP
  viral respiratory infection tables are read that way; the CYPC cancer
  tables are 140-230 MB and are not catalogued. The API's free-form SQL
  route is deliberately not used.
"""

BASE_URL = "https://health-infobase.canada.ca"
FRENCH_SITE = "https://sante-infobase.canada.ca"
API_URL = f"{BASE_URL}/api"
# health.canada.ca hosts the Canadian Notifiable Disease Surveillance System
# extract that the Notifiable Diseases Online charts are built from.
ALLOWED_HOSTS = frozenset({"health-infobase.canada.ca", "health.canada.ca"})
NOT_FOUND_PAGE = "/404.html"

RATE_LIMIT_SOURCE = "phac-infobase"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_FILE_SECONDS = 6 * 60 * 60
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_REDIRECTS = 3

ROWS_DEFAULT = 100
ROWS_MAX = 2000
SAMPLE_VALUES = 12
GEO_VALUES_MAX = 40

# Provinces and territories by PRUID, the code PHAC files use: (English,
# French, abbreviations). 63 "Territories" is the combined territories row
# in the opioid and stimulant harms file.
PROVINCES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "1": ("Canada", "Canada", ("CA", "CAN")),
    "10": ("Newfoundland and Labrador", "Terre-Neuve-et-Labrador", ("NL", "T.-N.-L.", "NFLD")),
    "11": ("Prince Edward Island", "Île-du-Prince-Édouard", ("PE", "PEI", "Î.-P.-É.")),
    "12": ("Nova Scotia", "Nouvelle-Écosse", ("NS", "N.-É.")),
    "13": ("New Brunswick", "Nouveau-Brunswick", ("NB", "N.-B.")),
    "24": ("Quebec", "Québec", ("QC", "QUE")),
    "35": ("Ontario", "Ontario", ("ON", "ONT")),
    "46": ("Manitoba", "Manitoba", ("MB", "MAN")),
    "47": ("Saskatchewan", "Saskatchewan", ("SK", "SASK")),
    "48": ("Alberta", "Alberta", ("AB", "ALTA")),
    "59": ("British Columbia", "Colombie-Britannique", ("BC", "C.-B.")),
    "60": ("Yukon", "Yukon", ("YT", "YK")),
    "61": ("Northwest Territories", "Territoires du Nord-Ouest", ("NT", "NWT", "T.N.-O.")),
    "62": ("Nunavut", "Nunavut", ("NU",)),
    "63": ("Territories", "Territoires", ()),
}

# Cell markers seen live in catalogued files, with their meaning.
MARKERS: dict[str, tuple[str, str]] = {
    "Suppr.": (
        "suppressed to protect privacy (small counts)",
        "supprimé pour protéger la confidentialité (petits nombres)",
    ),
    "X": ("suppressed (small counts)", "supprimé (petits nombres)"),
    "x": ("suppressed (small counts)", "supprimé (petits nombres)"),
    "n/a": ("not available or not applicable", "non disponible ou sans objet"),
    "N/A": ("not available or not applicable", "non disponible ou sans objet"),
    "n.d.": ("not available (French files)", "non disponible"),
    "na": ("not available", "non disponible"),
    "-": ("no value reported", "aucune valeur déclarée"),
    "..": ("not available for this reference period", "non disponible pour cette période"),
    "<5": ("fewer than 5, suppressed", "moins de 5, supprimé"),
    "<0.01": ("below 0.01, rounded", "moins de 0,01, arrondi"),
    "<0.1": ("below 0.1, rounded", "moins de 0,1, arrondi"),
    ">=99": ("99 or more, top-coded", "99 ou plus, valeur plafonnée"),
}

FREQUENCIES: dict[str, tuple[str, str]] = {
    "weekly": ("weekly", "hebdomadaire"),
    "monthly": ("monthly", "mensuelle"),
    "quarterly": ("quarterly", "trimestrielle"),
    "annual": ("annual", "annuelle"),
    "periodic": ("with each survey cycle or report", "à chaque cycle d'enquête ou rapport"),
    "archived": ("archived, no longer updated", "archivé, n'est plus mis à jour"),
}
