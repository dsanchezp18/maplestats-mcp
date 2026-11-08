"""Constants for the UK Office for National Statistics (ONS) module.

Endpoints, limits and series ids checked live on 2026-11-08 (see client.py's
module docstring).
"""

from __future__ import annotations

from dataclasses import dataclass

SEARCH_URL = "https://api.beta.ons.gov.uk/v1/search"
SITE_URL = "https://www.ons.gov.uk"
SOURCE = "ons"

LICENCE_URL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
TERMS_URL = "https://www.ons.gov.uk/help/termsandconditions"
LIMITS_URL = "https://developer.ons.gov.uk/bots/"

# ONS terms and conditions (read 2026-11-08): most content is Crown copyright
# under the Open Government Licence; the ONS licences page says ONS material
# may be re-used "commercially or privately" freely under OGL v3, with a
# source accreditation to the ONS.
LICENCE = (
    "Source: Office for National Statistics licensed under the Open Government Licence v3.0 "
    f"({LICENCE_URL}): any use, commercial included, with the ONS acknowledged as the source."
)
LICENCE_FR = (
    "Source : Office for National Statistics, sous licence Open Government Licence v3.0 "
    f"({LICENCE_URL}, en anglais) : toute utilisation, y compris commerciale, en citant "
    "l'ONS comme source."
)

# Developer Hub "Guide to rate limiting" (read 2026-11-08): 120 requests per
# 10 seconds and 200 a minute on all site and API assets, 15 per 10 seconds
# on high-demand site assets; over them the ONS answers 429 with Retry-After
# and blocks for a time it varies with release schedules. One request a
# second keeps well under all three.
RATE_LIMIT_SOURCE = "ons"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 3.0
COOLDOWN_SECONDS = 5 * 60

LIMITS = (
    "ONS limits (developer.ons.gov.uk/bots): 120 requests per 10 seconds, 200 a minute, 15 "
    "per 10 seconds on high-demand pages, then a temporary block. This server sends at most "
    "one request a second and caches answers (series 1 h, search 6 h)."
)
LIMITS_FR = (
    "Limites de l'ONS (developer.ons.gov.uk/bots) : 120 requêtes par 10 secondes, 200 par "
    "minute, 15 par 10 secondes sur les pages très demandées, puis un blocage temporaire. Ce "
    "serveur envoie au plus une requête par seconde et garde les réponses en cache (séries "
    "1 h, recherche 6 h)."
)

TIMEOUT_SECONDS = 60.0
# Series change on release mornings (07:00 UK time); an hour keeps a figure
# at most an hour behind a release.
CACHE_TTL_SERIES_SECONDS = 60 * 60
CACHE_TTL_SEARCH_SECONDS = 6 * 60 * 60

MAX_SEARCH_RESULTS = 50
SEARCH_FETCH = 100
MAX_ROWS = 2_000
MAX_LAST_N = 1_000

FREQUENCIES = {"monthly": "months", "quarterly": "quarters", "annual": "years"}


@dataclass(frozen=True)
class Indicator:
    """A preset UK headline series and where Canada's counterpart is."""

    series_id: str
    dataset: str
    label_en: str
    label_fr: str
    frequency: str
    canada_en: str
    canada_fr: str


_CPI_CANADA_EN = (
    "Canada: CPI, Statistics Canada table 18-10-0004-01, 12-month change (wds_ tools; "
    "statcan_indicators_ for the headline). The UK CPI is the harmonised index (HICP "
    "methods); Canada's CPI includes owned accommodation costs, closer to the UK's CPIH."
)
_CPI_CANADA_FR = (
    "Canada : IPC, tableau 18-10-0004-01 de Statistique Canada, variation sur 12 mois (outils "
    "wds_ ; statcan_indicators_ pour le chiffre phare). L'IPC britannique suit la méthode de "
    "l'indice harmonisé (IPCH) ; l'IPC canadien comprend les coûts du logement occupé par son "
    "propriétaire, plus proche de l'IPCH britannique (CPIH)."
)
_LFS_CANADA_EN = (
    "Canada: Labour Force Survey, Statistics Canada table 14-10-0287-01, monthly, seasonally "
    "adjusted (wds_ tools). The UK figures are three-month averages for ages 16 and over "
    "(employment and inactivity 16 to 64); Canada's are single months for ages 15 and over. "
    "ilo_compare_countries has both on ILO definitions."
)
_LFS_CANADA_FR = (
    "Canada : Enquête sur la population active, tableau 14-10-0287-01 de Statistique Canada, "
    "mensuel, désaisonnalisé (outils wds_). Les chiffres britanniques sont des moyennes sur "
    "trois mois des 16 ans et plus (emploi et inactivité : 16 à 64 ans) ; les canadiens, des "
    "mois isolés des 15 ans et plus. ilo_compare_countries donne les deux selon les "
    "définitions de l'OIT."
)
_GDP_CANADA_EN = (
    "Canada: real GDP, Statistics Canada table 36-10-0104-01 (expenditure-based, quarterly; "
    "wds_ tools). Canada's headline quarterly growth is annualized; the ONS's is not."
)
_GDP_CANADA_FR = (
    "Canada : PIB réel, tableau 36-10-0104-01 de Statistique Canada (en termes de dépenses, "
    "trimestriel ; outils wds_). La croissance trimestrielle phare du Canada est annualisée, "
    "celle de l'ONS non."
)

