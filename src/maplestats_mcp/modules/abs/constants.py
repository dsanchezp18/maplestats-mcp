"""Constants for the Australian Bureau of Statistics (ABS) Data API module.

Endpoints, codes and keys checked live on 2026-11-08 (see client.py's module
docstring).
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_URL = "https://data.api.abs.gov.au/rest/"
AGENCY = "ABS"
SOURCE = "abs"

DATA_ACCEPT = "application/vnd.sdmx.data+csv;labels=both"
STRUCTURE_ACCEPT = "application/vnd.sdmx.structure+json;version=1.0"

COPYRIGHT_URL = "https://www.abs.gov.au/website-privacy-copyright-and-disclaimer"
GUIDE_URL = (
    "https://www.abs.gov.au/about/data-services/application-programming-interfaces-apis/"
    "data-api-user-guide"
)

# The ABS copyright page (read 2026-11-08): "All material presented on this
# website is provided under a Creative Commons Attribution 4.0 International
# licence", except logos, trade marks, microdata and third-party content.
LICENCE = (
    "Source: Australian Bureau of Statistics. Creative Commons Attribution 4.0 International "
    f"({COPYRIGHT_URL}): any use, commercial included, with the ABS credited; third-party "
    "content excepted."
)
LICENCE_FR = (
    "Source : Australian Bureau of Statistics. Creative Commons Attribution 4.0 International "
    f"({COPYRIGHT_URL}, en anglais) : toute utilisation, y compris commerciale, en citant "
    "l'ABS ; contenus de tiers exclus."
)

# The Data API user guide (read 2026-11-08): keys were removed on 29 November
# 2024 ("freely accessible without the need for an API key"); the API is a
# beta whose availability "may be impacted during periods of high use"; no
# numeric rate limit is published.
RATE_LIMIT_SOURCE = "abs"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 3.0

LIMITS = (
    "The ABS Data API (beta) publishes no rate limit and warns that availability may drop at "
    "busy times; this server spaces requests (one a second at most) and caches answers (data "
    "6 h, structures and the dataset list 24 h). The beta may lag the ABS website after a "
    "release."
)
LIMITS_FR = (
    "L'API de données de l'ABS (bêta) ne publie pas de limite de débit et prévient que sa "
    "disponibilité peut baisser aux heures chargées ; ce serveur espace les requêtes (une par "
    "seconde au plus) et garde les réponses en cache (données 6 h, structures et liste des "
    "jeux 24 h). La bêta peut être en retard sur le site de l'ABS après une publication."
)

CATALOGUE_TIMEOUT_SECONDS = 120.0
STRUCTURE_TIMEOUT_SECONDS = 60.0
DATA_TIMEOUT_SECONDS = 90.0

CACHE_TTL_CATALOGUE_SECONDS = 24 * 60 * 60
CACHE_TTL_STRUCTURE_SECONDS = 24 * 60 * 60
CACHE_TTL_DATA_SECONDS = 6 * 60 * 60

MAX_SEARCH_RESULTS = 50
MAX_DESCRIPTION_CHARS = 400
MAX_CODES_PER_DIMENSION = 300
MAX_SERIES = 200
MAX_ROWS = 10_000
MAX_LAST_N = 1_000
MAX_KEY_BOUND = 1_000_000

# The area code the example key prefers: the ABS writes Australia AUS in most
# datasets and 50 in the CPI.
AUSTRALIA = ("AUS", "50")


@dataclass(frozen=True)
class Indicator:
    """A preset Australian headline series and where Canada's counterpart is."""

    dataflow: str
    key: str
    label_en: str
    label_fr: str
    canada_en: str
    canada_fr: str
    default_last_n: int


_LFS_CANADA_EN = (
    "Canada: Labour Force Survey, Statistics Canada table 14-10-0287-01, monthly, seasonally "
    "adjusted (wds_ tools). Both surveys cover ages 15 and over; ilo_compare_countries has "
    "both on ILO definitions."
)
_LFS_CANADA_FR = (
    "Canada : Enquête sur la population active, tableau 14-10-0287-01 de Statistique Canada, "
    "mensuel, désaisonnalisé (outils wds_). Les deux enquêtes portent sur les 15 ans et plus ; "
    "ilo_compare_countries donne les deux selon les définitions de l'OIT."
)

