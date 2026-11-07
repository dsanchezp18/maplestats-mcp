"""MCP tools for the OECD Data Explorer.

oecd_compare_countries is the Canada-centred entry point: preset indicators
(Economic Outlook projections, productivity, unit labour costs, PPPs, tax
revenue, house prices, leading indicators), Canada always first.
oecd_search_datasets, oecd_describe_dataset and oecd_get_data reach any
series of the OECD's dataflows by SDMX key. Code labels come in French where
the OECD has them; dataset names and descriptions are English only.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.oecd import client
from maplestats_mcp.modules.oecd.schemas import (
    ComparisonResult,
    DataResult,
    DatasetSearch,
    DatasetStructure,
)

Lang = Literal["en", "fr"]
IndicatorName = Literal[
    "real_gdp_growth",
    "inflation",
    "unemployment_rate",
    "government_balance",
    "government_debt",
    "current_account",
    "gdp_per_hour_worked",
    "labour_productivity_growth",
    "gdp_per_capita",
    "unit_labour_cost_growth",
    "ppp_gdp",
    "tax_to_gdp",
    "real_house_price_index",
    "house_price_to_income",
    "house_price_to_rent",
    "composite_leading_indicator",
]


@tool
async def oecd_compare_countries(
    indicator: IndicatorName,
    compare_with: list[str] | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> ComparisonResult:
    """Compare Canada with the G7 or other OECD countries on an OECD indicator.

    Use for: how Canada compares with peers on OECD Economic Outlook
    projections (real GDP growth, inflation, unemployment, government
    balance and debt, current account), labour productivity (GDP per hour
    worked, productivity growth), GDP per capita, unit labour costs,
    purchasing power parities, tax-to-GDP ratio (Revenue Statistics),
    real house prices, price-to-income and price-to-rent ratios, and the
    composite leading indicator. `compare_with` takes "G7" or OECD codes
    ("USA", "GBR", "AUS", "OECD"; "US" also works). Periods are SDMX
    (`2020`, `2020-Q1`, `2020-01`); without them the recent years come
    back, Economic Outlook projections included. The result gives
    Canada's rank (1 = highest) and the citation the OECD asks for.
    StatCan and the Bank of Canada are better for Canada's own latest
    figures.
    Keywords: OECD, international comparison, peer countries, G7,
    economic outlook, projections, forecast, productivity, unit labour
    costs, purchasing power parity, tax-to-GDP, house prices, leading
    indicator.
    Mots-clés : OCDE, comparaison internationale, pays comparables, G7,
    perspectives économiques, projections, prévisions, productivité du
    travail, coûts unitaires de main-d'œuvre, parité de pouvoir d'achat,
    recettes fiscales, prix des logements, indicateur avancé.
    """
    return await client.compare_countries(
        indicator,
        compare_with=compare_with,
        start_period=start_period,
        end_period=end_period,
        last_n=last_n,
        lang=lang,
    )


@tool
async def oecd_search_datasets(query: str, limit: int = 10, lang: Lang = "en") -> DatasetSearch:
    """Search the OECD Data Explorer's datasets (dataflows) by keyword.

    Use for: finding which OECD dataset holds a series before describing
    and fetching it: Economic Outlook, productivity, unit labour costs,
    PPPs, Revenue Statistics, house prices, leading indicators, national
    accounts, labour force, education, health, environment, trade
    in value added. `query` is English (the OECD names datasets in English
    only), e.g. "tax revenue", "health expenditure", "pensions". Each
    result has the dataset id to pass to oecd_describe_dataset and
    oecd_get_data, and a Data Explorer link.
    Keywords: OECD, Data Explorer, datasets, dataflows, SDMX, OECD.Stat,
    search, statistics catalogue, international statistics, OECD
    databases.
    Mots-clés : OCDE, Explorateur de données, jeux de données, flux SDMX,
    recherche, catalogue statistique, statistiques internationales, bases
    de données de l'OCDE, OCDE.Stat.
    """
    return await client.search_datasets(query, limit=limit, lang=lang)


@tool
async def oecd_describe_dataset(dataset: str, lang: Lang = "en") -> DatasetStructure:
    """Describe an OECD dataset's dimensions and codes, to build a series key.

    Use for: the order of an OECD dataset's key dimensions and the codes
    that have data in each (countries, measures, units, frequencies),
    before calling oecd_get_data; also when the dataset was last updated,
    how many observations it has, and how to cite it. `dataset` is an id
    from oecd_search_datasets (e.g. DSD_EO@DF_EO). The result gives a key
    template and an example key for Canada.
    Keywords: OECD, dataset structure, dimensions, code list, series key,
    SDMX key, data structure definition, DSD, country codes, metadata,
    last updated.
    Mots-clés : OCDE, structure du jeu de données, dimensions, liste de
    codes, clé de série, clé SDMX, définition de structure, codes de
    pays, métadonnées, mise à jour.
    """
    return await client.describe_dataset(dataset, lang=lang)


@tool
async def oecd_get_data(
    dataset: str,
    key: str,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> DataResult:
    """Get OECD data by dataset and SDMX key, as tidy rows.

    Use for: any OECD series beyond the preset comparisons: Economic
    Outlook measures (DSD_EO@DF_EO, e.g. `CAN+USA.GDPV_ANNPCT.A`),
    productivity by industry, PPPs and price levels, tax revenue by tax
    type, labour, health, education. `key` has one part per
    dimension in the order oecd_describe_dataset gives, codes joined by
    `+`, an empty part for all. Periods are SDMX (`2020`, `2020-Q1`,
    `2020-01`); `last_n` keeps the last N per series. Each row has the
    country, period, value, unit and frequency; csv_url opens the same
    query as CSV. Each query spends one of the OECD's hourly downloads.
    Keywords: OECD, time series, SDMX key, international data, country
    comparison, economic statistics, projections, tidy data, CSV
    download, OECD.Stat.
    Mots-clés : OCDE, séries chronologiques, clé SDMX, données
    internationales, comparaison entre pays, statistiques économiques,
    projections, téléchargement CSV, OCDE.Stat.
    """
    return await client.get_data(
        dataset,
        key,
        start_period=start_period,
        end_period=end_period,
        last_n=last_n,
        lang=lang,
    )
