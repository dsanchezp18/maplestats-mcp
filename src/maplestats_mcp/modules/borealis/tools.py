"""MCP tools for Beyond 20/20 files on Borealis."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.borealis import client, constants
from maplestats_mcp.modules.borealis.schemas import IvtSearchResult

Lang = Literal["en", "fr"]


@tool
async def borealis_search_ivt(
    query: str = "",
    limit: int = constants.LIMIT_DEFAULT,
    lang: Lang = "en",
) -> IvtSearchResult:
    """Find Beyond 20/20 (.ivt) statistical tables on Borealis, with R code to read them.

    Use for: Statistics Canada tables that exist only as Beyond 20/20
    files and were deposited on Borealis (the Canadian Dataverse) by
    university libraries: historical censuses 1665-1871, Census of
    Population tabulations 1996-2021, Census of Agriculture 2001, the
    Labour Force Historical Review 1997-2008, Canadian Business Patterns
    and Business Counts, justice surveys, HART housing tabulations. Every
    word of the query must match the dataset or file. Each hit gives the
    download URL, size, whether a Borealis login is needed, and an R
    snippet using canivt (mountainMath), the only maintained IVT reader.
    An empty query lists IVT files by relevance. `lang` has no effect;
    dataset titles are as deposited (English or French).
    Keywords: Beyond 20/20, IVT, Borealis, Dataverse, Data Liberation
    Initiative, historical census, Canadian Business Patterns, Labour
    Force Historical Review, canivt, custom tabulation.
    Mots-clés : Beyond 20/20, IVT, Borealis, Dataverse, Initiative de
    démocratisation des données, recensement historique, Structure des
    industries canadiennes, Revue chronologique de la population active,
    totalisation personnalisée.
    """
    del lang
    return await client.search_ivt(query, limit=limit)
