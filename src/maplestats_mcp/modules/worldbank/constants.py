"""Constants for the World Bank Indicators API module (WDI, Canada-centred).

Base URL, paths and response shapes checked live on 2026-10-03 (see
client.py's module docstring).
"""

from __future__ import annotations

BASE_URL = "https://api.worldbank.org/v2/"
SOURCE = "worldbank-wdi"

# World Development Indicators is source 2 of the API. Only WDI is served:
# the World Bank licenses its own datasets under CC BY 4.0, and WDI's catalogue
# entry carries that licence, while other API sources can carry other terms.
WDI_SOURCE_ID = "2"

LICENCE = (
    "Source: World Bank, World Development Indicators (https://data.worldbank.org/). "
    "Licensed under Creative Commons Attribution 4.0 International (CC BY 4.0), "
    "https://datacatalog.worldbank.org/public-licenses: credit the World Bank and say "
    "if the data were changed. Use of the data does not imply endorsement by the "
    "World Bank."
)
LICENCE_FR = (
    "Source : Banque mondiale, Indicateurs du développement dans le monde "
    "(https://donnees.banquemondiale.org/). Sous licence Creative Commons Attribution 4.0 "
    "International (CC BY 4.0), https://datacatalog.worldbank.org/public-licenses : "
    "citer la Banque mondiale et indiquer toute modification des données. L'utilisation "
    "des données n'implique aucune approbation de la Banque mondiale."
)

# The API publishes no rate limit and sent no rate-limit headers on 2026-10-03.
# Data calls took 0.2 to 21 s and the edge answered HTTP 502 to bursts of
# calls for several minutes, so pace well below anything a busy client sends.
RATE_LIMIT_SOURCE = "worldbank"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0

# The French WDI catalogue took 40 s to arrive (1.1 MB) on 2026-10-03.
CATALOGUE_TIMEOUT_SECONDS = 60.0
DATA_TIMEOUT_SECONDS = 45.0

# WDI is updated a few times a year (lastupdated 2026-07-13 on 2026-10-03).
CACHE_TTL_CATALOGUE_SECONDS = 24 * 60 * 60
CACHE_TTL_DATA_SECONDS = 6 * 60 * 60

# One page holds every year for every country requested (66 years x 39
# countries at most); the API default of 50 rows would page a single series.
PER_PAGE = 5000

CANADA = "CAN"

# G7 and OECD member countries (38, ISO 3166-1 alpha-3 as the API uses them),
# and the World Bank's own "OECD members" aggregate. Comparisons are limited to
# these so the tools stay about Canada and its usual peers.
G7 = ("CAN", "USA", "GBR", "FRA", "DEU", "ITA", "JPN")
OECD_MEMBERS = (
    "AUS", "AUT", "BEL", "CAN", "CHL", "COL", "CRI", "CZE", "DNK", "EST",
    "FIN", "FRA", "DEU", "GRC", "HUN", "ISL", "IRL", "ISR", "ITA", "JPN",
    "KOR", "LVA", "LTU", "LUX", "MEX", "NLD", "NZL", "NOR", "POL", "PRT",
    "SVK", "SVN", "ESP", "SWE", "CHE", "TUR", "GBR", "USA",
)  # fmt: skip
OECD_AGGREGATE = "OED"

# Shortcuts accepted in `compare_with`, besides single ISO3 codes.
GROUP_ALIASES: dict[str, tuple[str, ...]] = {
    "G7": G7,
    "OECD": (OECD_AGGREGATE,),
    "OECD_AVERAGE": (OECD_AGGREGATE,),
    "OECD_MEMBERS": OECD_MEMBERS,
}

MAX_SEARCH_RESULTS = 100
DESCRIPTION_CHARS = 600
