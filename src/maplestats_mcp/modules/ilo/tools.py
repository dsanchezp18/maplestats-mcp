"""MCP tools for ILOSTAT, the International Labour Organization's statistics.

ilo_compare_countries is the Canada-centred entry point: preset labour
indicators harmonised to international definitions, Canada always first.
ilo_search_datasets, ilo_describe_dataset and ilo_get_data reach any of
ILOSTAT's datasets by SDMX key. Names, descriptions and code labels come in
French with lang="fr".
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.ilo import client
from maplestats_mcp.modules.ilo.schemas import (
    ComparisonResult,
    DataResult,
    DatasetSearch,
    DatasetStructure,
)

Lang = Literal["en", "fr"]
IndicatorName = Literal[
    "unemployment_rate",
    "youth_unemployment_rate",
    "labour_force_participation_rate",
    "employment_to_population_ratio",
    "labour_underutilisation_lu3",
    "neet_rate",
    "weekly_hours_worked",
    "temporary_employees_share",
    "average_monthly_earnings_ppp",
    "minimum_wage_ppp",
    "unemployment_rate_modelled",
    "labour_income_share",
    "output_per_hour_worked",
]


@tool
async def ilo_compare_countries(
    indicator: IndicatorName,
    compare_with: list[str] | None = None,
    sex: Literal["total", "male", "female"] = "total",
    frequency: Literal["annual", "quarterly", "monthly"] = "annual",
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> ComparisonResult:
    """Compare Canada's labour market with other countries on ILOSTAT (ILO) indicators.

    Use for: how Canada compares internationally on labour statistics the
    International Labour Organization harmonises: unemployment rate,
    youth unemployment, labour force participation, employment-to-
    population ratio, labour underutilisation (LU3), NEET rate, weekly
    hours worked, share of temporary employees, monthly earnings and the
    statutory minimum in PPP dollars, and ILO modelled estimates
    (unemployment projections, labour income share, output per hour
    worked). `compare_with` takes "G7", "WORLD", "EU27" or ISO 3 codes
    ("USA", "GBR", "AUS", "MEX"; "US", "UK" also work). `sex` splits
    by sex; `frequency` is annual, or quarterly/monthly for survey series
    (not seasonally adjusted). The result ranks Canada (1 = highest) and
    gives the ILO citation. Statistics Canada's Labour Force Survey is
    better for Canada's own latest monthly figures.
    Keywords: ILO, ILOSTAT, International Labour Organization,
    international comparison, unemployment rate, labour force
    participation, employment rate, youth unemployment, NEET, hours
    worked, earnings, labour income share, G7 countries.
    Mots-clés : OIT, BIT, ILOSTAT, Organisation internationale du
    Travail, comparaison internationale, chômage comparé entre pays,
    activité, emploi, jeunes, heures travaillées, salaire minimum,
    gains, part du revenu du travail, pays du G7.
    """
    return await client.compare_countries(
        indicator,
        compare_with=compare_with,
        sex=sex,
        frequency=frequency,
        start_period=start_period,
        end_period=end_period,
        last_n=last_n,
        lang=lang,
    )


@tool
async def ilo_search_datasets(query: str, limit: int = 10, lang: Lang = "en") -> DatasetSearch:
    """Search ILOSTAT's labour statistics datasets (ILO) by keyword.

    Use for: finding which ILOSTAT dataset holds a labour series before
    describing and fetching it: unemployment, employment by industry or
    occupation, informal employment, earnings, hours, labour income,
    working poverty, child labour, occupational injuries, labour
    inspection, strikes, ILO modelled estimates. `query` is English, or
    French with lang="fr" (names are searched in that language). Each
    result has the dataset id for ilo_describe_dataset and ilo_get_data,
    and says whether it is an ILO modelled estimate.
    Keywords: ILO, ILOSTAT, labour statistics, datasets, dataflows,
    SDMX, search, catalogue, international labour data, employment
    statistics.
    Mots-clés : OIT, ILOSTAT, statistiques du travail, jeux de données,
    flux SDMX, recherche, catalogue, données internationales sur le
    travail, statistiques de l'emploi.
    """
    return await client.search_datasets(query, limit=limit, lang=lang)


@tool
async def ilo_describe_dataset(dataset: str, lang: Lang = "en") -> DatasetStructure:
    """Describe an ILOSTAT dataset's dimensions and codes, to build a series key.

    Use for: the order of an ILOSTAT (ILO) dataset's key dimensions and
    the codes that have data in each (countries, frequency, measure, sex,
    age bands, economic activity, currency), before calling ilo_get_data;
    also when it was last updated and how to cite it. `dataset` is an id
    from ilo_search_datasets (e.g. DF_UNE_DEAP_SEX_AGE_RT). The result
    gives a key template and an example key for Canada.
    Keywords: ILO, ILOSTAT, dataset structure, dimensions, code list,
    series key, SDMX key, age bands, classification codes, metadata.
    Mots-clés : OIT, ILOSTAT, structure du jeu de données, dimensions,
    liste de codes, clé de série, clé SDMX, tranches d'âge,
    nomenclatures, métadonnées.
    """
    return await client.describe_dataset(dataset, lang=lang)


@tool
async def ilo_get_data(
    dataset: str,
    key: str,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> DataResult:
    """Get ILOSTAT (ILO) labour data by dataset and SDMX key, as tidy rows.

    Use for: any ILOSTAT series beyond the preset comparisons: by age
    band, education, economic activity, occupation, status in employment,
    informality, earnings by industry, for any country. `key` has one
    part per dimension in the order ilo_describe_dataset gives, codes
    joined by `+`, an empty part for all (e.g.
    `CAN+USA.A.UNE_DEAP_RT.SEX_T.AGE_YTHADULT_Y15-24`). Periods are SDMX
    (`2020`, `2020-Q1`, `2020-M01` or `2020-01`); `last_n` keeps the
    last N per series. Each row has the country, period, value, unit and
    frequency; each series names its national source survey.
    Keywords: ILO, ILOSTAT, labour data, time series, SDMX key,
    international data, country comparison, labour market statistics,
    tidy data, CSV download.
    Mots-clés : OIT, ILOSTAT, données sur le travail, séries
    chronologiques, clé SDMX, données internationales, comparaison
    entre pays, marché du travail, téléchargement CSV.
    """
    return await client.get_data(
        dataset,
        key,
        start_period=start_period,
        end_period=end_period,
        last_n=last_n,
        lang=lang,
    )
