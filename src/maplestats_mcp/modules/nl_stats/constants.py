"""Constants for the Newfoundland and Labrador Statistics Agency module.

Fetched live on 2026-09-30. The agency's site (stats.gov.nl.ca, ASP.NET)
has no robots.txt (404). Its copyright statement (gov.nl.ca/disclaimer)
allows use by the public and non-government organizations. Each topic page
lists Excel and PDF links inside `#ContentPlaceHolder1_links`, grouped
under <h4> headings; the Excel files sit under /Statistics/Topics/.
"""

DOMAIN = "www.stats.gov.nl.ca"
SITE = f"https://{DOMAIN}"
TOPIC_PAGE_URL = SITE + "/Statistics/Statistics.aspx?Topic={topic}"
FILE_PATH_PREFIX = "/Statistics/Topics/"

# Topic slug -> (English title, French title). `census`, `environment` and
# `justice` publish no Excel files and are left out.
TOPICS: dict[str, tuple[str, str]] = {
    "charitabledonations": ("Charitable donations", "Dons de bienfaisance"),
    "cpi": ("Consumer price index", "Indice des prix à la consommation"),
    "education": ("Education", "Éducation"),
    "ei": ("Employment insurance", "Assurance-emploi"),
    "gdp": ("Gross domestic product", "Produit intérieur brut"),
    "health": ("Health", "Santé"),
    "income": ("Income", "Revenu"),
    "incomesupport": ("Income support", "Aide au revenu"),
    "industry": ("Industry", "Industrie"),
    "labour": ("Labour force", "Population active"),
    "minimumwage": ("Minimum wage", "Salaire minimum"),
    "personalfinance": ("Personal finance", "Finances personnelles"),
    "population": ("Population and demographics", "Population et démographie"),
    "trade": ("International trade", "Commerce international"),
    "transportation": ("Transportation", "Transports"),
}

RATE_LIMIT_SOURCE = "nl-stats"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 3.0

CACHE_TTL_PAGE_SECONDS = 6 * 60 * 60
CACHE_TTL_FILE_SECONDS = 6 * 60 * 60

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_ROWS_PER_SHEET = 20000
ROWS_LIMIT_DEFAULT = 50
ROWS_LIMIT_MAX = 500
FILES_LIMIT_MAX = 200
# All topics list about 160 files (43 KB of JSON, live 2026-10-03); a first
# call shows one compact page, and topic, query or offset reach the rest.
FILES_LIMIT_DEFAULT = 40

PROVENANCE_SOURCE = "nl-statistics-agency"
