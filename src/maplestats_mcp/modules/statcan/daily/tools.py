"""MCP tools for The Daily (StatCan's official release bulletin)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.daily import client, constants
from maplestats_mcp.modules.statcan.daily.schemas import (
    DailyArchiveSearchResult,
    DailyArticle,
    DailyReleaseList,
    ReleaseCalendarResult,
    ReleaseFilesResult,
    ReleaseTablesResult,
    UpcomingReleasesResult,
)
from maplestats_mcp.modules.statcan.lang import use_lang

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
    Canada, latest statistics, today's releases, press releases, news.
    Mots-clés : Le Quotidien, bulletin de diffusion, nouvelles données,
    diffusions récentes, quoi de neuf, annonce de Statistique Canada,
    Statistique Canada, dernières statistiques, communiqués du Quotidien,
    communiqués d'aujourd'hui, diffusions du jour, nouveautés.
    """
    use_lang(lang)
    return await client.get_releases(subject, lang=lang, limit=limit)


@tool
async def statcan_daily_get_article(
    article: str,
    lang: Literal["en", "fr"] = "en",
) -> DailyArticle:
    """Read the full text of one Daily article, with its tables, charts and PDF.

    Use for: what StatCan actually wrote in a release -- the analysis,
    the headings, the Note to readers (concepts, revisions, next release
    date) -- beyond the one-paragraph summary statcan_daily_get_releases
    gives. `article` is the id ("dq261104a") or the URL that
    statcan_daily_get_releases or statcan_daily_search_archive returned;
    `lang` picks the English or French page. Returns the text by
    section, chart titles, the StatCan tables the text links to (with
    8-digit product ids for the wds_ tools), the article's own PDF, its
    Tables and Related information pages, the previous release, and the
    other links in the body. Charts and the release's tables are not
    reproduced: read figures from the tables and cite them.
    Keywords: The Daily article, full text, release text, StatCan
    analysis, note to readers, PDF, press release, Daily release,
    commentary, what StatCan said, what StatCan says about a release,
    today's release explained, highlights, release article.
    Mots-clés : article du Quotidien, texte intégral, texte du
    communiqué, analyse de Statistique Canada, note aux lecteurs, PDF,
    communiqué de presse, diffusion du Quotidien, faits saillants,
    commentaire, article de diffusion, ce que dit Statistique Canada.
    """
    use_lang(lang)
    return await client.get_article(article, lang=lang)


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
    Results are returned most-recent-first. The archive also holds UPCOMING
    releases (entries of type "meeting", dated in the future): search with
    start_date set to today to see what StatCan has scheduled. Each entry
    has scheduled (true when the release date is today or later, Toronto
    time); an upcoming one has url null because its article does not exist yet.
    Keywords: The Daily, historical,
    archive, past releases, release history, when was, Statistics Canada,
    release date, upcoming releases, release schedule, release calendar.
    Mots-clés : Le Quotidien, historique, archive, diffusions passées,
    historique des diffusions, quand, Statistique Canada, date de diffusion,
    diffusions à venir, calendrier de diffusion.
    """
    use_lang(lang)
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
    until the release is out. Dates are plans and can move. When nothing
    scheduled matches (the 2026 provincial and territorial economic
    accounts, a year ahead), not_scheduled gives the same release's past
    dates, any release of it already scheduled, and an estimate from the
    usual gap: report the estimate as an estimate, never as a date
    StatCan announced. For releases already out use
    statcan_daily_search_archive.
    Keywords: release calendar, release schedule, next release, upcoming
    releases, when is the next, Labour Force Survey release date, CPI
    release date, The Daily, indicators calendar, last year's release
    date, PTEA, supply and use tables, Statistics Canada.
    Mots-clés : calendrier de diffusion, prochaine diffusion, prochaines
    parutions, date de diffusion, quand sort, Enquête sur la population
    active, indice des prix à la consommation, Le Quotidien, indicateurs
    clés, Statistique Canada.
    """
    use_lang(lang)
    return await client.get_release_calendar(
        query,
        lang=lang,
        kind=kind,
        upcoming_only=upcoming_only,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


@tool
async def statcan_daily_get_upcoming_releases(
    query: str = "",
    lang: Literal["en", "fr"] = "en",
) -> UpcomingReleasesResult:
    """List every StatCan release scheduled in the next two weeks, studies included.

    Use for: "what is StatCan releasing this week / next week" -- the
    detailed two-week schedule from The Daily's Upcoming releases page:
    every release, not only the major indicators (annual surveys,
    studies, census data tables, price indexes), each with its date,
    reference period, whether it has a media lockup (the major
    economic releases) and the StatCan contact. query keeps the releases
    whose title or reference period holds every word (accents ignored).
    Also returns the same list as a PDF, and the link to StatCan's
    annual PDF of planned release dates for the major economic
    indicators (the whole year, e.g. "2026-2027 release dates") with the
    names of those indicators. For dates further than two weeks ahead
    use statcan_daily_get_release_calendar (major indicators, about six
    months); for releases already out, statcan_daily_search_archive. When
    the query matches nothing in the window, not_scheduled gives the
    release's past dates and an estimate, labelled as one.
    Keywords: upcoming releases, this week, next week, release schedule,
    two-week schedule, what is coming out, lockup, major economic releases,
    annual release dates, release calendar PDF, Statistics Canada, The Daily.
    Mots-clés : diffusions à venir, cette semaine, semaine prochaine,
    calendrier de diffusion, huis clos, principales diffusions
    économiques, dates de diffusion annuelles, prochaines parutions,
    Le Quotidien, Statistique Canada.
    """
    use_lang(lang)
    return await client.get_upcoming_releases(query, lang=lang)


@tool
async def statcan_daily_get_release_files(
    article: str,
    lang: Literal["en", "fr"] = "en",
    previous: int = 0,
) -> ReleaseFilesResult:
    """Get the tables, PDF, surveys and publications behind a Daily release, and past releases.

    Use for: "which tables and documents came with this release" and
    "what did the previous releases of this indicator include" -- for one
    Daily article (id such as "dq261030a" or its URL, from
    statcan_daily_get_releases or statcan_daily_search_archive) returns
    the article's PDF, every table of the release (title, frequency,
    table number and 8-digit product id for the wds_ tools), the surveys
    with their IMDB documentation pages (definitions, methods), the
    catalogued publications it links, its subjects and its release
    schedule. previous (0 to 12) also walks the "Previous release" links
    back that many releases, newest first, so you can see each past
    release's PDF and tables. Releases from 2012 to 2017 cite old CANSIM
    numbers; these are matched to today's tables where StatCan kept the
    link (legacy_cansim_id holds the old number). Links only: read the
    figures with the wds_ tools and the text with statcan_daily_get_article.
    Keywords: release tables, datasets, PDF, previous release, past
    releases, release history, CANSIM table, related information, IMDB,
    survey documentation, release files, downloads, The Daily, Statistics Canada.
    Mots-clés : tableaux du communiqué, jeux de données, PDF, communiqué
    précédent, diffusions passées, historique des diffusions, tableau
    CANSIM, informations connexes, documentation de l'enquête,
    Le Quotidien, Statistique Canada.
    """
    use_lang(lang)
    return await client.get_release_files(article, lang=lang, previous=previous)


@tool
async def statcan_daily_get_release_tables(
    article: str,
    lang: Literal["en", "fr"] = "en",
    tables: list[int] | None = None,
    search: str = "",
    limit: int = constants.RELEASE_TABLE_ROWS_DEFAULT,
) -> ReleaseTablesResult:
    """Read the tables published inside a Daily release, with the values as first published.

    Use for: the figures exactly as StatCan released them on the day --
    first estimates before revision, e.g. the January 2018 LFS change in
    employment by province -- which the wds_ tables no longer show once
    revised (the LFS has no real-time table). `article` is a Daily
    article id ("dq180209a") or URL from statcan_daily_search_archive or
    statcan_daily_get_releases. Returns every table the article links
    (Table 1, Table 2...) with its title, units, columns, notes and
    sources, its page and CSV links, and its values as tidy rows: group
    (e.g. the province), parent rows, row, column, unit, the cell as
    published and as a number. `tables` picks tables by number ([3]);
    `search` keeps rows whose labels contain every word ("Alberta
    employment"); `limit` caps rows across tables (default 500, max
    5000) and `truncated` says when more exist. Releases from 2012 on,
    English or French.
    Keywords: first published, as released, release tables, preliminary
    estimate, unrevised, original release, vintage, real-time data, Daily
    table, LFS release table, CPI release table, GDP release table.
    Mots-clés : première publication, données non révisées, tableaux du
    communiqué, estimation préliminaire, valeurs d'origine, millésime,
    données en temps réel, tableau du Quotidien, tableau de l'EPA,
    tableau de l'IPC, tableau du PIB.
    """
    use_lang(lang)
    return await client.get_release_tables(
        article, lang=lang, tables=tables, search=search, limit=limit
    )
