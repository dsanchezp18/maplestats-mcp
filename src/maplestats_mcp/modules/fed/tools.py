"""MCP tools for the Federal Reserve Board's statistical releases.

fed_get_indicator is the Canada-centred entry point: US rates, the
Canadian dollar per US dollar, industrial production and credit, each with
the Canadian series to set beside it. fed_list_releases,
fed_describe_release, fed_search_series and fed_get_series reach any
series of the releases read. The Board publishes in English only; `lang="fr"`
gives this server's own text in French.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.fed import client
from maplestats_mcp.modules.fed.schemas import (
    ReleaseList,
    ReleaseStructure,
    SearchResult,
    SeriesData,
)

Lang = Literal["en", "fr"]
ReleaseCode = Literal[
    "H15", "PRATES", "H10", "G17", "H6", "G19", "DSR", "H8", "H41", "CP", "G20", "CHGDEL",
    "SLOOS", "SCOOS",
]  # fmt: skip
Frequency = Literal["daily", "weekly", "monthly", "quarterly", "annual"]
IndicatorName = Literal[
    "cad_per_usd",
    "cad_per_usd_monthly",
    "broad_dollar_index",
    "fed_funds_rate",
    "fed_funds_rate_monthly",
    "interest_on_reserve_balances",
    "prime_rate",
    "treasury_2y",
    "treasury_10y",
    "industrial_production",
    "manufacturing_production",
    "capacity_utilization",
    "m2_money_stock",
    "consumer_credit",
    "household_debt_service_ratio",
]


@tool
async def fed_get_indicator(
    indicator: IndicatorName,
    start_date: str | None = None,
    end_date: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> SeriesData:
    """Get a US Federal Reserve headline series to compare with Canada.

    Use for: the US federal funds rate beside the Bank of Canada's policy
    rate, US Treasury 2- and 10-year yields beside Canadian bond yields,
    the Canadian dollar per US dollar (Fed H.10 noon rate), the broad
    dollar index, the Fed's interest on reserve balances, the US prime
    rate, US industrial production and capacity utilization (G.17), M2
    money stock, US consumer credit and the household debt service ratio.
    Each result names the Canadian series to set beside it. Dates are
    `2024`, `2024-06` or `2024-06-30`; without them the latest year
    (daily) or five years (monthly) come back. Rows are tidy: date, value,
    unit, frequency, series id.
    Keywords: Federal Reserve, Fed, United States, US interest rates,
    federal funds rate, Treasury yields, USD/CAD exchange rate, industrial
    production, capacity utilization, comparison with Canada.
    Mots-clés : Réserve fédérale, Fed, États-Unis, taux d'intérêt
    américains, taux des fonds fédéraux, rendements du Trésor, taux de
    change dollar canadien dollar américain, production industrielle,
    utilisation des capacités, comparaison avec le Canada.
    """
    return await client.get_indicator(
        indicator, start_date=start_date, end_date=end_date, last_n=last_n, lang=lang
    )


@tool
async def fed_list_releases(lang: Lang = "en") -> ReleaseList:
    """List the Federal Reserve Board statistical releases this server reads.

    Use for: finding which Fed release holds a US series: H.15 selected
    interest rates, policy rates, H.10/G.5 foreign exchange rates, G.17
    industrial production, H.6 money stock, G.19 consumer credit, H.8
    commercial bank assets, H.4.1 the Fed's balance sheet, commercial
    paper, G.20 finance companies, charge-off and delinquency rates, the
    senior loan officer survey (SLOOS) and SCOOS. Each entry links the
    release page and its complete XML data file.
    Keywords: Federal Reserve Board, statistical releases, H.15, H.10, G.17,
    H.8, H.4.1, SLOOS, US data, release list.
    Mots-clés : Réserve fédérale, publications statistiques, H.15, H.10,
    G.17, bilan de la Fed, enquête auprès des responsables du crédit,
    données américaines, liste des publications.
    """
    return await client.list_releases(lang=lang)


@tool
async def fed_describe_release(release: ReleaseCode, lang: Lang = "en") -> ReleaseStructure:
    """Describe a Federal Reserve release: its groups, dimensions and codes.

    Use for: what a Fed release holds before searching it: its data
    groups (G.17's industry groups, capacity utilization, motor vehicle
    assemblies), the dimensions its series vary by (instrument, maturity,
    currency, seasonal adjustment) with the codes used, the frequencies,
    the number of series, when the file was prepared, and example series
    ids.
    Keywords: Federal Reserve, release structure, dimensions, code list,
    series groups, metadata, frequencies, data set description.
    Mots-clés : Réserve fédérale, structure de la publication, dimensions,
    liste de codes, groupes de séries, métadonnées, fréquences,
    publication statistique.
    """
    return await client.describe_release(release, lang=lang)


@tool
async def fed_search_series(
    query: str,
    release: ReleaseCode | None = None,
    frequency: Frequency | None = None,
    include_discontinued: bool = False,
    limit: int = 25,
    lang: Lang = "en",
) -> SearchResult:
    """Search Federal Reserve series by words in their descriptions.

    Use for: finding a Fed series id: a Treasury maturity, a commercial
    paper rate, a currency's exchange rate against the US dollar, an
    industry's production index, a G.19 credit category, a bank balance
    sheet item. Descriptions are English (`Treasury 5-year`, `Japan yen`,
    `motor vehicles`). Without `release` it searches H.15, policy rates,
    H.10 and G.17; name a release for the others. Each hit has its
    unit, frequency, dates covered and latest value.
    Keywords: Federal Reserve, series search, series id, find series,
    US interest rate series, exchange rate series, production index,
    credit series.
    Mots-clés : Réserve fédérale, recherche de séries, identifiant de série,
    trouver une série, séries de taux américains, séries de taux de change,
    indice de production, séries de crédit.
    """
    return await client.search_series(
        query,
        release=release,
        frequency=frequency,
        include_discontinued=include_discontinued,
        limit=limit,
        lang=lang,
    )


@tool
async def fed_get_series(
    release: ReleaseCode,
    series: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> SeriesData:
    """Get Federal Reserve series by id from one release, as tidy rows.

    Use for: any Fed series beyond the preset indicators, by the ids
    fed_search_series returns (e.g. H15 `RIFLGFCY05_N.B`, H10
    `RXI_N.M.JA`, G17 `IP.G3361T3.S`), up to 25 from one release. Dates are
    `2024`, `2024-06` or `2024-06-30`; `last_n` keeps the last N per series.
    Rows give date (period end), value, unit, frequency and series id.
    Keywords: Federal Reserve, time series, series id, US data download,
    H.15 data, H.10 data, G.17 data, tidy data.
    Mots-clés : Réserve fédérale, séries chronologiques, identifiant de
    série, données américaines, téléchargement de données, données
    ordonnées, taux d'intérêt américains, production industrielle.
    """
    return await client.get_series(
        release,
        series,
        start_date=start_date,
        end_date=end_date,
        last_n=last_n,
        lang=lang,
    )
