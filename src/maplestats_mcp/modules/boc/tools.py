"""MCP tools for the Bank of Canada Valet API.

Every tool returns a typed Pydantic model (see schemas.py) - FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.

`lang` is accepted on every tool for consistency with the rest of this
project, but Valet itself has no language query parameter - every field
this module reads back (label/description) is already in whichever
language the series/group was authored in (mostly English, with some
French-only or bilingual entries), so `lang` has no effect on the
Valet request itself. It is kept purely so a caller/BM25 query
mentioning "fr" doesn't rule this module out.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.boc import client, constants
from maplestats_mcp.modules.boc.schemas import (
    GroupDetail,
    GroupList,
    GroupObservationsResult,
    ObservationsResult,
    SeriesDetail,
    SeriesList,
)

Lang = Literal["en", "fr"]


@tool
async def boc_search_series(
    query: str | None = None, limit: int | None = None, lang: Lang = "en"
) -> SeriesList:
    """Search or list Bank of Canada Valet's ~16,000 statistical series.

    Use for: finding a Valet series name when you only know a topic -
    exchange rates, interest rates (policy rate, prime rate), CPI/
    inflation measures, commodity prices, and hundreds of other
    monetary/financial series. Pass `query` for a keyword search (top
    `limit` matches, default 25, max 200). Omit `query` to page through
    the catalogue in name order (`limit` default 50, max 1000);
    `total_count` is the full number and provenance.limits says what was
    cut.
    Keywords: bank of canada, boc, valet, series, search, find, exchange
    rate, interest rate, policy rate, prime rate, five-year mortgage
    rate, bond yield, cpi, inflation, commodity price, discover, list,
    inventory, all series, catalogue, full list.
    Mots-clés : banque du canada, valet, série, recherche, trouver, taux
    de change, taux d'intérêt, taux directeur, taux préférentiel, taux
    hypothécaire, rendement des obligations, IPC, inflation, prix des
    matières premières, découvrir, liste, inventaire, toutes les séries,
    catalogue, liste complète, parcourir.
    """
    if query is not None:
        return await client.search_series(
            query, limit=constants.SEARCH_LIMIT_DEFAULT if limit is None else limit
        )
    # page_series copies, so the cached full list is not trimmed in place.
    return client.page_series(
        await client.list_series(), constants.LIST_LIMIT_DEFAULT if limit is None else limit
    )


@tool
async def boc_search_groups(
    query: str | None = None, limit: int | None = None, lang: Lang = "en"
) -> GroupList:
    """Search or list Bank of Canada Valet's series groups (~2,500).

    Use for: finding a themed group of related series (e.g. daily
    exchange rates, the CPI family including CPI-trim/median/common,
    weekly/monthly/annual commodity price indexes) when you want several
    related series at once rather than one series name. Pass `query`
    for a keyword search (top `limit` matches, default 25, max 200). Omit
    `query` to page through the groups (`limit` default 50, max 1000).
    Keywords: bank of canada, boc, valet, group, series group, search,
    find, cpi, exchange rates, commodity prices, discover, list, groups,
    inventory, catalogue, full list.
    Mots-clés : banque du canada, valet, groupe, groupe de séries,
    recherche, trouver, IPC, taux de change, prix des produits de base,
    découvrir, liste, groupes, inventaire, catalogue, liste complète,
    parcourir.
    """
    if query is not None:
        return await client.search_groups(
            query, limit=constants.SEARCH_LIMIT_DEFAULT if limit is None else limit
        )
    return client.page_groups(
        await client.list_groups(), constants.LIST_LIMIT_DEFAULT if limit is None else limit
    )


@tool
async def boc_get_series(name: str, lang: Lang = "en") -> SeriesDetail:
    """Get the label and description for one Bank of Canada Valet series.

    Use for: confirming what a series code actually measures before
    requesting its observations, e.g. FXUSDCAD (USD/CAD daily exchange
    rate), V39079 (target for the overnight rate / policy rate),
    V80691311 (prime rate), V41690973 (Total CPI).
    Keywords: bank of canada, boc, valet, series, detail, metadata,
    description, label, lookup.
    Mots-clés : banque du canada, valet, série, détail, métadonnées,
    description, étiquette, recherche par code, consulter.
    """
    return await client.get_series(name)


@tool
async def boc_get_group(name: str, lang: Lang = "en") -> GroupDetail:
    """Get a Bank of Canada Valet group's description and member series.

    Use for: discovering all the series in a themed group before
    fetching their observations together, e.g. FX_RATES_DAILY (daily
    exchange rates for ~27 currencies) or CPI_MONTHLY (Total CPI plus
    core-inflation measures such as CPI-trim, CPI-median, CPI-common).
    Keywords: bank of canada, boc, valet, group, detail, member series,
    cpi, exchange rates, commodity prices, metadata.
    Mots-clés : banque du canada, valet, groupe, détail, séries membres,
    IPC, taux de change, prix des produits de base, métadonnées.
    """
    return await client.get_group(name)


@tool
async def boc_get_observations(
    series_names: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    recent: int | None = None,
    recent_weeks: int | None = None,
    recent_months: int | None = None,
    recent_years: int | None = None,
    lang: Lang = "en",
) -> ObservationsResult:
    """Get observations for one or more Bank of Canada Valet series.

    Use for: fetching exchange rate history, interest rate history,
    CPI/inflation history, or commodity price history for one or more
    named series in a single call (series_names accepts multiple codes
    at once, e.g. ["FXUSDCAD", "FXEURCAD"]).
    `start_date`/`end_date` (each "YYYY-MM-DD") and
    `recent`/`recent_weeks`/`recent_months`/`recent_years` are mutually
    exclusive - Valet rejects mixing them. Series requested together
    are merged into one row per date only when they share the same
    publication frequency; mixing frequencies (e.g. a daily FX rate
    with monthly CPI) returns separate rows, each carrying only its own
    series - check each row's `values` keys rather than assuming every
    requested series appears in every row. With no window, the full
    history comes back trimmed to the most recent dates (about 200 KB);
    provenance.limits says how many dates were left out.
    Keywords: bank of canada, boc, valet, observations, data, exchange
    rate, interest rate, policy rate, prime rate, cpi, inflation,
    commodity price, time series, history, recent, date range.
    Mots-clés : banque du canada, valet, observations, données, taux de
    change, taux d'intérêt, taux directeur, taux préférentiel, IPC,
    inflation, prix des matières premières, série chronologique,
    historique, plage de dates.
    """
    return await client.get_observations(
        series_names,
        start_date=start_date,
        end_date=end_date,
        recent=recent,
        recent_weeks=recent_weeks,
        recent_months=recent_months,
        recent_years=recent_years,
    )


@tool
async def boc_get_group_observations(
    group_name: str,
    start_date: str | None = None,
    end_date: str | None = None,
    recent: int | None = None,
    recent_weeks: int | None = None,
    recent_months: int | None = None,
    recent_years: int | None = None,
    lang: Lang = "en",
) -> GroupObservationsResult:
    """Get observations for every series in a Bank of Canada Valet group.

    Use for: fetching all series in a themed group at once, e.g. every
    daily exchange rate in FX_RATES_DAILY or the full CPI_MONTHLY family
    (Total CPI, CPI-trim, CPI-median, CPI-common), without listing each
    series name individually.
    `start_date`/`end_date` and `recent`/`recent_weeks`/`recent_months`/
    `recent_years` are mutually exclusive, same as boc_get_observations.
    With no window, the most recent dates are kept within about 200 KB
    (FX_RATES_DAILY's full history is over 1 MB); provenance.limits says
    how many dates were left out.
    Keywords: bank of canada, boc, valet, group, observations, data,
    exchange rates, cpi, inflation, commodity prices, time series,
    history, recent, date range.
    Mots-clés : banque du canada, valet, groupe, observations, données,
    taux de change, IPC, inflation, prix des produits de base, série
    chronologique, historique, plage de dates.
    """
    return await client.get_group_observations(
        group_name,
        start_date=start_date,
        end_date=end_date,
        recent=recent,
        recent_weeks=recent_weeks,
        recent_months=recent_months,
        recent_years=recent_years,
    )
