"""Constants for the Eurostat module.

Endpoints, parameters, limits and codes checked live on 2026-11-07 (see
client.py's module docstring). No API key or registration anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

API_BASE = "https://ec.europa.eu/eurostat/api/dissemination/"
DATA_URL = API_BASE + "statistics/1.0/data/"
TOC_URL = API_BASE + "catalogue/toc/txt"
STRUCTURE_URL = API_BASE + "sdmx/2.1/dataflow/ESTAT/"
DATABROWSER_URL = "https://ec.europa.eu/eurostat/databrowser/view/"
SOURCE = "eurostat"

# https://ec.europa.eu/eurostat/help/copyright-notice, read 2026-11-07.
LICENCE = (
    "Source: Eurostat (https://ec.europa.eu/eurostat). Creative Commons Attribution 4.0 "
    "(Commission Decision 2011/833/EU; https://ec.europa.eu/eurostat/help/copyright-notice): "
    "reuse for commercial or non-commercial purposes is authorised provided the source is "
    "acknowledged, e.g. 'Source: Eurostat, <dataset code>, <access date>'. Data for "
    "countries outside the EU, EFTA and candidate countries (e.g. the United States) and "
    "data marked as coming from non-Eurostat sources may not be reused commercially."
)
LICENCE_FR = (
    "Source : Eurostat (https://ec.europa.eu/eurostat). Creative Commons Attribution 4.0 "
    "(décision 2011/833/UE de la Commission ; https://ec.europa.eu/eurostat/help/copyright-"
    "notice) : la réutilisation à des fins commerciales ou non est autorisée sous réserve "
    "de mentionner la source, p. ex. « Source : Eurostat, <code du jeu>, <date de "
    "consultation> ». Les données des pays hors UE, AELE et pays candidats (p. ex. les "
    "États-Unis) et les données provenant de sources autres qu'Eurostat ne peuvent pas "
    "être réutilisées à des fins commerciales."
)

# Eurostat publishes no numeric rate limit; its asynchronous-API guide asks
# for one extraction at a time and no parallel requests ("fair use"), and
# throttles heavy users by sending their requests to the asynchronous queue.
RATE_LIMIT_SOURCE = "eurostat"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 2.0

TOC_TIMEOUT_SECONDS = 60.0
STRUCTURE_TIMEOUT_SECONDS = 60.0
DATA_TIMEOUT_SECONDS = 60.0

CACHE_TTL_TOC_SECONDS = 12 * 60 * 60
CACHE_TTL_STRUCTURE_SECONDS = 12 * 60 * 60
CACHE_TTL_DATA_SECONDS = 3 * 60 * 60

# The API answers up to 5,000,000 cells, but 2.4 million took 88 s and
# 30 MB on 2026-11-07; keep a request well inside a tool call.
MAX_CELLS = 60_000
MAX_SERIES = 400
MAX_ROWS = 5_000
MAX_LAST_N = 500
DEFAULT_LAST_N = 12
MAX_SEARCH_RESULTS = 50
MAX_CODES_PER_DIMENSION = 300

LANGS = {"en": "EN", "fr": "FR"}

# Eurostat writes Greece as EL and the United Kingdom as UK; ISO codes map.
ISO_TO_EUROSTAT = {"GR": "EL", "GB": "UK"}

EU27 = (
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU",
    "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
)  # fmt: skip
# Bulgaria joined on 2026-01-01 (EA21 in Eurostat's GEO codelist, 2026-11-07).
EURO_AREA = (
    "AT", "BE", "BG", "CY", "DE", "EE", "EL", "ES", "FI", "FR", "HR", "IE", "IT", "LT",
    "LU", "LV", "MT", "NL", "PT", "SI", "SK",
)  # fmt: skip
EFTA = ("CH", "IS", "LI", "NO")
CANDIDATES = ("AL", "BA", "GE", "MD", "ME", "MK", "RS", "TR", "UA", "XK")

# Aggregates tried in order: the first the dataset has wins. EA (changing
# composition) is last because most headline series use the fixed EA21.
EU_AGGREGATES = ("EU27_2020", "EU")
EURO_AREA_AGGREGATES = ("EA21", "EA20", "EA", "EA19")

# Shortcuts accepted in `geo`, upper-cased with spaces and hyphens as "_".
GEO_GROUPS: dict[str, tuple[str, ...]] = {
    "EU_MEMBERS": EU27,
    "EU27_MEMBERS": EU27,
    "EURO_AREA_MEMBERS": EURO_AREA,
    "EUROZONE_MEMBERS": EURO_AREA,
    "BIG_FOUR": ("DE", "FR", "IT", "ES"),
}
GEO_AGGREGATE_ALIASES: dict[str, tuple[str, ...]] = {
    "EU27": EU_AGGREGATES,
    "EU": EU_AGGREGATES,
    "UE": EU_AGGREGATES,
    "UE27": EU_AGGREGATES,
    "EUROPEAN_UNION": EU_AGGREGATES,
    "UNION_EUROPEENNE": EU_AGGREGATES,
    "EURO_AREA": EURO_AREA_AGGREGATES,
    "EUROZONE": EURO_AREA_AGGREGATES,
    "ZONE_EURO": EURO_AREA_AGGREGATES,
    "EA": EURO_AREA_AGGREGATES,
}

# Atomic observation flags, from the OBS_FLAG codelist (ESTAT, v1.39, read
# 2026-11-07). Combined flags ("bep") are their letters in order. The data
# response labels the flags it uses; this table is the fallback.
FLAGS: dict[str, tuple[str, str]] = {
    "b": ("break in time series", "rupture de série"),
    "c": ("confidential", "confidentiel"),
    "d": ("definition differs (see metadata)", "définition différente (voir métadonnées)"),
    "e": ("estimated", "estimé"),
    "f": ("forecast", "prévision"),
    "i": (
        "value imputed by Eurostat or other receiving agencies",
        "valeur imputée par Eurostat ou d'autres organismes destinataires",
    ),
    "m": (
        "missing value; data cannot exist",
        "valeur manquante ; les données ne peuvent pas exister",
    ),
    "n": ("not significant", "non significatif"),
    "p": ("provisional", "provisoire"),
    "r": ("revised", "révisé"),
    "s": ("Eurostat estimate", "estimation d'Eurostat"),
    "u": ("low reliability", "peu fiable"),
    "z": ("not applicable", "sans objet"),
}


@dataclass(frozen=True)
class Indicator:
    """A preset series for eurostat_compare: fixed codes for every dimension but geo."""

    dataset: str
    filters: dict[str, str]
    label_en: str
    label_fr: str
    canada_en: str
    canada_fr: str


_GDP_CANADA_EN = (
    "Canada: Statistics Canada table 36-10-0104-01 (GDP, expenditure-based, quarterly), "
    "through the wds_ tools."
)
_GDP_CANADA_FR = (
    "Canada : tableau 36-10-0104-01 de Statistique Canada (PIB en termes de dépenses, "
    "trimestriel), avec les outils wds_."
)

# Every preset checked live on 2026-11-07 for EU27_2020, EA21 and DE.
INDICATORS: dict[str, Indicator] = {
    "gdp_growth_quarterly": Indicator(
        "namq_10_gdp",
        {"unit": "CLV_PCH_PRE", "s_adj": "SCA", "na_item": "B1GQ"},
        "Real GDP, change on the previous quarter, seasonally and calendar adjusted (%)",
        "PIB réel, variation sur le trimestre précédent, désaisonnalisé et corrigé des "
        "effets de calendrier (%)",
        _GDP_CANADA_EN + " Canada's headline is annualized; Eurostat's is not.",
        _GDP_CANADA_FR + " Le chiffre phare canadien est annualisé, celui d'Eurostat non.",
    ),
    "gdp_growth_year_on_year": Indicator(
        "namq_10_gdp",
        {"unit": "CLV_PCH_SM", "s_adj": "SCA", "na_item": "B1GQ"},
        "Real GDP, change on the same quarter of the previous year, seasonally and calendar "
        "adjusted (%)",
        "PIB réel, variation sur le même trimestre de l'année précédente, désaisonnalisé et "
        "corrigé des effets de calendrier (%)",
        _GDP_CANADA_EN,
        _GDP_CANADA_FR,
    ),
    "gdp_growth_annual": Indicator(
        "nama_10_gdp",
        {"unit": "CLV_PCH_PRE", "na_item": "B1GQ"},
        "Real GDP, annual change (%)",
        "PIB réel, variation annuelle (%)",
        _GDP_CANADA_EN,
        _GDP_CANADA_FR,
    ),
    "gdp_per_capita_pps": Indicator(
        "nama_10_pc",
        {"unit": "CP_PPS_EU27_2020_HAB", "na_item": "B1GQ"},
        "GDP per capita, current prices, purchasing power standards (PPS, EU27 = basis)",
        "PIB par habitant, prix courants, standards de pouvoir d'achat (SPA, base UE27)",
        "Canada: not in Eurostat; World Bank GDP per capita, PPP (worldbank_ tools, "
        "NY.GDP.PCAP.PP.CD) is in a different unit (international dollars).",
        "Canada : absent d'Eurostat ; le PIB par habitant en PPA de la Banque mondiale "
        "(outils worldbank_, NY.GDP.PCAP.PP.CD) est dans une autre unité (dollars "
        "internationaux).",
    ),
    "hicp_inflation": Indicator(
        "prc_hicp_minr",
        {"unit": "RCH_A", "coicop18": "TOTAL"},
        "HICP inflation, all items, annual rate of change (%)",
        "Inflation IPCH, ensemble, taux de variation annuel (%)",
        "Canada: CPI, Statistics Canada table 18-10-0004-01 (wds_ tools). The CPI is not "
        "harmonised: it includes owners' housing costs, which the HICP leaves out.",
        "Canada : IPC, tableau 18-10-0004-01 de Statistique Canada (outils wds_). L'IPC "
        "n'est pas harmonisé : il comprend le coût du logement des propriétaires, que l'IPCH "
        "exclut.",
    ),
    "unemployment_rate": Indicator(
        "une_rt_m",
        {"s_adj": "SA", "age": "TOTAL", "sex": "T", "unit": "PC_ACT"},
        "Unemployment rate, seasonally adjusted, monthly (% of the labour force)",
        "Taux de chômage, désaisonnalisé, mensuel (% de la population active)",
        "Canada: Labour Force Survey, Statistics Canada table 14-10-0287-01 (wds_ tools). "
        "Eurostat counts ages 15 to 74; the LFS counts 15 and over.",
        "Canada : Enquête sur la population active, tableau 14-10-0287-01 de Statistique "
        "Canada (outils wds_). Eurostat compte les 15 à 74 ans ; l'EPA, les 15 ans et plus.",
    ),
    "employment_rate": Indicator(
        "lfsi_emp_q",
        {"indic_em": "EMP_LFS", "age": "Y20-64", "unit": "PC_POP", "sex": "T", "s_adj": "SA"},
        "Employment rate, ages 20 to 64, seasonally adjusted, quarterly (% of population)",
        "Taux d'emploi, 20 à 64 ans, désaisonnalisé, trimestriel (% de la population)",
        "Canada: Labour Force Survey, Statistics Canada table 14-10-0287-01 (wds_ tools), "
        "whose age groups differ from 20 to 64.",
        "Canada : Enquête sur la population active, tableau 14-10-0287-01 de Statistique "
        "Canada (outils wds_), dont les groupes d'âge diffèrent des 20 à 64 ans.",
    ),
    "house_price_growth": Indicator(
        "prc_hpi_q",
        {"purchase": "TOTAL", "unit": "RCH_A"},
        "House price index, all dwellings, annual rate of change, quarterly (%)",
        "Indice des prix des logements, ensemble des logements, taux de variation annuel, "
        "trimestriel (%)",
        "Canada: bis_compare_countries with nominal_house_price_growth (BIS, all "
        "dwellings); Statistics Canada's New Housing Price Index covers new homes only.",
        "Canada : bis_compare_countries avec nominal_house_price_growth (BRI, ensemble des "
        "logements) ; l'Indice des prix des logements neufs de Statistique Canada ne couvre "
        "que le neuf.",
    ),
    "government_debt_to_gdp": Indicator(
        "gov_10q_ggdebt",
        {"unit": "PC_GDP", "sector": "S13", "na_item": "GD"},
        "General government gross debt (Maastricht), quarterly (% of GDP)",
        "Dette brute des administrations publiques (Maastricht), trimestrielle (% du PIB)",
        "Canada: bis_compare_countries with government_debt_to_gdp (BIS, debt at nominal "
        "value); Canada has no Maastricht-definition figure.",
        "Canada : bis_compare_countries avec government_debt_to_gdp (BRI, dette à la valeur "
        "nominale) ; le Canada ne publie pas de chiffre au sens de Maastricht.",
    ),
    "government_deficit_to_gdp": Indicator(
        "gov_10dd_edpt1",
        {"unit": "PC_GDP", "sector": "S13", "na_item": "B9"},
        "General government net lending (+) or borrowing (-), annual (% of GDP)",
        "Capacité (+) ou besoin (-) de financement des administrations publiques, annuel "
        "(% du PIB)",
        "Canada: federal and provincial budget balances in the Fiscal Reference Tables "
        "(finance_frt_ tools); the concepts differ from government net lending.",
        "Canada : soldes budgétaires fédéral et provinciaux des Tableaux de référence "
        "financiers (outils finance_frt_) ; les concepts diffèrent de la capacité de "
        "financement des administrations publiques.",
    ),
    "exports_to_gdp": Indicator(
        "nama_10_gdp",
        {"unit": "PC_GDP", "na_item": "P6"},
        "Exports of goods and services, annual (% of GDP)",
        "Exportations de biens et services, annuelles (% du PIB)",
        _GDP_CANADA_EN,
        _GDP_CANADA_FR,
    ),
    "imports_to_gdp": Indicator(
        "nama_10_gdp",
        {"unit": "PC_GDP", "na_item": "P7"},
        "Imports of goods and services, annual (% of GDP)",
        "Importations de biens et services, annuelles (% du PIB)",
        _GDP_CANADA_EN,
        _GDP_CANADA_FR,
    ),
}

DEFAULT_COMPARE_GEO = ("EU27", "EURO_AREA", "DE", "FR", "IT", "ES")
