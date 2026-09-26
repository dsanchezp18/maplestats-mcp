"""MCP tools for the 2006-2016 census data tables."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.census_tables import client, constants
from maplestats_mcp.modules.statcan.census_tables.schemas import (
    CensusTableDownloads,
    CensusTableSearch,
)

Release = Literal["2016", "2011", "2011_nhs", "2006"]


@tool
async def statcan_census_tables_search(
    query: str = "",
    release: Release = "2016",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    lang: Literal["en", "fr"] = "en",
) -> CensusTableSearch:
    """Search the 2006, 2011 (Census and NHS) and 2016 census data tables.

    Use for: census cross-tabulations by topic and geography, e.g.
    "income household type" or "language dissemination areas", with the
    catalogue number and PID of each table. Every word must appear in
    the title. 2021 census tables are StatCan tables: use
    wds_search_cubes. StatCan retired the 2011 Census tabulations
    (the 2011 NHS ones remain); copies are on Borealis, see
    borealis_search_ivt. Titles are in English; lang is accepted for
    consistency.
    Keywords: census data tables, cross-tabulation, 2016 census, 2011
    National Household Survey, 2006 census, Beyond 20/20, topic-based
    tabulations.
    Mots-clés : tableaux de données du recensement, totalisations
    croisées, recensement de 2016, Enquête nationale auprès des ménages,
    recensement de 2006, Beyond 20/20.
    """
    return await client.search(query, release=release, limit=limit)


@tool
async def statcan_census_tables_get_downloads(
    pid: str, release: Release = "2016", lang: Literal["en", "fr"] = "en"
) -> CensusTableDownloads:
    """Get a census data table's download links: CSV, SDMX and Beyond 20/20 IVT.

    Use for: downloading a table found with statcan_census_tables_search
    (by pid). Checks which formats exist and their sizes. When only the
    IVT exists, returns an R snippet using mountainMath's canivt to read
    it. Some SDMX files are very large; check size_bytes first.
    Keywords: census table download, CSV, SDMX, IVT, Beyond 20/20,
    canivt, full table.
    Mots-clés : téléchargement, tableau du recensement, CSV, SDMX, IVT,
    Beyond 20/20, tableau complet.
    """
    return await client.get_downloads(pid, release=release)
