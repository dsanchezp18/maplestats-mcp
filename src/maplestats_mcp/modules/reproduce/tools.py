"""reproduce_code: the same data, fetched from an R, Python, Stata or Julia script."""

from __future__ import annotations

from typing import Any

from fastmcp.tools import tool

from maplestats_mcp.modules.reproduce import client
from maplestats_mcp.modules.reproduce.schemas import LanguageChoice, ReproductionCode


@tool
async def reproduce_code(
    tool_name: str, arguments: dict[str, Any], language: LanguageChoice = "all"
) -> ReproductionCode:
    """Get R, Python, Stata and Julia scripts that fetch and clean the same data.

    Use for: moving any data tool's result into an analysis script
    reproducibly. Pass the tool name and the arguments you called it
    with; the server writes the scripts, ready to run. Tools that return
    documents or text (StatCan articles and Daily releases, Gazette
    notices, Hansard) get no script. It rebuilds the exact request: from
    the arguments (StatCan tables via cansim, Beyond 20/20 via canivt,
    Valet, Socrata, CKAN), or by recording the upstream request the tool
    makes (every query parameter, POST body and header). Where the tool
    filters a downloaded file itself (CanadaBuys, CER, GC InfoBase, CIHI,
    IRCC, IP Horizons patents), the script repeats those filters. Scripts
    follow a header plus numbered sections (setup, read, check, prepare),
    save downloads under data/raw/, and clean names, text and numbers;
    Python uses polars, Julia TidierFiles, Stata import delimited (JSON
    and filtered files go through Stata's built-in Python). notes say what
    a script cannot repeat and why a language is missing; language picks
    one.
    Keywords: reproducible, R code, Python code, Stata do-file, Julia,
    script, cansim, download data, replication, code generation.
    Mots-clés : reproductible, code R, code Python, Stata, Julia,
    script, télécharger les données, réplication, génération de code.
    """
    return await client.reproduce(tool_name, arguments, language)
