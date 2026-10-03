"""Ontario Energy Board open data (www.oeb.ca/ontarios-energy-sector/open-data).

Everything below was read from the live site on 2026-10-03.
"""

from __future__ import annotations

SOURCE = "oeb"
HOST = "www.oeb.ca"
ALLOWED_HOSTS = frozenset({"www.oeb.ca", "oeb.ca"})
BASE_URL = "https://www.oeb.ca"

# The English listing is the canonical catalogue: 43 dataset pages over three
# pages of 20 (?page=0..2). The French listing has the same pages under other
# slugs (plus a yearbook page with no English twin, which only links back to an
# HTML page), so French titles are matched through each English page's
# <link rel="alternate" hreflang="fr">.
LISTING_URL = f"{BASE_URL}/ontarios-energy-sector/open-data"
LISTING_URL_FR = f"{BASE_URL}/fr/secteur-de-lenergie-de-lontario/donnees-ouvertes"
DATASET_URL = f"{BASE_URL}/open-data/{{slug}}"
MAX_LISTING_PAGES = 10

LICENCE_URL = "https://www.ontario.ca/page/open-government-licence-ontario"
LICENCE_URL_FR = "https://www.ontario.ca/fr/page/licence-du-gouvernement-ouvert-ontario"
# The open data page links the Open Government Licence - Ontario as the terms
# for these files; the licence's own default attribution statement is quoted.
LICENCE = (
    "Source: Ontario Energy Board open data (https://www.oeb.ca/ontarios-energy-sector/"
    "open-data). Contains information licensed under the Open Government Licence – Ontario "
    f"({LICENCE_URL})."
)
LICENCE_FR = (
    "Source : données ouvertes de la Commission de l'énergie de l'Ontario "
    "(https://www.oeb.ca/fr/secteur-de-lenergie-de-lontario/donnees-ouvertes). Contient des "
    "renseignements utilisés en vertu de la Licence du gouvernement ouvert – Ontario "
    f"({LICENCE_URL_FR})."
)

# The 2021 edition of the Yearbook of Electricity Distributors, rebuilt from the
# RRR files and linked from the open data page itself (not from a dataset
# page). Exposed as one extra dataset with this slug.
YEARBOOK_SLUG = "yearbook-electricity-distributors-2021"
YEARBOOK_TITLE = "Yearbook of Electricity Distributors 2021 (open data edition)"
YEARBOOK_TITLE_FR = "Annuaire des distributeurs d'électricité 2021 (édition données ouvertes)"
YEARBOOK_DESCRIPTION = (
    "Files compiled from the individual open data files to mimic sections of the former "
    "Yearbook of Electricity Distributors (balance sheet, income statement, financial "
    "ratios, general and unitized statistics, statistics by customer class, service "
    "quality, system reliability), 2021 edition."
)
YEARBOOK_DESCRIPTION_FR = (
    "Fichiers compilés à partir des fichiers de données ouvertes pour reprendre les sections "
    "de l'ancien Annuaire des distributeurs d'électricité (bilan, état des résultats, ratios "
    "financiers, statistiques générales et unitaires, statistiques par catégorie de clients, "
    "qualité du service, fiabilité du réseau), édition 2021."
)

# Rate tables for oeb_rates. The current-rate XML files back the OEB bill
# calculator; their tags are explained by the "data keys" workbooks linked
# from the residential electricity and natural gas pages.
RATE_TABLES: dict[str, dict[str, str]] = {
    "electricity_residential": {
        "url": f"{BASE_URL}/_html/calculator/data/BillData.xml",
        "keys": f"{BASE_URL}/sites/default/files/data-keys-electricity-rates.xlsx",
        "page": "current-electricity-rates-residential-rate-class",
        "title": "Current electricity rates, residential rate class",
        "title_fr": "Tarifs d'électricité en vigueur, catégorie résidentielle",
    },
    "electricity_general_service": {
        "url": f"{BASE_URL}/_html/calculator/data/BillData_GS.xml",
        "keys": f"{BASE_URL}/sites/default/files/data-keys-electricity-rates.xlsx",
        "page": "current-electricity-rates-general-service-50-kw-rate-class",
        "title": "Current electricity rates, general service under 50 kW",
        "title_fr": "Tarifs d'électricité en vigueur, service général de moins de 50 kW",
    },
    "natural_gas_residential": {
        "url": f"{BASE_URL}/_html/calculator/data/GasBillData.xml",
        "keys": f"{BASE_URL}/sites/default/files/data-keys-naturalgas-rates.xlsx",
        "page": "current-natural-gas-rates-residential-rate-classes",
        "title": "Current natural gas rates, residential rate classes",
        "title_fr": "Tarifs du gaz naturel en vigueur, catégories résidentielles",
    },
    "rpp_time_of_use": {
        "url": f"{BASE_URL}/sites/default/files/historical-rpp-prices.xlsx",
        "sheet": "Time-of-Use",
        "page": "historical-regulated-price-plan-electricity-rates",
        "title": "Historical Regulated Price Plan prices, time-of-use",
        "title_fr": "Historique des prix de la grille tarifaire réglementée, prix selon l'heure",
    },
    "rpp_tiered": {
        "url": f"{BASE_URL}/sites/default/files/historical-rpp-prices.xlsx",
        "sheet": "Tiered",
        "page": "historical-regulated-price-plan-electricity-rates",
        "title": "Historical Regulated Price Plan prices, tiered",
        "title_fr": "Historique des prix de la grille tarifaire réglementée, prix par paliers",
    },
    "rpp_ultra_low_overnight": {
        "url": f"{BASE_URL}/sites/default/files/historical-rpp-prices.xlsx",
        "sheet": "Ultra-Low Overnight",
        "page": "historical-regulated-price-plan-electricity-rates",
        "title": "Historical Regulated Price Plan prices, ultra-low overnight",
        "title_fr": "Historique des prix de la grille tarifaire réglementée, très bas prix de nuit",
    },
}

# Two Drupal page types plus static files on one host; 4 requests a second
# keeps a cold catalogue build (3 listing pages + 43 dataset pages) near 12 s.
RATE_LIMIT_PER_SECOND = 4.0
RATE_LIMIT_CAPACITY = 4.0
PAGE_TIMEOUT_SECONDS = 30.0
FILE_TIMEOUT_SECONDS = 120.0

CATALOGUE_TTL_SECONDS = 6 * 3600
FILE_TTL_SECONDS = 2 * 3600

# The largest file is the 2015-2019 trial balance (Table 3, 61.9 MB, checked
# 2026-10-03); the next largest is 13.2 MB (a zip of map files, not read). The
# download is streamed under this cap, and the XML is parsed record by record
# (iterparse, each record dropped once read) rather than built into a tree.
MAX_FILE_BYTES = 80 * 1024 * 1024
MAX_XLSX_BYTES = 24 * 1024 * 1024

DEFAULT_MAX_ROWS = 100
MAX_ROWS = 1000
MAX_EXAMPLES = 3
MAX_LISTED_DISTRIBUTORS = 80
