"""MCP tools for the US Bureau of Labor Statistics (Public Data API v2).

bls_get_indicator is the entry point for the US headline numbers a Canadian
comparison usually needs; bls_get_series takes any BLS series id;
bls_search_series and bls_list_surveys help find an id. The BLS publishes in
English; `lang="fr"` gives this server's own text (titles of known series,
notes, errors) in French.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.bls import client
from maplestats_mcp.modules.bls.schemas import (
    IndicatorResult,
    SearchResult,
    SeriesResult,
    SurveyList,
)

Lang = Literal["en", "fr"]
IndicatorName = Literal[
    "nonfarm_payrolls",
    "unemployment_rate",
    "cpi_all_items",
    "cpi_core",
    "average_hourly_earnings",
    "participation_rate",
    "job_openings",
    "ppi_final_demand",
]


@tool
async def bls_get_indicator(
    indicator: IndicatorName,
    seasonally_adjusted: bool = True,
    start_year: int | None = None,
    end_year: int | None = None,
    lang: Lang = "en",
) -> IndicatorResult:
    """Get a US headline labour or price indicator from the Bureau of Labor Statistics.

    Use for: the American side of a comparison with the United States: US
    nonfarm payrolls (monthly job gains), the US unemployment rate, US
    consumer price inflation (CPI-U all items or core, less food and
    energy), US average hourly earnings, participation rate, job openings
    (JOLTS) or producer prices. Rows carry the change from the previous
    period and the per cent change from a year earlier (12-month US
    inflation; the BLS headline uses seasonally_adjusted=False),
    preliminary flags and the release schedule. Without years the last 5
    come back. Not for Canadian figures (use StatCan's tools).
    Keywords: BLS, Bureau of Labor Statistics, United States, American,
    US jobs report, nonfarm payrolls, US unemployment rate, US CPI-U, US
    inflation, JOLTS, US hourly earnings.
    Mots-clés : BLS, États-Unis, américain, rapport sur l'emploi américain,
    emploi salarié non agricole, taux de chômage américain, IPC américain,
    inflation aux États-Unis, postes vacants américains, salaires
    américains.
    """
    return await client.get_indicator(
        indicator,
        seasonally_adjusted=seasonally_adjusted,
        start_year=start_year,
        end_year=end_year,
        lang=lang,
    )


@tool
async def bls_get_series(
    series_ids: list[str],
    start_year: int | None = None,
    end_year: int | None = None,
    lang: Lang = "en",
) -> SeriesResult:
    """Get US Bureau of Labor Statistics time series by series id.

    Use for: any BLS series beyond the headline indicators: CPI components
    (CUSR0000SAH1 shelter), state unemployment (LASST...), industry
    payrolls (CES...), import prices from Canada (EIUCOCANTOT), the
    Employment Cost Index, productivity. Takes up to 25 ids per call and a
    year range (default the last 5; at most 30 years per call, one BLS
    query per 10 years; the server shares 25 BLS queries a day). Returns tidy rows, oldest
    first, with seasonal adjustment, units, preliminary flags, change from
    the previous period, per cent change from a year earlier and the news
    release that publishes each series.
    Keywords: BLS, Bureau of Labor Statistics, series id, US time series,
    US labor statistics, US CPI components, state unemployment, US
    payrolls by industry, import price index, US data download.
    Mots-clés : BLS, identifiant de série, séries chronologiques
    américaines, statistiques du travail des États-Unis, composantes de
    l'IPC américain, chômage par État, emploi par industrie, prix à
    l'importation, données américaines.
    """
    return await client.get_series(series_ids, start_year=start_year, end_year=end_year, lang=lang)


@tool
async def bls_search_series(
    query: str = "",
    survey: str | None = None,
    lang: Lang = "en",
) -> SearchResult:
    """Find US Bureau of Labor Statistics series ids by keyword or survey.

    Use for: looking up the BLS series id for a US measure (core CPI,
    shelter inflation, U-6 unemployment, job openings, quits rate, import
    prices from Canada) before calling bls_get_series, or listing a
    survey's popular series (`survey` is a two-letter prefix from
    bls_list_surveys, e.g. CU for the CPI, LN for the household survey,
    CE for payrolls). The BLS API has no keyword search: matches come from
    MapleStats' list of headline series and the BLS's popular series.
    Keywords: BLS, series lookup, find series id, US statistics search,
    popular series, CPI series, unemployment series, JOLTS series,
    payroll series, US indicators.
    Mots-clés : BLS, recherche de série, trouver un identifiant, séries
    américaines, séries populaires, série de l'IPC, série du chômage,
    postes vacants, indicateurs des États-Unis.
    """
    return await client.search_series(query, survey=survey, lang=lang)


@tool
async def bls_list_surveys(lang: Lang = "en") -> SurveyList:
    """List the US Bureau of Labor Statistics surveys and their series-id prefixes.

    Use for: which BLS program publishes a US measure and the two-letter
    prefix its series ids start with: CU (CPI, all urban consumers), CE
    (Current Employment Statistics, payrolls), LN (Current Population
    Survey, unemployment), JT (JOLTS), WP (producer prices), EI (import
    and export prices), CI (Employment Cost Index), LA (local area
    unemployment). Pass a prefix to bls_search_series for its popular series.
    Keywords: BLS, surveys, programs, series prefix, Current Population
    Survey, Current Employment Statistics, CPI, JOLTS, US statistical
    programs, survey list.
    Mots-clés : BLS, enquêtes, programmes statistiques américains, préfixe
    de série, enquête sur la population active américaine, enquête sur
    l'emploi, IPC, postes vacants, liste des enquêtes.
    """
    return await client.list_surveys(lang=lang)
