"""MCP tools for The Daily (StatCan's official release bulletin)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.daily import client, constants
from maplestats_mcp.modules.statcan.daily.schemas import (
    DailyArchiveSearchResult,
    DailyReleaseList,
    ReleaseCalendarResult,
)

Subject = Literal[
    "all",
    "agriculture_and_food",
    "business_and_consumer_services_and_culture",
    "business_performance_and_ownership",
    "children_and_youth",
    "construction",
    "crime_and_justice",
    "digital_economy_and_society",
    "economic_accounts",
    "education_training_and_learning",
    "energy",
    "environment",
    "families_households_and_marital_status",
    "government",
    "health",
    "housing",
    "immigration_and_ethnocultural_diversity",
    "income_pensions_spending_and_wealth",
    "indigenous_peoples",
    "international_trade",
    "labour",
    "languages",
    "manufacturing",
    "older_adults_and_population_aging",
    "population_and_demography",
    "prices_and_price_indexes",
    "reference",
    "retail_and_wholesale",
    "science_and_technology",
    "society_and_community",
    "statistical_methods",
    "transportation",
    "travel_and_tourism",
]


@tool
async def statcan_daily_get_releases(
    subject: Subject = "all",
    lang: Literal["en", "fr"] = "en",
    limit: int = constants.RELEASES_LIMIT_DEFAULT,
) -> DailyReleaseList:
    """Get recent releases from The Daily, StatCan's official release bulletin.

    Use for: finding what data StatCan has released recently -- new or
    updated tables, survey results, analytical products -- optionally
    filtered to one subject (e.g. "housing", "labour", "prices_and_price_indexes").
    Covers the last 100 days. Each release has a title, a canonical
    URL (either a Daily article or a catalogue-number product page),
    a publication timestamp, and a plain-text summary. Use "all" for
    every subject in one call. Keywords: The Daily, release bulletin, new
    data, recent releases, what's new, StatCan announcement, Statistics
    Canada, latest statistics.
    Mots-clés : Le Quotidien, bulletin de diffusion, nouvelles données,
    diffusions récentes, quoi de neuf, annonce de Statistique Canada,
    Statistique Canada, dernières statistiques.
    """
    return await client.get_releases(subject, lang=lang, limit=limit)


@tool
async def statcan_daily_search_archive(
    query: str = "",
    lang: Literal["en", "fr"] = "en",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.ARCHIVE_SEARCH_LIMIT_DEFAULT,
) -> DailyArchiveSearchResult:
    """Search The Daily's full release archive (2012-03-14 onward), not just the last 100 days.

    Use for: finding when StatCan first or last released something on
    a topic, or listing every historical release matching a keyword,
    going back to 2012 -- statcan_daily_get_releases only covers the
    last 100 days via the official Atom feeds. query matches against
    the release title and reference period (e.g. "second quarter
    2020"); leave it empty to browse by date range alone. start_date
    and end_date are "YYYY-MM-DD" and filter to releases on or between
    those dates (inclusive); omit either to leave that side open.
    Results are returned most-recent-first. Keywords: The Daily, historical,
    archive, past releases, release history, when was, Statistics Canada,
    release date.
    Mots-clés : Le Quotidien, historique, archive, diffusions passées,
    historique des diffusions, quand, Statistique Canada, date de diffusion.
    """
    return await client.search_archive(
        query, lang=lang, start_date=start_date, end_date=end_date, limit=limit
    )


@tool
async def statcan_daily_get_release_calendar(
    query: str = "",
    lang: Literal["en", "fr"] = "en",
    kind: Literal["key_indicators", "products", "all"] = "key_indicators",
    upcoming_only: bool = True,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.CALENDAR_LIMIT_DEFAULT,
) -> ReleaseCalendarResult:
    """Find when StatCan will next release something (forward release calendar).

    Use for: "when is the next release of X" -- the planned date of
    upcoming Daily releases of key indicators (Labour Force Survey,
    international merchandise trade, building permits, CPI
    and so on, with their reference period), checked live to
    reach about six months ahead. query needs every word to appear in
    the title, reference period or catalogue number
    (accents ignored); start_date and end_date are "YYYY-MM-DD". With
    upcoming_only=True (default) results run soonest first from today
    (Toronto); with False they are the history, newest first. kind
    "products" is the catalogue-number release history since 2012 only:
    that file has no future dates (use it for "when was catalogue
    62-013-X published"); "all" merges both. Scheduled rows have no URL
    until the release is out. Dates are plans and can move. For
    releases already out use statcan_daily_search_archive.
    Keywords: release calendar, release schedule, next release, upcoming
    releases, when is the next, Labour Force Survey release date, CPI
    release date, The Daily, indicators calendar,
    Statistics Canada.
    Mots-clés : calendrier de diffusion, prochaine diffusion, prochaines
    parutions, date de diffusion, quand sort, Enquête sur la population
    active, indice des prix à la consommation, Le Quotidien, indicateurs
    clés, Statistique Canada.
    """
    return await client.get_release_calendar(
        query,
        lang=lang,
        kind=kind,
        upcoming_only=upcoming_only,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
