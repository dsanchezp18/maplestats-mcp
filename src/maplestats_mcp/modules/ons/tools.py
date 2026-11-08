"""MCP tools for the UK Office for National Statistics' time series.

ons_get_indicator gives a headline UK series with the Canadian series to
pair with; ons_search_series and ons_get_series reach any ONS time series
by its id (CDID). The ONS publishes in English only; with lang="fr" the
module's own labels, notes and Canadian pairings are French.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.ons import client
from maplestats_mcp.modules.ons.schemas import IndicatorResult, SeriesResult, SeriesSearch

Lang = Literal["en", "fr"]
IndicatorName = Literal[
    "cpi_inflation",
    "cpih_inflation",
    "core_cpi_inflation",
    "rpi_inflation",
    "gdp_quarterly_growth",
    "gdp_annual_growth",
    "monthly_gdp_growth",
    "unemployment_rate",
    "employment_rate",
    "inactivity_rate",
    "regular_pay_growth",
    "total_pay_growth",
    "vacancies",
    "public_sector_net_debt",
    "retail_sales_volume",
]


@tool
async def ons_get_indicator(
    indicator: IndicatorName,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> IndicatorResult:
    """Get a headline United Kingdom figure from the ONS, with Canada's counterpart.

    Use for: UK comparators from the Office for National Statistics: CPI,
    CPIH, core CPI and RPI inflation, UK GDP growth, unemployment,
    employment and inactivity rates, regular and
    total pay growth, job vacancies, public sector net debt (% of GDP),
    retail sales volume. Periods are `2026`, `2026-Q3` or `2026-09`;
    without them the recent values come back. The result names the
    Statistics Canada table to pair with and how the definitions differ,
    the next release date and the ONS citation.
    Keywords: United Kingdom, UK, Britain, ONS, Office for National
    Statistics, UK inflation, CPIH, UK GDP, UK unemployment, UK pay,
    comparator.
    Mots-clés : Royaume-Uni, britannique, Grande-Bretagne, ONS, inflation
    britannique, PIB britannique, chômage au Royaume-Uni, salaires
    britanniques, point de comparaison.
    """
    return await client.get_indicator(
        indicator, start_period=start_period, end_period=end_period, last_n=last_n, lang=lang
    )


@tool
async def ons_search_series(
    query: str, dataset: str | None = None, limit: int = 10, lang: Lang = "en"
) -> SeriesSearch:
    """Search the UK Office for National Statistics' time series by keyword.

    Use for: finding the ONS series id (CDID, e.g. D7G7) of a UK
    statistic before fetching it: price indices and their components,
    labour market, earnings, GDP and its components, trade, public
    finances, retail sales, productivity. `query` is English (the ONS
    publishes in English only); `dataset` narrows to one ONS dataset
    (MM23 consumer prices, LMS labour market, QNA quarterly national
    accounts, PUSF public finances). Each result has the series id and
    dataset to pass to ons_get_series.
    Keywords: ONS, Office for National Statistics, United Kingdom, UK
    time series, CDID, series id, search, British statistics.
    Mots-clés : ONS, Royaume-Uni, séries chronologiques britanniques,
    identifiant de série, CDID, recherche, statistiques britanniques,
    Grande-Bretagne.
    """
    return await client.search_series(query, dataset=dataset, limit=limit, lang=lang)


@tool
async def ons_get_series(
    series_id: str,
    dataset: str | None = None,
    frequency: Literal["monthly", "quarterly", "annual"] | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> SeriesResult:
    """Get any UK ONS time series by its id (CDID), as tidy observations.

    Use for: a UK series beyond the presets, by its four-character ONS
    id from ons_search_series (e.g. D7G7 CPI annual rate, MGSX
    unemployment rate, ABMI real GDP). `dataset` picks one when several
    ONS datasets publish the id; `frequency` picks the frequency
    (default: the most frequent published). Periods are
    `2026`, `2026-Q3` or `2026-09`; `last_n` keeps the last N. The
    result has the unit, release and next-release dates, a CSV link and
    the citation.
    Keywords: ONS, Office for National Statistics, United Kingdom, UK
    time series, CDID, series id, British statistics, CSV download.
    Mots-clés : ONS, Royaume-Uni, série chronologique britannique,
    CDID, mensuel, trimestriel, annuel, téléchargement CSV.
    """
    return await client.get_series(
        series_id,
        dataset=dataset,
        frequency=frequency,
        start_period=start_period,
        end_period=end_period,
        last_n=last_n,
        lang=lang,
    )
