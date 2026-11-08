"""Constants for the ILOSTAT (International Labour Organization) module.

Endpoints, media types, codes and keys checked live on 2026-11-08 (see
client.py's module docstring).
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_URL = "https://sdmx.ilo.org/rest/"
AGENCY = "ILO"
SOURCE = "ilo"
ILOSTAT_URL = "https://ilostat.ilo.org/data/"

DATA_ACCEPT = "application/vnd.sdmx.data+csv;version=2.0.0;labels=both"
STRUCTURE_ACCEPT = "application/vnd.sdmx.structure+json;version=1.0"

RIGHTS_URL = "https://www.ilo.org/rights-and-permissions"

# The ILO's "Rights and permissions" page (read 2026-11-08): "As of 3 May 2023,
# databases and datasets together with the accompanying referential metadata
# are covered by the Creative Commons CC BY 4.0 licence", except microdata
# restricted to the ILO's use (not in ILOSTAT's SDMX API). CC BY 4.0 allows
# commercial use with attribution.
LICENCE = (
    "Source: ILOSTAT, International Labour Organization (https://ilostat.ilo.org). ILO datasets "
    f"and their metadata are licensed under CC BY 4.0 ({RIGHTS_URL}): any use, commercial "
    "included, with credit to the ILO and an indication of changes."
)
LICENCE_FR = (
    "Source : ILOSTAT, Organisation internationale du Travail (https://ilostat.ilo.org). Les "
    "jeux de données de l'OIT et leurs métadonnées sont sous licence CC BY 4.0 "
    f"({RIGHTS_URL}, en anglais) : toute utilisation, y compris commerciale, en citant l'OIT "
    "et en indiquant les modifications."
)

# The ILO publishes no rate limit for its SDMX API (sdmx.ilo.org sits behind
# Cloudflare). Requests are spaced at most one a second and every answer is
# cached, so the hosted server stays a light user.
RATE_LIMIT_SOURCE = "ilo"
RATE_LIMIT_PER_SECOND = 1.0
RATE_LIMIT_CAPACITY = 3.0

LIMITS = (
    "The ILO publishes no rate limit for its SDMX API; this server spaces requests (one a "
    "second at most) and caches answers (data 12 h, structures and the dataset list 24 h)."
)
LIMITS_FR = (
    "L'OIT ne publie pas de limite de débit pour son API SDMX ; ce serveur espace les requêtes "
    "(une par seconde au plus) et garde les réponses en cache (données 12 h, structures et "
    "liste des jeux 24 h)."
)

CATALOGUE_TIMEOUT_SECONDS = 120.0
STRUCTURE_TIMEOUT_SECONDS = 60.0
DATA_TIMEOUT_SECONDS = 90.0

CACHE_TTL_CATALOGUE_SECONDS = 24 * 60 * 60
CACHE_TTL_STRUCTURE_SECONDS = 24 * 60 * 60
CACHE_TTL_DATA_SECONDS = 12 * 60 * 60

MAX_SEARCH_RESULTS = 50
MAX_DESCRIPTION_CHARS = 400
MAX_CODES_PER_DIMENSION = 300
MAX_SERIES = 200
MAX_ROWS = 10_000
MAX_LAST_N = 1_000
MAX_KEY_BOUND = 1_000_000

CANADA = "CAN"
G7 = ("CAN", "USA", "GBR", "FRA", "DEU", "ITA", "JPN")

# Common two-letter codes, so "US" or "UK" work beside the ISO 3 codes ILOSTAT uses.
ISO2_TO_ISO3: dict[str, str] = {
    "AU": "AUS", "AT": "AUT", "BE": "BEL", "BR": "BRA", "CA": "CAN", "CH": "CHE", "CL": "CHL",
    "CN": "CHN", "CO": "COL", "DE": "DEU", "DK": "DNK", "ES": "ESP", "FI": "FIN", "FR": "FRA",
    "GB": "GBR", "UK": "GBR", "IE": "IRL", "IN": "IND", "IT": "ITA", "JP": "JPN", "KR": "KOR",
    "MX": "MEX", "NL": "NLD", "NO": "NOR", "NZ": "NZL", "PT": "PRT", "SE": "SWE", "US": "USA",
}  # fmt: skip

# ILOSTAT's regional and income aggregates are X codes (X01 World, X88 G7,
# X92 European Union 27, X34 Northern America); they are compared but never
# ranked against countries.
GROUP_ALIASES: dict[str, tuple[str, ...]] = {
    "G7": G7,
    "WORLD": ("X01",),
    "EU": ("X92",),
    "EU27": ("X92",),
}

FREQUENCIES = {"annual": "A", "quarterly": "Q", "monthly": "M"}


@dataclass(frozen=True)
class Indicator:
    """A preset series for ilo_compare_countries. `key` has `{area}`, `{freq}`
    and, where the dataset has a SEX dimension, `{sex}`, in key order."""

    dataflow: str
    key: str
    label_en: str
    label_fr: str
    frequencies: tuple[str, ...] = ("A",)
    has_sex: bool = True
    modelled: bool = False
    # The ILO labels PPP amounts only "Currency".
    unit_en: str | None = None
    unit_fr: str | None = None


# Every key checked live on 2026-11-08 for Canada (scripts/smoke_test_ilo.py
# runs each against the G7).
INDICATORS: dict[str, Indicator] = {
    "unemployment_rate": Indicator(
        "DF_UNE_DEAP_SEX_AGE_RT",
        "{area}.{freq}.UNE_DEAP_RT.{sex}.AGE_YTHADULT_YGE15",
        "Unemployment rate, ages 15 and over (per cent of the labour force)",
        "Taux de chômage, 15 ans et plus (% de la population active)",
        ("A", "Q", "M"),
    ),
    "youth_unemployment_rate": Indicator(
        "DF_UNE_DEAP_SEX_AGE_RT",
        "{area}.{freq}.UNE_DEAP_RT.{sex}.AGE_YTHADULT_Y15-24",
        "Youth unemployment rate, ages 15 to 24 (per cent of the labour force)",
        "Taux de chômage des jeunes, 15 à 24 ans (% de la population active)",
        ("A", "Q", "M"),
    ),
    "labour_force_participation_rate": Indicator(
        "DF_EAP_DWAP_SEX_AGE_RT",
        "{area}.{freq}.EAP_DWAP_RT.{sex}.AGE_YTHADULT_YGE15",
        "Labour force participation rate, ages 15 and over (per cent of the population)",
        "Taux d'activité, 15 ans et plus (% de la population)",
        ("A", "Q", "M"),
    ),
    "employment_to_population_ratio": Indicator(
        "DF_EMP_DWAP_SEX_AGE_RT",
        "{area}.{freq}.EMP_DWAP_RT.{sex}.AGE_YTHADULT_YGE15",
        "Employment-to-population ratio, ages 15 and over (per cent)",
        "Taux d'emploi, 15 ans et plus (% de la population)",
        ("A", "Q", "M"),
    ),
    "labour_underutilisation_lu3": Indicator(
        "DF_LUU_XLU3_SEX_AGE_RT",
        "{area}.{freq}.LUU_XLU3_RT.{sex}.AGE_YTHADULT_YGE15",
        "LU3: combined rate of unemployment and potential labour force, ages 15 and over "
        "(per cent of the extended labour force)",
        "LU3 : taux combiné de chômage et de main-d'œuvre potentielle, 15 ans et plus (% de la "
        "main-d'œuvre élargie)",
        ("A", "Q", "M"),
    ),
    "neet_rate": Indicator(
        "DF_EIP_NEET_SEX_RT",
        "{area}.{freq}.EIP_NEET_RT.{sex}",
        "Share of youth not in employment, education or training (NEET), ages 15 to 24 (per cent)",
        "Proportion de jeunes sans emploi, ni études, ni formation (NEET), 15 à 24 ans (%)",
        ("A", "Q"),
    ),
    "weekly_hours_worked": Indicator(
        "DF_HOW_TEMP_SEX_NB",
        "{area}.{freq}.HOW_TEMP_NB.{sex}",
        "Average weekly hours actually worked per employed person (hours)",
        "Heures hebdomadaires effectivement travaillées par personne occupée, moyenne (heures)",
        ("A", "Q", "M"),
    ),
    "temporary_employees_share": Indicator(
        "DF_EES_XTMP_SEX_RT",
        "{area}.{freq}.EES_XTMP_RT.{sex}",
        "Share of temporary employees (per cent of employees)",
        "Proportion de salariés temporaires (% des salariés)",
    ),
    "average_monthly_earnings_ppp": Indicator(
        "DF_EAR_EMTA_SEX_CUR_NB",
        "{area}.{freq}.EAR_EMTA_NB.{sex}.CUR_TYPE_PPP",
        "Average monthly earnings of employees (2021 PPP dollars)",
        "Gains mensuels moyens des salariés (dollars PPA de 2021)",
        unit_en="2021 PPP dollars a month",
        unit_fr="Dollars PPA de 2021 par mois",
    ),
    "minimum_wage_ppp": Indicator(
        "DF_EAR_INEE_CUR_NB",
        "{area}.{freq}.EAR_INEE_NB.CUR_TYPE_PPP",
        "Monthly minimum wage (2021 PPP dollars)",
        "Salaire minimum mensuel (dollars PPA de 2021)",
        has_sex=False,
        unit_en="2021 PPP dollars a month",
        unit_fr="Dollars PPA de 2021 par mois",
    ),
    "unemployment_rate_modelled": Indicator(
        "DF_UNE_2EAP_SEX_AGE_RT",
        "{area}.{freq}.UNE_2EAP_RT.{sex}.AGE_YTHADULT_YGE15",
        "Unemployment rate, ILO modelled estimates and projections, ages 15 and over (per cent)",
        "Taux de chômage, estimations modélisées et projections de l'OIT, 15 ans et plus (%)",
        modelled=True,
    ),
    "labour_income_share": Indicator(
        "DF_LAP_2GDP_NOC_RT",
        "{area}.{freq}.LAP_2GDP_RT",
        "Labour income share, ILO modelled estimates (per cent of GDP)",
        "Part du revenu du travail, estimations modélisées de l'OIT (% du PIB)",
        has_sex=False,
        modelled=True,
    ),
    "output_per_hour_worked": Indicator(
        "DF_GDP_2HRW_NOC_NB",
        "{area}.{freq}.GDP_2HRW_NB",
        "Output per hour worked, ILO modelled estimates (GDP, constant 2021 international "
        "dollars at PPP)",
        "Production par heure travaillée, estimations modélisées de l'OIT (PIB, dollars "
        "internationaux constants de 2021 en PPA)",
        has_sex=False,
        modelled=True,
    ),
}

SEXES = {"total": "SEX_T", "male": "SEX_M", "female": "SEX_F"}
