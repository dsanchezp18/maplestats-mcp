"""reproduce_code: the same data, fetched from an R, Python, Stata or Julia script."""

from __future__ import annotations

from typing import Any

from fastmcp.tools import tool

from maple_data_mcp.modules.reproduce import client
from maple_data_mcp.modules.reproduce.schemas import Language, ReproductionCode


@tool
async def reproduce_code(
    tool_name: str, arguments: dict[str, Any], language: Language = "r"
) -> ReproductionCode:
    """Get R, Python, Stata or Julia code that fetches the same data as a tool call.

    Use for: moving a result into an analysis script reproducibly. Pass
    the tool name and arguments you called it with. StatCan tables use
    cansim in R, Beyond 20/20 tables use canivt, and the Bank of Canada,
    Socrata and CKAN queries are rebuilt exactly; other tools use the
    result's source URL (method says which). Python code uses polars,
    Julia TidierFiles, Stata import delimited. Downloads go to data/raw/.
    Keywords: reproducible, R code, Python code, Stata do-file, Julia,
    script, cansim, download data, replication.
    Mots-clés : reproductible, code R, code Python, Stata, Julia,
    script, télécharger les données, réplication.
    """
    return await client.reproduce(tool_name, arguments, language)
