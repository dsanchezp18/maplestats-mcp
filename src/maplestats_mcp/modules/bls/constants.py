"""Constants for the US Bureau of Labor Statistics module (Public Data API v2).

Limits and terms read on 2026-11-07 from bls.gov/developers/api_faqs.htm,
bls.gov/developers/termsOfService.htm and bls.gov/opub/copyright-information.htm;
behaviour checked live the same day (see client.py's module docstring).
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_URL = "https://api.bls.gov/publicAPI/v2/"
DATA_URL = f"{BASE_URL}timeseries/data/"
SURVEYS_URL = f"{BASE_URL}surveys"
POPULAR_URL = f"{BASE_URL}timeseries/popular"
SOURCE = "bls"

# The module uses the API without registration (MapleStats takes no source
# that needs a key). BLS FAQ table (2026-11-07), unregistered: 25 queries a
# day, 25 series and 10 years per query, 50 requests per 10 seconds. The
# daily count is per address, so every user of a hosted server shares it.
DAILY_QUERIES = 25
MAX_SERIES = 25
MAX_YEARS = 10
# A long range is fetched in chunks of the year limit, newest first; capped so
# one call spends at most three queries of the daily allowance.
MAX_CHUNKS = 3
DEFAULT_YEARS = 5

RATE_LIMIT_SOURCE = "bls"
RATE_LIMIT_PER_SECOND = 4.0
RATE_LIMIT_CAPACITY = 5.0
TIMEOUT_SECONDS = 45.0

# Most BLS series update monthly; caching six hours spares the daily allowance.
CACHE_TTL_DATA_SECONDS = 6 * 60 * 60
CACHE_TTL_LIST_SECONDS = 24 * 60 * 60

LICENCE = (
    "Source: U.S. Bureau of Labor Statistics (https://www.bls.gov/). BLS publications and "
    "data are in the public domain; BLS asks to be cited as the source "
    "(https://www.bls.gov/opub/copyright-information.htm). API terms "
    "(https://www.bls.gov/developers/termsOfService.htm): cite the date the data were "
    "retrieved, do not modify content and still cite BLS, and BLS.gov cannot vouch for "
    "data or analyses derived from these data."
)
LICENCE_FR = (
    "Source : Bureau of Labor Statistics des États-Unis (https://www.bls.gov/). Les "
    "publications et données du BLS sont du domaine public ; le BLS demande d'être cité "
    "comme source (https://www.bls.gov/opub/copyright-information.htm, en anglais). "
    "Conditions de l'API (https://www.bls.gov/developers/termsOfService.htm) : citer la "
    "date d'extraction, ne pas modifier le contenu en citant encore le BLS ; BLS.gov ne "
    "garantit pas les données ni les analyses qui en sont tirées."
)

SCHEDULE = "https://www.bls.gov/schedule/news_release/"


@dataclass(frozen=True)
class Release:
    name_en: str
    name_fr: str
    schedule_url: str


# News release behind each survey prefix, with its release schedule page.
RELEASES: dict[str, Release] = {
    "CE": Release(
        "The Employment Situation", "Situation de l'emploi (Employment Situation)",
        f"{SCHEDULE}empsit.htm",
    ),
    "LN": Release(
        "The Employment Situation", "Situation de l'emploi (Employment Situation)",
        f"{SCHEDULE}empsit.htm",
    ),
    "CU": Release("Consumer Price Index", "Indice des prix à la consommation", f"{SCHEDULE}cpi.htm"),
    "CW": Release("Consumer Price Index", "Indice des prix à la consommation", f"{SCHEDULE}cpi.htm"),
    "SU": Release("Consumer Price Index", "Indice des prix à la consommation", f"{SCHEDULE}cpi.htm"),
    "AP": Release("Consumer Price Index", "Indice des prix à la consommation", f"{SCHEDULE}cpi.htm"),
    "WP": Release("Producer Price Index", "Indice des prix à la production", f"{SCHEDULE}ppi.htm"),
    "JT": Release(
        "Job Openings and Labor Turnover Survey", "Enquête sur les postes vacants et le "
        "roulement (JOLTS)", f"{SCHEDULE}jolts.htm",
    ),
    "CI": Release("Employment Cost Index", "Indice du coût de l'emploi", f"{SCHEDULE}eci.htm"),
    "PR": Release(
        "Productivity and Costs", "Productivité et coûts", f"{SCHEDULE}prod2.htm",
    ),
    "EI": Release(
        "U.S. Import and Export Price Indexes", "Indices des prix à l'importation et à "
        "l'exportation des États-Unis", f"{SCHEDULE}ximpim.htm",
    ),
    "LA": Release(
        "State Employment and Unemployment", "Emploi et chômage par État",
        f"{SCHEDULE}laus.htm",
    ),
    "SM": Release(
        "State Employment and Unemployment", "Emploi et chômage par État",
        f"{SCHEDULE}laus.htm",
    ),
}  # fmt: skip


@dataclass(frozen=True)
class KnownSeries:
    """A series this module can describe: the API sends no titles without registration."""

    title_en: str
    title_fr: str
    units_en: str
    units_fr: str
    keywords: str = ""


_K = "thousands of persons"
_K_FR = "milliers de personnes"
_PCT = "per cent"
_PCT_FR = "pour cent"
_CPI = "index, 1982-84 = 100"
_CPI_FR = "indice, 1982-1984 = 100"
# Import and export price indexes: the base period differs by series.
_IDX = "index"
_IDX_FR = "indice"

# Every id checked live on 2026-11-07 (all returned 2026 data). Titles follow
# the BLS's own series titles; the seasonal code is the third character.
KNOWN_SERIES: dict[str, KnownSeries] = {
    "CES0000000001": KnownSeries(
        "All employees, total nonfarm (payroll employment)",
        "Salariés, total non agricole (emploi salarié)", _K, _K_FR, "payrolls jobs nfp",
    ),
    "CEU0000000001": KnownSeries(
        "All employees, total nonfarm (payroll employment)",
        "Salariés, total non agricole (emploi salarié)", _K, _K_FR, "payrolls jobs nfp",
    ),
    "CES0500000003": KnownSeries(
        "Average hourly earnings of all employees, total private",
        "Rémunération horaire moyenne de tous les salariés, secteur privé",
        "dollars per hour", "dollars l'heure", "wages pay salaire",
    ),
    "CEU0500000003": KnownSeries(
        "Average hourly earnings of all employees, total private",
        "Rémunération horaire moyenne de tous les salariés, secteur privé",
        "dollars per hour", "dollars l'heure", "wages pay salaire",
    ),
    "CES0500000002": KnownSeries(
        "Average weekly hours of all employees, total private",
        "Durée hebdomadaire moyenne du travail, secteur privé", "hours", "heures",
        "hours worked",
    ),
    "LNS14000000": KnownSeries(
        "Unemployment rate, 16 years and over", "Taux de chômage, 16 ans et plus",
        _PCT, _PCT_FR, "jobless chomage",
    ),
    "LNU04000000": KnownSeries(
        "Unemployment rate, 16 years and over", "Taux de chômage, 16 ans et plus",
        _PCT, _PCT_FR, "jobless chomage",
    ),
    "LNS14000006": KnownSeries(
        "Unemployment rate, Black or African American, 16 years and over",
        "Taux de chômage, personnes noires ou afro-américaines, 16 ans et plus",
        _PCT, _PCT_FR, "race",
    ),
    "LNS11300000": KnownSeries(
        "Labor force participation rate, 16 years and over",
        "Taux d'activité, 16 ans et plus", _PCT, _PCT_FR, "participation activite",
    ),
    "LNU01300000": KnownSeries(
        "Labor force participation rate, 16 years and over",
        "Taux d'activité, 16 ans et plus", _PCT, _PCT_FR, "participation activite",
    ),
    "LNS12300000": KnownSeries(
        "Employment-population ratio, 16 years and over",
        "Taux d'emploi, 16 ans et plus", _PCT, _PCT_FR, "employment rate",
    ),
    "LNS13327709": KnownSeries(
        "U-6 unemployment rate: unemployed, marginally attached and part time for economic "
        "reasons", "Taux de chômage U-6 : chômeurs, personnes marginalement attachées et "
        "temps partiel involontaire", _PCT, _PCT_FR, "underemployment sous-emploi",
    ),
    "CUUR0000SA0": KnownSeries(
        "CPI for all urban consumers (CPI-U), all items, U.S. city average",
        "IPC des consommateurs urbains (CPI-U), ensemble, moyenne des villes américaines",
        _CPI, _CPI_FR, "inflation consumer prices headline",
    ),
    "CUSR0000SA0": KnownSeries(
        "CPI for all urban consumers (CPI-U), all items, U.S. city average",
        "IPC des consommateurs urbains (CPI-U), ensemble, moyenne des villes américaines",
        _CPI, _CPI_FR, "inflation consumer prices headline",
    ),
    "CUUR0000SA0L1E": KnownSeries(
        "CPI-U, all items less food and energy (core), U.S. city average",
        "CPI-U, ensemble sauf aliments et énergie (inflation de base), moyenne des villes "
        "américaines", _CPI, _CPI_FR, "core inflation de base",
    ),
    "CUSR0000SA0L1E": KnownSeries(
        "CPI-U, all items less food and energy (core), U.S. city average",
        "CPI-U, ensemble sauf aliments et énergie (inflation de base), moyenne des villes "
        "américaines", _CPI, _CPI_FR, "core inflation de base",
    ),
    "CUSR0000SAF1": KnownSeries(
        "CPI-U, food, U.S. city average", "CPI-U, aliments, moyenne des villes américaines",
        _CPI, _CPI_FR, "groceries alimentation",
    ),
    "CUSR0000SA0E": KnownSeries(
        "CPI-U, energy, U.S. city average", "CPI-U, énergie, moyenne des villes américaines",
        _CPI, _CPI_FR, "gasoline essence",
    ),
    "CUSR0000SAH1": KnownSeries(
        "CPI-U, shelter, U.S. city average", "CPI-U, logement, moyenne des villes américaines",
        _CPI, _CPI_FR, "rent housing loyer",
    ),
    "CWUR0000SA0": KnownSeries(
        "CPI for urban wage earners and clerical workers (CPI-W), all items",
        "IPC des salariés urbains et employés de bureau (CPI-W), ensemble",
        _CPI, _CPI_FR, "social security indexation",
    ),
    "SUUR0000SA0": KnownSeries(
        "Chained CPI for all urban consumers (C-CPI-U), all items",
        "IPC chaîné des consommateurs urbains (C-CPI-U), ensemble",
        "index, December 1999 = 100", "indice, décembre 1999 = 100", "chained",
    ),
    "WPSFD4": KnownSeries(
        "PPI final demand", "IPP, demande finale", "index, November 2009 = 100",
        "indice, novembre 2009 = 100", "producer prices wholesale prix production",
    ),
    "WPUFD4": KnownSeries(
        "PPI final demand", "IPP, demande finale", "index, November 2009 = 100",
        "indice, novembre 2009 = 100", "producer prices wholesale prix production",
    ),
    "JTS000000000000000JOL": KnownSeries(
        "Job openings, total nonfarm", "Postes vacants, total non agricole", _K, _K_FR,
        "vacancies jolts postes vacants",
    ),
    "JTU000000000000000JOL": KnownSeries(
        "Job openings, total nonfarm", "Postes vacants, total non agricole", _K, _K_FR,
        "vacancies jolts postes vacants",
    ),
    "JTS000000000000000JOR": KnownSeries(
        "Job openings rate, total nonfarm", "Taux de postes vacants, total non agricole",
        _PCT, _PCT_FR, "vacancy rate jolts",
    ),
    "JTS000000000000000QUR": KnownSeries(
        "Quits rate, total nonfarm", "Taux de démissions, total non agricole", _PCT, _PCT_FR,
        "quits turnover demissions jolts",
    ),
    "CIU1010000000000A": KnownSeries(
        "Employment Cost Index, total compensation, civilian workers, 12-month change",
        "Indice du coût de l'emploi, rémunération totale, travailleurs civils, variation sur "
        "12 mois", _PCT, _PCT_FR, "eci wages compensation labour costs",
    ),
    "PRS85006092": KnownSeries(
        "Labor productivity (output per hour), nonfarm business, change from previous "
        "quarter at annual rate", "Productivité du travail (production horaire), entreprises "
        "non agricoles, variation trimestrielle annualisée", _PCT, _PCT_FR, "productivity",
    ),
    "EIUIR": KnownSeries(
        "Import price index, all commodities", "Indice des prix à l'importation, tous les "
        "produits", _IDX, _IDX_FR, "import prices",
    ),
    "EIUIQ": KnownSeries(
        "Export price index, all commodities", "Indice des prix à l'exportation, tous les "
        "produits", _IDX, _IDX_FR, "export prices",
    ),
    "EIUCOCANTOT": KnownSeries(
        "Import price index, imports from Canada, all industries",
        "Indice des prix à l'importation, importations en provenance du Canada, toutes les "
        "industries", _IDX, _IDX_FR,
        "canada trade import prices",
    ),
}  # fmt: skip


@dataclass(frozen=True)
class Indicator:
    seasonally_adjusted: str
    not_seasonally_adjusted: str
    label_en: str
    label_fr: str


# Named shortcuts for bls_get_indicator: (SA id, NSA id).
INDICATORS: dict[str, Indicator] = {
    "nonfarm_payrolls": Indicator(
        "CES0000000001", "CEU0000000001", "Nonfarm payroll employment",
        "Emploi salarié non agricole",
    ),
    "unemployment_rate": Indicator(
        "LNS14000000", "LNU04000000", "Unemployment rate", "Taux de chômage",
    ),
    "cpi_all_items": Indicator(
        "CUSR0000SA0", "CUUR0000SA0", "CPI-U, all items", "CPI-U, ensemble",
    ),
    "cpi_core": Indicator(
        "CUSR0000SA0L1E", "CUUR0000SA0L1E", "CPI-U, all items less food and energy",
        "CPI-U, ensemble sauf aliments et énergie",
    ),
    "average_hourly_earnings": Indicator(
        "CES0500000003", "CEU0500000003", "Average hourly earnings, total private",
        "Rémunération horaire moyenne, secteur privé",
    ),
    "participation_rate": Indicator(
        "LNS11300000", "LNU01300000", "Labor force participation rate", "Taux d'activité",
    ),
    "job_openings": Indicator(
        "JTS000000000000000JOL", "JTU000000000000000JOL", "Job openings (JOLTS)",
        "Postes vacants (JOLTS)",
    ),
    "ppi_final_demand": Indicator(
        "WPSFD4", "WPUFD4", "PPI final demand", "IPP, demande finale",
    ),
}  # fmt: skip
