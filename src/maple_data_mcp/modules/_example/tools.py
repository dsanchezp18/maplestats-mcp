"""Template tools.py — the literal pattern new modules copy.

- Standalone @tool decorator from fastmcp.tools (never @mcp.tool).
- Bilingual lang: Literal["en", "fr"] = "en" parameter on every tool.
- Return type is the typed model itself — FastMCP derives
  outputSchema/structuredContent from it automatically.
- Docstring has `Use for:` + `Keywords:` lines (>=8 keywords), plus a
  `Mots-clés:` line with a French equivalent set of terms, so the BM25
  search transform can also match a French-language query.
- Module prefix on every tool name (example_, statcan_wds_, etc. —
  see modules/statcan/*/tools.py for the real prefix-per-submodule
  convention).
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules._example import client
from maple_data_mcp.modules._example.schemas import EchoResult


@tool
async def example_echo(message: str, lang: Literal["en", "fr"] = "en") -> EchoResult:
    """Echo a message back through the shared client/error-raising pattern.

    Use for: verifying the module template registers correctly, testing
    bilingual passthrough, demonstrating the typed-model return
    convention.
    Keywords: echo, test, example, template, bilingual, lang, message,
    demo.
    Mots-clés: écho, test, exemple, gabarit, bilingue, langue, message,
    démo.
    """
    return await client.echo(message)
