"""MCP tools for Job Bank wages (ESDC) on open.canada.ca."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.jobbank import client, constants
from maplestats_mcp.modules.jobbank.schemas import (
    EconomicRegionList,
    OccupationComparison,
    OccupationSearchResult,
    OccupationWages,
)

Lang = Literal["en", "fr"]


@tool
async def jobbank_search_occupations(
    query: str,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    release_year: int | None = None,
    lang: Lang = "en",
) -> OccupationSearchResult:
    """Find occupations (NOC 2021 codes) in Job Bank's wage data, with the national median wage.

    Use for: turning a job title ("electrician", "infirmière", "welder")
    into the five-digit NOC 2021 code the other jobbank_ tools take, or listing
    the occupations under a NOC prefix ("2123", "31"). Words must all appear in
    the English or French title (accents and case ignored); digits match code
    prefixes. Each match carries the Canada-wide median wage, whether it is
    hourly or annual, its reference period and data source. release_year picks
    an older NOC 2021 release (2023 on); the default is the newest one, found
    from the open.canada.ca package at run time.
    Keywords: Job Bank, wages, salary, occupation, NOC 2021, National
    Occupational Classification, job title, median wage, hourly wage, pay, ESDC.
    Mots-clés : Guichet-Emplois, salaires, rémunération, profession, métier,
    CNP 2021, Classification nationale des professions, titre d'emploi, salaire
    médian, taux horaire, EDSC.
    """
    return await client.search_occupations(query, limit, release_year, lang)


@tool
async def jobbank_get_wages(
    noc: str,
    region: str | None = None,
    province: str | None = None,
    published_only: bool = False,
    release_year: int | None = None,
    lang: Lang = "en",
) -> OccupationWages:
    """Get Job Bank's low, median and high wages for one occupation, by economic region.

    Use for: "what does an electrician (NOC 72200) earn in Toronto",
    prevailing wages for an occupation across Canada, a province or one
    economic region, and LMIA or job-offer wage benchmarks. `noc` is a
    five-digit NOC 2021 code (find it with jobbank_search_occupations).
    `region` takes an economic region name or code ("Toronto", "ER3530",
    "Montréal"), a province code ("ON") or "Canada"; `province` alone returns
    the province and all its economic regions; neither returns all 86
    geographies. Each row gives the wage unit (hourly or annual), the data
    source Job Bank names (Labour Force Survey, Small Area Estimation, Census,
    EI survey), the reference period, and published=false where Job Bank
    publishes no wage. Low and high are in most cases the 10th and 90th
    percentiles; average_wage, where present, is Job Bank's own estimate too.
    These are Job Bank estimates, not a StatCan table: for StatCan's
    published average wages by occupation use the Labour Force Survey table
    14-10-0417 (Employee wages by occupation, annual) through wds_, and for
    industries the Survey of Employment, Payrolls and Hours (SEPH, e.g.
    14-10-0223, average weekly earnings by industry).
    Keywords: Job Bank, wages, salary by region, earn, earnings, median wage, prevailing wage, economic region, hourly wage,
    annual salary, occupation pay, trades, NOC, LMIA, ESDC.
    Mots-clés : Guichet-Emplois, salaires, salaire par région, combien
    gagne, gains, salaire médian, salaire en vigueur, région économique, taux
    horaire, salaire annuel, rémunération d'une profession, métiers, CNP,
    EIMT, EDSC.
    """
    return await client.get_wages(noc, region, province, published_only, release_year, lang)


@tool
async def jobbank_compare_occupations(
    nocs: list[str],
    region: str = "Canada",
    province: str | None = None,
    release_year: int | None = None,
    lang: Lang = "en",
) -> OccupationComparison:
    """Compare Job Bank wages for several occupations in one region.

    Use for: side-by-side low, median and high wages of 2 to 25 occupations
    (NOC 2021 codes) in Canada, a province or one economic region, e.g.
    electricians vs plumbers vs carpenters in Calgary. `region`
    takes a name or code like jobbank_get_wages ("Calgary", "ER4830", "QC",
    "Canada"); `province` narrows an ambiguous name ("Northeast" exists in
    Ontario and BC). mixed_units is true when some occupations are paid
    annually and others hourly: those medians are not comparable as is.
    Keywords: Job Bank, compare wages, occupations, salary comparison, median
    wage, economic region, NOC, career choice, ESDC.
    Mots-clés : Guichet-Emplois, comparer les salaires, professions,
    comparaison salariale, salaire médian, région économique, CNP, choix de
    carrière, EDSC.
    """
    return await client.compare_occupations(nocs, region, province, release_year, lang)


@tool
async def jobbank_list_regions(
    province: str | None = None,
    release_year: int | None = None,
    lang: Lang = "en",
) -> EconomicRegionList:
    """List the geographies Job Bank publishes wages for: Canada, provinces and economic regions.

    Use for: finding the economic region code or exact name (ER3530 Toronto,
    ER2440 Montréal, ER5920 Lower Mainland) to pass to jobbank_get_wages or
    jobbank_compare_occupations, or seeing which regions a province has.
    `province` is a code such as ON, QC, BC, YT.
    Keywords: Job Bank, economic regions, ER code, geography, region list,
    province, territory, labour market region, wages, ESDC.
    Mots-clés : Guichet-Emplois, régions économiques, code RE, géographie,
    liste des régions, province, territoire, région du marché du travail,
    salaires, EDSC.
    """
    return await client.list_regions(province, release_year, lang)
