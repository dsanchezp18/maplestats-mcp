"""Python client for the MapleStats MCP server: Canadian open data with citations.

import maplestats as ms

ms.search_tools("unemployment rate Alberta")
result = ms.get_data("boc_get_observations", series_names=["FXUSDCAD"], recent=5)
result.data, result.citation
"""

from __future__ import annotations

from typing import Any

from maplestats._version import __version__
from maplestats.client import (
    DEFAULT_URL,
    Client,
    MapleStatsError,
    RateLimited,
    Result,
)

__all__ = [
    "DEFAULT_URL",
    "Client",
    "MapleStatsError",
    "RateLimited",
    "Result",
    "__version__",
    "call_tool",
    "default_client",
    "get_data",
    "plan_query",
    "reproduce_code",
    "search_tools",
]

_default: Client | None = None


def default_client() -> Client:
    """The client the module-level functions use, created on first use."""
    global _default
    if _default is None:
        _default = Client()
    return _default


def search_tools(query: str, client: Client | None = None, detail: str = "full") -> Any:
    """See Client.search_tools."""
    return (client or default_client()).search_tools(query, detail)


def plan_query(question: str, lang: str = "en", client: Client | None = None) -> Any:
    """See Client.plan_query."""
    return (client or default_client()).plan_query(question, lang)


def call_tool(tool: str, /, *, client: Client | None = None, **arguments: Any) -> Any:
    """See Client.call_tool."""
    return (client or default_client()).call_tool(tool, **arguments)


def get_data(tool: str, /, *, client: Client | None = None, **arguments: Any) -> Result:
    """See Client.get_data."""
    return (client or default_client()).get_data(tool, **arguments)


def reproduce_code(
    tool: str,
    arguments: dict[str, Any],
    language: str = "python",
    lang: str = "en",
    client: Client | None = None,
) -> Any:
    """See Client.reproduce_code."""
    return (client or default_client()).reproduce_code(tool, arguments, language, lang)
