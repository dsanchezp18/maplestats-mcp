"""reproduce_code: the same data, fetched from an R, Python, Stata or Julia script."""

from __future__ import annotations

from typing import Any

from fastmcp.tools import tool

from maple_data_mcp.modules.reproduce import client
from maple_data_mcp.modules.reproduce.schemas import LanguageChoice, ReproductionCode


@tool
async def reproduce_code(
    tool_name: str, arguments: dict[str, Any], language: LanguageChoice = "all"
) -> ReproductionCode:
    """Get R, Python, Stata and Julia scripts that fetch and clean the same data.

    Use for: moving a result into an analysis script reproducibly. Pass
    the tool name and arguments you called it with. StatCan tables use
    cansim in R, Beyond 20/20 tables use canivt, and the Bank of Canada,
    Socrata and CKAN queries are rebuilt exactly; other tools use the
    result's source URL (method says which). Python code uses polars,
    Julia TidierFiles, Stata import delimited. Downloads go to data/raw/.
    By default all languages that can read the source are returned, each
    with retrieval plus basic cleaning (consistent names, trimmed text,
    missing values, numeric types, and source steps such as StatCan's
    scalar factor); language picks just one.
    Keywords: reproducible, R code, Python code, Stata do-file, Julia,
    script, cansim, download data, replication.
    Mots-clés : reproductible, code R, code Python, Stata, Julia,
    script, télécharger les données, réplication.
    """
    return await client.reproduce(tool_name, arguments, language)
