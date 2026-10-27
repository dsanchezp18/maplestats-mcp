"""MCP tools for Ontario's municipal Financial Information Return (FIR).

The FIR identifies every number by an SLC code (schedule, line, column:
"slc.40X.L0420.C01.11" is schedule 40, line 0420 police, column 11 total
expenses after adjustments). on_fir_search_lines finds codes by label words,
on_fir_get_schedule reads one municipality's schedule, and on_fir_compare
reads one code across municipalities or years. The Ministry publishes the
labels in English only; `lang="fr"` gives this server's own text in French.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.on_fir import client
from maplestats_mcp.modules.on_fir.schemas import (
    ComparisonResult,
    LineSearch,
    MunicipalitySearch,
    ScheduleList,
    ScheduleResult,
)

Lang = Literal["en", "fr"]
Tier = Literal["UT", "LT", "ST"]


@tool
async def on_fir_list_schedules(year: int | None = None, lang: Lang = "en") -> ScheduleList:
    """List the FIR years published and the schedules filed for one year.

    Use for: which years of Ontario municipal Financial Information Return
    data exist (2000 to the newest, with each file's update date), which
    schedules a year has (10 revenue, 12 grants and user fees, 22 and 26
    taxation, 40 expenses by function, 51 tangible capital assets, 60
    reserves, 70 financial position, 74 long-term debt, 80 statistics and
    service measures such as staff, building permits and road condition,
    81 debt repayment limit), and
    how many of the 444 municipalities have filed. Without `year`, the
    year before the newest (the newest fills in over the following year).
    The first call for a year downloads it (about 10 MB).
    Keywords: Ontario, municipal finance, Financial Information Return,
    FIR, schedules, municipalities, MMAH, local government finance,
    years available, budget, audited financial statements.
    Mots-clés : Ontario, finances municipales, rapport d'information
    financière, RIF, annexes, municipalités, ministère des Affaires
    municipales, administration locale, années disponibles, états
    financiers.
    """
    return await client.list_schedules(year, lang=lang)


@tool
async def on_fir_search_municipalities(
    query: str = "",
    year: int | None = None,
    tier: Tier | None = None,
    limit: int = 25,
    lang: Lang = "en",
) -> MunicipalitySearch:
    """Find Ontario municipalities in the FIR and their MUNID, tier and population.

    Use for: the Ministry municipal ID (MUNID) of a city, town, township,
    county or region to pass to on_fir_get_schedule or on_fir_compare;
    whether it is upper tier (UT: county, region, district), lower tier
    (LT) or single tier (ST); its upper tier number, population and
    households as reported on schedule 02; whether it has filed a return
    for the year yet. Words match the name ("toronto", "peel", "sault"),
    a number matches the MUNID or assessment code; an empty query lists
    every municipality that filed. Names carry a type suffix: C city, T
    town, Tp township, V village, M municipality, Co county, R region, UCo
    united counties.
    Keywords: Ontario municipalities, MUNID, municipal ID, upper tier,
    lower tier, single tier, county, region, population, households.
    Mots-clés : municipalités de l'Ontario, identifiant municipal, palier
    supérieur, palier inférieur, palier unique, comté, région, population,
    ménages, cantons.
    """
    return await client.search_municipalities(query, year, tier, limit, lang=lang)


@tool
async def on_fir_search_lines(
    query: str,
    year: int | None = None,
    schedule: str | None = None,
    limit: int = 25,
    lang: Lang = "en",
) -> LineSearch:
    """Find FIR data point codes (SLC) by the words in their line and column labels.

    Use for: the code of a municipal finance figure before comparing it,
    e.g. "police total expenses" (schedule 40), "residential total taxes"
    (26), "reserves balance end of year" (60), "long term debt" (74),
    "closing net book value" (51), "full-time funded positions" or "paved
    lane km" (80). Every word must appear in the schedule, line or
    column label (English, as the Ministry publishes it). `schedule`
    ("40", "26A") narrows the search. Each result gives the SLC, its
    labels, data type and how many municipalities reported it.
    Keywords: FIR line codes, SLC, schedule line column, municipal
    expenses, revenue, taxation, reserves, debt, capital assets, police,
    roads, transit.
    Mots-clés : codes de ligne du RIF, annexe ligne colonne, charges
    municipales, revenus, impôts fonciers, réserves, dette,
    immobilisations, police, voirie, transport en commun.
    """
    return await client.search_lines(query, year, schedule, limit, lang=lang)


@tool
async def on_fir_get_schedule(
    municipality: str,
    schedule: str,
    year: int | None = None,
    line: str | None = None,
    lang: Lang = "en",
) -> ScheduleResult:
    """Read one Ontario municipality's FIR schedule for one year, with labels.

    Use for: a city's revenue by source (schedule 10), expenses by
    function and object (40: salaries, interest, materials, contracted
    services, amortization for governance, police, fire, roads, transit,
    waste, social housing, parks, planning), property taxes levied
    (26), reserves and reserve funds (60), statement of financial position
    (70), long-term liabilities (74), tangible capital assets (51),
    staff, building permits and road condition (80). `municipality` is a
    MUNID or a name ("Toronto", "Peel R"); `schedule` is "40", "40X" or
    "26A"; `line` ("0420") limits it to one line. Amounts are dollars.
    Keywords: municipal budget, municipal spending, city finances,
    revenue, expenses, property tax, reserves, debt, financial statements,
    Ontario.
    Mots-clés : budget municipal, dépenses municipales, finances de la
    ville, revenus, charges, impôt foncier, réserves, dette, états
    financiers, Ontario.
    """
    return await client.get_schedule(municipality, schedule, year, line, lang=lang)


@tool
async def on_fir_compare(
    slc: str,
    years: list[int] | None = None,
    municipalities: list[str] | None = None,
    tier: Tier | None = None,
    per_capita: bool = False,
    limit: int = 50,
    lang: Lang = "en",
) -> ComparisonResult:
    """Compare one FIR figure across Ontario municipalities or years, optionally per capita.

    Use for: ranking municipalities on a line (police spending per capita,
    debt per household, property taxes, reserves), or one municipality's
    figure over time. `slc` is a code from on_fir_search_lines or
    on_fir_get_schedule, such as "slc.40X.L0420.C01.11". `years` takes up
    to 10 years (default: the year before the newest); `municipalities`
    up to 50 MUNIDs or names (default: every municipality that reported
    it, largest first); `tier` keeps UT, LT or ST only, since upper and
    lower tiers split services and should not be ranked together.
    `per_capita` divides by the population on schedule 02. Line numbers
    change between FIR templates, so `label_changes` lists years whose
    labels differ.
    Keywords: compare municipalities, per capita spending, municipal
    benchmarking, ranking, time series, Ontario cities, police cost, debt
    per capita, property tax.
    Mots-clés : comparer les municipalités, dépenses par habitant,
    étalonnage municipal, classement, série chronologique, villes de
    l'Ontario, coût des services, dette par habitant.
    """
    return await client.compare(slc, years, municipalities, tier, per_capita, limit, lang=lang)
