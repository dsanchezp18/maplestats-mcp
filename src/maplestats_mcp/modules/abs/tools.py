"""MCP tools for the Australian Bureau of Statistics Data API.

abs_get_indicator gives a headline Australian series with the Canadian
series to pair with; abs_search_datasets, abs_describe_dataset and
abs_get_data reach any ABS dataset by SDMX key. The ABS publishes in English
only; with lang="fr" the module's own labels, notes and pairings are French.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.abs import client
from maplestats_mcp.modules.abs.schemas import (
    DataResult,
    DatasetSearch,
    DatasetStructure,
    IndicatorResult,
)

Lang = Literal["en", "fr"]
IndicatorName = Literal[
    "cpi_inflation",
    "trimmed_mean_inflation",
    "unemployment_rate",
    "participation_rate",
    "employment_to_population_ratio",
    "gdp_quarterly_growth",
    "wage_price_index_growth",
    "population_growth",
]


@tool
async def abs_get_indicator(
    indicator: IndicatorName,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> IndicatorResult:
    """Get a headline Australian figure from the ABS, with Canada's counterpart.

    Use for: Australian comparators from the Australian Bureau of
    Statistics: CPI and trimmed-mean inflation, unemployment,
    participation and employment-to-population rates, quarterly GDP
    growth, Wage Price Index growth, population growth. Periods are
    `2026`, `2026-Q3` or `2026-09`; without them the recent values come
    back. The result names the Statistics Canada table to pair with and
    how the measures differ, and gives the ABS citation.
    Keywords: Australia, Australian, ABS, Australian Bureau of
    Statistics, Australian inflation, trimmed mean, Australian
    unemployment, WPI, comparator.
    Mots-clés : Australie, australien, ABS, inflation australienne,
    moyenne tronquée, chômage en Australie, indice des prix des
    salaires, point de comparaison.
    """
    return await client.get_indicator(
        indicator, start_period=start_period, end_period=end_period, last_n=last_n, lang=lang
    )


@tool
async def abs_search_datasets(query: str, limit: int = 10, lang: Lang = "en") -> DatasetSearch:
    """Search the Australian Bureau of Statistics' datasets (ABS Data API) by keyword.

    Use for: finding which ABS dataset holds an Australian series before
    describing and fetching it: consumer prices, labour force, national
    accounts, wages, population, building approvals, trade, household
    spending. `query` is English (the ABS publishes in English only).
    Each result has the dataset id for abs_describe_dataset and
    abs_get_data.
    Keywords: Australia, ABS, Australian Bureau of Statistics, datasets,
    dataflows, SDMX, search, catalogue, Australian statistics.
    Mots-clés : Australie, ABS, jeux de données australiens, flux SDMX,
    recherche, catalogue, statistiques australiennes, bureau australien
    de la statistique.
    """
    return await client.search_datasets(query, limit=limit, lang=lang)


@tool
async def abs_describe_dataset(dataset: str, lang: Lang = "en") -> DatasetStructure:
    """Describe an ABS (Australian) dataset's dimensions and codes, to build a key.

    Use for: the order of an Australian Bureau of Statistics dataset's
    key dimensions and the codes that have data in each (measure, index
    or data item, adjustment type, region, frequency), before calling
    abs_get_data. `dataset` is an id from abs_search_datasets (e.g. CPI,
    LF, ANA_AGG). The result gives a key template and an example key for
    Australia.
    Keywords: Australia, ABS, dataset structure, dimensions, code list,
    series key, SDMX key, Australian statistics, metadata.
    Mots-clés : Australie, ABS, structure du jeu de données, dimensions,
    liste de codes, clé de série, clé SDMX, métadonnées.
    """
    return await client.describe_dataset(dataset, lang=lang)


@tool
async def abs_get_data(
    dataset: str,
    key: str,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> DataResult:
    """Get Australian Bureau of Statistics data by dataset and SDMX key, as tidy rows.

    Use for: any ABS series beyond the presets: CPI groups and capital
    cities, labour force by state and sex, national accounts aggregates,
    pay indices by industry, population by state. `key` has one part per
    dimension in the order abs_describe_dataset gives, codes joined by
    `+`, an empty part for all (e.g. `M13.3.1599.20.1+2+AUS.M` for
    unemployment in NSW, Victoria and Australia). Periods are SDMX
    (`2020`, `2020-Q1`, `2020-01`); `last_n` keeps the last N per
    series. Each series names its adjustment type and unit.
    Keywords: Australia, ABS, Australian data, time series, SDMX key,
    states and territories, tidy data, CSV download.
    Mots-clés : Australie, ABS, données australiennes, séries
    chronologiques, clé SDMX, États et territoires, téléchargement CSV,
    statistiques australiennes.
    """
    return await client.get_data(
        dataset,
        key,
        start_period=start_period,
        end_period=end_period,
        last_n=last_n,
        lang=lang,
    )
