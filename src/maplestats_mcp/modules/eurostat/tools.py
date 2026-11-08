"""MCP tools for Eurostat: the EU, the euro area and member states as comparators."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.eurostat import client
from maplestats_mcp.modules.eurostat.schemas import (
    Comparison,
    DataResult,
    DatasetSearch,
    DatasetStructure,
)

Lang = Literal["en", "fr"]
IndicatorName = Literal[
    "gdp_growth_quarterly",
    "gdp_growth_year_on_year",
    "gdp_growth_annual",
    "gdp_per_capita_pps",
    "hicp_inflation",
    "unemployment_rate",
    "employment_rate",
    "house_price_growth",
    "government_debt_to_gdp",
    "government_deficit_to_gdp",
    "exports_to_gdp",
    "imports_to_gdp",
]


@tool
async def eurostat_compare(
    indicator: IndicatorName,
    geo: list[str] | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> Comparison:
    """Compare the EU, the euro area and European countries on a headline indicator.

    Use for: EU or euro area GDP growth, HICP inflation, unemployment rate,
    employment rate, house price growth, government debt or deficit as a
    share of GDP, exports or imports as a share of GDP, beside Germany,
    France, Italy, Spain or any member state, to compare with Canada.
    `geo` takes EU27, EURO_AREA, EU_MEMBERS, EURO_AREA_MEMBERS, BIG_FOUR,
    country names or codes (DE, FR, EL for Greece); the default is EU27,
    euro area and the four largest economies. Status flags (provisional,
    estimated, break in series) are decoded. canada_counterpart names the
    Canadian series to pair with: Canada is not in Eurostat.
    Keywords: Eurostat, European Union, euro area, eurozone, EU comparison,
    HICP inflation, unemployment rate Europe, GDP growth EU, government
    debt Maastricht, house prices Europe, Germany, France.
    Mots-clés : Eurostat, Union européenne, zone euro, comparaison
    européenne, inflation IPCH, taux de chômage en Europe, croissance du
    PIB de l'UE, dette publique, prix des logements en Europe, Allemagne,
    France.
    """
    return await client.compare(
        indicator, geo=geo, start_period=start_period, end_period=end_period,
        last_n=last_n, lang=lang,
    )  # fmt: skip


@tool
async def eurostat_search_datasets(
    query: str,
    dataset_type: Literal["dataset", "table"] | None = None,
    limit: int = 10,
    lang: Lang = "en",
) -> DatasetSearch:
    """Search Eurostat's datasets and tables by title words or code.

    Use for: finding the Eurostat dataset code for an EU statistic (labour
    market, prices, national accounts, trade, government finance,
    population, energy) before describing and fetching it. Each hit gives
    its last update and data coverage; an old data_end means discontinued.
    Keywords: Eurostat, EU datasets, European statistics, table of
    contents, dataset code, database, find data, EU indicators, euro area
    statistics, catalogue.
    Mots-clés : Eurostat, jeux de données de l'UE, statistiques
    européennes, table des matières, code de jeu, base de données, trouver
    des données, indicateurs de l'UE, catalogue.
    """
    return await client.search_datasets(query, dataset_type=dataset_type, limit=limit, lang=lang)


@tool
async def eurostat_describe_dataset(dataset: str, lang: Lang = "en") -> DatasetStructure:
    """Describe a Eurostat dataset's dimensions, codes and status flags.

    Use for: the dimensions (geo, unit, na_item, s_adj...) and the codes
    with data of a Eurostat dataset, before eurostat_get_data, plus the
    meaning of its flags (p provisional, e estimated, b break in series).
    Keywords: Eurostat, dataset structure, dimensions, code list, filters,
    geo codes, units, metadata, status flags, DSD.
    Mots-clés : Eurostat, structure du jeu, dimensions, liste de codes,
    filtres, codes géographiques, unités, métadonnées, indicateurs de
    statut.
    """
    return await client.describe_dataset(dataset, lang=lang)


@tool
async def eurostat_get_data(
    dataset: str,
    filters: dict[str, list[str]] | None = None,
    geo: list[str] | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> DataResult:
    """Get Eurostat data as tidy rows (geo, time, unit, value, flag).

    Use for: any Eurostat series by dataset code, filtered by dimension
    codes (e.g. namq_10_gdp with {"unit": ["CLV_PCH_PRE"], "s_adj":
    ["SCA"], "na_item": ["B1GQ"]}) and `geo` (EU27, EURO_AREA, EU_MEMBERS,
    country names or codes). Periods: 2020, 2020-Q1, 2020-01; without
    them, the last 12 periods. Flags are decoded on each row.
    Keywords: Eurostat, EU data, time series, JSON-stat, member states,
    euro area, regional data, statistics download, tidy data, flags.
    Mots-clés : Eurostat, données de l'UE, séries chronologiques, États
    membres, zone euro, données régionales, téléchargement, indicateurs de
    statut.
    """
    return await client.get_data(
        dataset, filters=filters, geo=geo, start_period=start_period,
        end_period=end_period, last_n=last_n, lang=lang,
    )  # fmt: skip