# Every series fetched live on 2026-11-08 (scripts/smoke_test_ons.py).
INDICATORS: dict[str, Indicator] = {
    "cpi_inflation": Indicator(
        "D7G7",
        "MM23",
        "CPI annual rate, all items (per cent)",
        "IPC, taux annuel, ensemble (%)",
        "monthly",
        _CPI_CANADA_EN,
        _CPI_CANADA_FR,
    ),
    "cpih_inflation": Indicator(
        "L55O",
        "MM23",
        "CPIH annual rate (CPI including owner occupiers' housing costs), all items (per cent)",
        "CPIH, taux annuel (IPC avec les coûts du logement des propriétaires occupants), "
        "ensemble (%)",
        "monthly",
        _CPI_CANADA_EN,
        _CPI_CANADA_FR,
    ),
    "core_cpi_inflation": Indicator(
        "DKO8",
        "MM23",
        "CPI excluding energy, food, alcohol and tobacco, 12-month rate (per cent)",
        "IPC hors énergie, alimentation, alcool et tabac, taux sur 12 mois (%)",
        "monthly",
        "Canada: CPI all-items excluding food and energy, Statistics Canada table "
        "18-10-0004-01, and the Bank of Canada's core measures (CPI-trim, CPI-median), table "
        "18-10-0256-01 (wds_ tools).",
        "Canada : IPC d'ensemble hors aliments et énergie, tableau 18-10-0004-01 de Statistique "
        "Canada, et mesures de l'inflation fondamentale de la Banque du Canada (IPC-tronq, "
        "IPC-méd), tableau 18-10-0256-01 (outils wds_).",
    ),
    "rpi_inflation": Indicator(
        "CZBH",
        "MM23",
        "RPI all items, percentage change over 12 months (per cent)",
        "RPI (indice des prix de détail), ensemble, variation sur 12 mois (%)",
        "monthly",
        "Canada: no counterpart; the RPI is a legacy UK index that the ONS does not consider a "
        "national statistic. Compare with the CPI (18-10-0004-01).",
        "Canada : pas d'équivalent ; le RPI est un ancien indice britannique que l'ONS ne "
        "considère pas comme une statistique nationale. Comparez avec l'IPC (18-10-0004-01).",
    ),
    "gdp_quarterly_growth": Indicator(
        "IHYQ",
        "QNA",
        "GDP, quarter-on-quarter growth, chained volume, seasonally adjusted (per cent)",
        "PIB, croissance d'un trimestre à l'autre, volume chaîné, désaisonnalisé (%)",
        "quarterly",
        _GDP_CANADA_EN,
        _GDP_CANADA_FR,
    ),
    "gdp_annual_growth": Indicator(
        "IHYP",
        "QNA",
        "GDP, year-on-year growth, chained volume, seasonally adjusted (per cent)",
        "PIB, croissance sur un an, volume chaîné, désaisonnalisé (%)",
        "annual",
        _GDP_CANADA_EN,
        _GDP_CANADA_FR,
    ),
    "monthly_gdp_growth": Indicator(
        "ECYX",
        "MGDP",
        "Monthly GDP (gross value added), month-on-month growth, chained volume, seasonally "
        "adjusted (per cent)",
        "PIB mensuel (valeur ajoutée brute), croissance d'un mois à l'autre, volume chaîné, "
        "désaisonnalisé (%)",
        "monthly",
        "Canada: GDP at basic prices by industry, Statistics Canada table 36-10-0434-01, "
        "monthly (wds_ tools).",
        "Canada : PIB aux prix de base par industrie, tableau 36-10-0434-01 de Statistique "
        "Canada, mensuel (outils wds_).",
    ),
    "unemployment_rate": Indicator(
        "MGSX",
        "LMS",
        "Unemployment rate, aged 16 and over, seasonally adjusted, three-month average (per cent)",
        "Taux de chômage, 16 ans et plus, désaisonnalisé, moyenne sur trois mois (%)",
        "monthly",
        _LFS_CANADA_EN,
        _LFS_CANADA_FR,
    ),
    "employment_rate": Indicator(
        "LF24",
        "LMS",
        "Employment rate, aged 16 to 64, seasonally adjusted, three-month average (per cent)",
        "Taux d'emploi, 16 à 64 ans, désaisonnalisé, moyenne sur trois mois (%)",
        "monthly",
        _LFS_CANADA_EN,
        _LFS_CANADA_FR,
    ),
    "inactivity_rate": Indicator(
        "LF2S",
        "LMS",
        "Economic inactivity rate, aged 16 to 64, seasonally adjusted, three-month average "
        "(per cent)",
        "Taux d'inactivité, 16 à 64 ans, désaisonnalisé, moyenne sur trois mois (%)",
        "monthly",
        _LFS_CANADA_EN,
        _LFS_CANADA_FR,
    ),
    "regular_pay_growth": Indicator(
        "KAI9",
        "LMS",
        "Average weekly earnings, regular pay, year-on-year growth of the three-month average, "
        "seasonally adjusted (per cent)",
        "Gains hebdomadaires moyens, salaire régulier, croissance sur un an de la moyenne sur "
        "trois mois, désaisonnalisée (%)",
        "monthly",
        "Canada: average weekly earnings, Statistics Canada table 14-10-0223-01 (SEPH, "
        "including overtime; wds_ tools).",
        "Canada : rémunération hebdomadaire moyenne, tableau 14-10-0223-01 de Statistique "
        "Canada (EERH, heures supplémentaires comprises ; outils wds_).",
    ),
    "total_pay_growth": Indicator(
        "KAC3",
        "LMS",
        "Average weekly earnings, total pay, year-on-year growth of the three-month average, "
        "seasonally adjusted (per cent)",
        "Gains hebdomadaires moyens, salaire total, croissance sur un an de la moyenne sur "
        "trois mois, désaisonnalisée (%)",
        "monthly",
        "Canada: average weekly earnings, Statistics Canada table 14-10-0223-01 (SEPH; wds_ "
        "tools).",
        "Canada : rémunération hebdomadaire moyenne, tableau 14-10-0223-01 de Statistique "
        "Canada (EERH ; outils wds_).",
    ),
    "vacancies": Indicator(
        "AP2Y",
        "LMS",
        "Job vacancies, UK total, three-month average (thousands)",
        "Postes vacants, total du Royaume-Uni, moyenne sur trois mois (milliers)",
        "monthly",
        "Canada: job vacancies, Statistics Canada table 14-10-0371-01 (monthly, not seasonally "
        "adjusted; wds_ tools).",
        "Canada : postes vacants, tableau 14-10-0371-01 de Statistique Canada (mensuel, non "
        "désaisonnalisé ; outils wds_).",
    ),
    "public_sector_net_debt": Indicator(
        "HF6X",
        "PUSF",
        "Public sector net debt excluding public sector banks (per cent of GDP)",
        "Dette nette du secteur public, hors banques publiques (% du PIB)",
        "monthly",
        "Canada: federal debt in the Fiscal Reference Tables (finance_frt_ tools); general "
        "government debt for both countries in oecd_compare_countries (government_debt).",
        "Canada : dette fédérale dans les Tableaux de référence financiers (outils "
        "finance_frt_) ; dette des administrations publiques des deux pays dans "
        "oecd_compare_countries (government_debt).",
    ),
    "retail_sales_volume": Indicator(
        "J5EK",
        "DRSI",
        "Retail sales volume, all retailers including fuel, seasonally adjusted (index)",
        "Volume des ventes au détail, tous détaillants, carburant compris, désaisonnalisé (indice)",
        "monthly",
        "Canada: monthly retail trade sales, Statistics Canada table 20-10-0056-01 (current "
        "dollars; wds_ tools).",
        "Canada : ventes mensuelles du commerce de détail, tableau 20-10-0056-01 de Statistique "
        "Canada (dollars courants ; outils wds_).",
    ),
}
