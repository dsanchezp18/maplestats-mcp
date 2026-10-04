SOURCE = "electricity"
BASE_URL = "https://reports-public.ieso.ca/public"

# IESO reports use Eastern Standard Time all year round: hour-ending 1..24, with
# 24 rows on both daylight-saving change days (confirmed live 2026-09-29 in
# PUB_Demand.csv for 2026-03-08 and PUB_Demand_2025.csv for 2025-11-02).
IESO_UTC_OFFSET_HOURS = -5

RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

CACHE_TTL_LATEST_SECONDS = 5 * 60
CACHE_TTL_HOURLY_SECONDS = 30 * 60
CACHE_TTL_ARCHIVE_SECONDS = 6 * 60 * 60

FIRST_DEMAND_YEAR = 2002
FIRST_FUEL_YEAR = 2015
DEFAULT_LIMIT = 48
MAX_LIMIT = 2000

# Fuel column of the hourly output report -> snake_case key.
CONTROL_ACTIONS_FUEL = "control_actions"

# Hydro-Quebec open data (Opendatasoft, keyless). Terms: licence CC BY-NC 4.0
# on every dataset used (catalogue `metas.default.license`, read 2026-09-29).
QUEBEC_SOURCE = "electricity"
QUEBEC_DATASETS_URL = "https://donnees.hydroquebec.com/api/explore/v2.1/catalog/datasets"
QUEBEC_LICENCE = (
    "Hydro-Quebec open data, licence CC BY-NC 4.0 "
    "(https://creativecommons.org/licenses/by-nc/4.0/): credit Hydro-Quebec; "
    "non-commercial use only."
)
# Dataset ids. "recent" is the rolling two-day window; "history" is the archive.
QUEBEC_DEMAND_DATASETS = {
    "recent": "demande-electricite-quebec",
    "history": "historique-demande-electricite-quebec",
}
QUEBEC_GENERATION_DATASETS = {
    "recent": "production-electricite-quebec",
    "history": "historique-production-electricite-quebec",
}
QUEBEC_TRADE_DATASET = "importations-exportations-avec-transits"
QUEBEC_TRADE_MARKETS = ("newengland", "newbrunswick", "newyork", "ontario")
QUEBEC_TRADE_SOURCES = ("gas", "nuclear", "unknown", "wind", "hydro")

# Flows at generating stations and control structures: one JSON file on
# hydroquebec.com (Donnees Quebec record `donnees-hydrometriques`, CC BY-NC 4.0).
QUEBEC_FLOWS_URL = (
    "https://www.hydroquebec.com/data/documents-donnees/donnees-ouvertes/json/"
    "Donnees_VUE_CENTRALES_ET_OUVRAGES.json"
)
QUEBEC_FLOWS_PAGE = "https://www.donneesquebec.ca/recherche/dataset/donnees-hydrometriques"
# 2.8 MB, rewritten about hourly (Last-Modified 20:45 UTC on a 20:48 read).
QUEBEC_FLOWS_TTL_SECONDS = 30 * 60
QUEBEC_FLOWS_MAX_FACILITIES = 200

QUEBEC_CACHE_TTL_RECENT_SECONDS = 5 * 60
QUEBEC_CACHE_TTL_HISTORY_SECONDS = 6 * 60 * 60