# Every key fetched live on 2026-11-08 (scripts/smoke_test_abs.py) and the
# latest values checked against the ABS release pages.
INDICATORS: dict[str, Indicator] = {
    "cpi_inflation": Indicator(
        "CPI",
        "3.10001.10.50.M",
        "CPI, all groups, Australia, change from the same month a year earlier (per cent)",
        "IPC, ensemble, Australie, variation sur 12 mois (%)",
        "Canada: CPI, Statistics Canada table 18-10-0004-01, 12-month change (wds_ tools).",
        "Canada : IPC, tableau 18-10-0004-01 de Statistique Canada, variation sur 12 mois "
        "(outils wds_).",
        24,
    ),
    "trimmed_mean_inflation": Indicator(
        "CPI",
        "3.999902.20.50.M",
        "CPI trimmed mean, seasonally adjusted, change from a year earlier (per cent)",
        "IPC, moyenne tronquée, désaisonnalisé, variation sur 12 mois (%)",
        "Canada: the Bank of Canada's CPI-trim, Statistics Canada table 18-10-0256-01 (wds_ "
        "tools). The two trim different shares of the price distribution.",
        "Canada : l'IPC-tronq de la Banque du Canada, tableau 18-10-0256-01 de Statistique "
        "Canada (outils wds_). Les deux mesures retranchent des parts différentes de la "
        "distribution des prix.",
        24,
    ),
    "unemployment_rate": Indicator(
        "LF",
        "M13.3.1599.20.AUS.M",
        "Unemployment rate, persons aged 15 and over, seasonally adjusted (per cent)",
        "Taux de chômage, 15 ans et plus, désaisonnalisé (%)",
        _LFS_CANADA_EN,
        _LFS_CANADA_FR,
        24,
    ),
    "participation_rate": Indicator(
        "LF",
        "M12.3.1599.20.AUS.M",
        "Participation rate, persons aged 15 and over, seasonally adjusted (per cent)",
        "Taux d'activité, 15 ans et plus, désaisonnalisé (%)",
        _LFS_CANADA_EN,
        _LFS_CANADA_FR,
        24,
    ),
    "employment_to_population_ratio": Indicator(
        "LF",
        "M16.3.1599.20.AUS.M",
        "Employment-to-population ratio, persons aged 15 and over, seasonally adjusted (per cent)",
        "Taux d'emploi, 15 ans et plus, désaisonnalisé (%)",
        _LFS_CANADA_EN,
        _LFS_CANADA_FR,
        24,
    ),
    "gdp_quarterly_growth": Indicator(
        "ANA_AGG",
        "M2.GPM.20.AUS.Q",
        "GDP, chain volume, seasonally adjusted, change from the previous quarter (per cent)",
        "PIB, volume chaîné, désaisonnalisé, variation d'un trimestre à l'autre (%)",
        "Canada: real GDP, Statistics Canada table 36-10-0104-01 (expenditure-based, "
        "quarterly; wds_ tools). Canada's headline quarterly growth is annualized; the ABS's "
        "is not.",
        "Canada : PIB réel, tableau 36-10-0104-01 de Statistique Canada (en termes de "
        "dépenses, trimestriel ; outils wds_). La croissance trimestrielle phare du Canada est "
        "annualisée, celle de l'ABS non.",
        12,
    ),
    "wage_price_index_growth": Indicator(
        "WPI",
        "3.THRPEB.7.TOT.20.AUS.Q",
        "Wage Price Index, total hourly rates of pay excluding bonuses, private and public, "
        "seasonally adjusted, change from a year earlier (per cent)",
        "Indice des prix des salaires, taux horaires totaux hors primes, privé et public, "
        "désaisonnalisé, variation sur un an (%)",
        "Canada: no fixed-basket wage index; the closest are average weekly earnings, "
        "Statistics Canada table 14-10-0223-01 (SEPH), whose changes also reflect shifts in "
        "the mix of jobs and hours.",
        "Canada : pas d'indice des salaires à panier fixe ; la plus proche est la rémunération "
        "hebdomadaire moyenne, tableau 14-10-0223-01 de Statistique Canada (EERH), dont les "
        "variations reflètent aussi les changements de composition des emplois et des heures.",
        12,
    ),
    "population_growth": Indicator(
        "ERP_Q",
        "3.3.TOT.AUS.Q",
        "Estimated resident population, change from a year earlier (per cent)",
        "Population résidente estimée, variation sur un an (%)",
        "Canada: population estimates, Statistics Canada table 17-10-0009-01 (quarterly; wds_ "
        "tools).",
        "Canada : estimations de la population, tableau 17-10-0009-01 de Statistique Canada "
        "(trimestriel ; outils wds_).",
        12,
    ),
}
