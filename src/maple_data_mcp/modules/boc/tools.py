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

from maple_data_mcp.modules.boc import client
from maple_data_mcp.modules.boc.schemas import (
    GroupDetail,
    GroupList,
    GroupObservationsResult,
    ObservationsResult,
    SeriesDetail,
    SeriesList,
)

Lang = Literal["en", "fr"]


@tool
async def boc_search_series(query: str, limit: int = 25, lang: Lang = "en") -> SeriesList:
    """Search Bank of Canada Valet's ~16,000 statistical series by keyword.

    Use for: finding a Valet series name when you only know a topic -
    exchange rates, interest rates (policy rate, prime rate), CPI/
    inflation measures, commodity prices, and hundreds of other
    monetary/financial series.
    Keywords: bank of canada, boc, valet, series, search, find, exchange
    rate, interest rate, policy rate, prime rate, cpi, inflation,
    commodity price, discover.
    Mots-clés: banque du canada, valet, série, recherche, trouver, taux
    de change, taux d'intérêt, taux directeur, taux préférentiel, IPC,
    inflation, prix des matières premières, découvrir.
    """
    return await client.search_series(query, limit=limit)


@tool
async def boc_list_series(lang: Lang = "en") -> SeriesList:
    """List every Bank of Canada Valet statistical series (~16,000).

    Use for: a full inventory scan or building a local index. Prefer
    boc_search_series for a topic search - this returns the entire
    catalogue.
    Keywords: bank of canada, boc, valet, list, inventory, all series,
    catalogue, full list.
    Mots-clés: banque du canada, valet, liste, inventaire, toutes les
    séries, catalogue, liste complète, parcourir.
    """
    return await client.list_series()


@tool
async def boc_search_groups(query: str, limit: int = 25, lang: Lang = "en") -> GroupList:
    """Search Bank of Canada Valet's series groups by keyword.

    Use for: finding a themed group of related series (e.g. daily
    exchange rates, the CPI family including CPI-trim/median/common,
    weekly/monthly/annual commodity price indexes) when you want several
    related series at once rather than one series name.
    Keywords: bank of canada, boc, valet, group, series group, search,
    find, cpi, exchange rates, commodity prices, discover.
    Mots-clés: banque du canada, valet, groupe, groupe de séries,
    recherche, trouver, IPC, taux de change, prix des produits de base,
    découvrir.
    """
    return await client.search_groups(query, limit=limit)


@tool
async def boc_list_groups(lang: Lang = "en") -> GroupList:
    """List every Bank of Canada Valet series group (~2,500).

    Use for: a full inventory scan of themed series groupings. Prefer
    boc_search_groups for a topic search - this returns the entire
    catalogue.
    Keywords: bank of canada, boc, valet, list, groups, inventory,
    catalogue, full list.
    Mots-clés: banque du canada, valet, liste, groupes, inventaire,
    catalogue, liste complète, parcourir.
    """
    return await client.list_groups()


@tool
async def boc_get_series(name: str, lang: Lang = "en") -> SeriesDetail:
    """Get the label and description for one Bank of Canada Valet series.

    Use for: confirming what a series code actually measures before
    requesting its observations, e.g. FXUSDCAD (USD/CAD daily exchange
    rate), V39079 (target for the overnight rate / policy rate),
    V80691311 (prime rate), V41690973 (Total CPI).
    Keywords: bank of canada, boc, valet, series, detail, metadata,
    description, label, lookup.
    Mots-clés: banque du canada, valet, série, détail, métadonnées,
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
    Mots-clés: banque du canada, valet, groupe, détail, séries membres,
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
    requested series appears in every row.
    Keywords: bank of canada, boc, valet, observations, data, exchange
    rate, interest rate, policy rate, prime rate, cpi, inflation,
    commodity price, time series, history, recent, date range.
    Mots-clés: banque du canada, valet, observations, données, taux de
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
    Keywords: bank of canada, boc, valet, group, observations, data,
    exchange rates, cpi, inflation, commodity prices, time series,
    history, recent, date range.
    Mots-clés: banque du canada, valet, groupe, observations, données,
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
