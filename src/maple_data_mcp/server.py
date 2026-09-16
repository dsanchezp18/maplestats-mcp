"""The FastMCP server instance: module auto-registration + tool search.

Confirmed working this session: FileSystemProvider recurses into
per-source subfolders (modules/statcan/{wds,sdmx,rdaas}/), auto-
discovering every @tool/@resource/@prompt-decorated function with no
manual registration call. FileSystemProvider itself has no built-in
underscore-prefix skip logic (checked its source directly) — this
module adds one provider per modules/* subdirectory rather than one
provider for the whole tree, specifically so modules/_example/ (the
template new sources copy) never registers its demo tools live.
"""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers import FileSystemProvider
from fastmcp.server.transforms.search import BM25SearchTransform

from maple_data_mcp import __version__

MODULES_ROOT = Path(__file__).parent / "modules"

SERVER_INSTRUCTIONS = """
MapleData MCP — one MCP server for Canadian public data.

Currently implemented: Statistics Canada, via two APIs:
- Web Data Service (WDS): table/cube discovery, metadata, time series
  (tools prefixed wds_).
- SDMX REST API: filtered, server-side-sliced series queries (tools
  prefixed sdmx_).
- Reference Data as a Service (RDaaS): classifications, codesets, and
  concordances such as NAICS (tools prefixed rdaas_).

Every tool accepts lang: "en"|"fr", but it only changes what comes back
for RDaaS tools and wds_get_full_table_download_csv, whose upstream
APIs are genuinely single-language per request. WDS and SDMX metadata/
data tools already return both languages in one response (every field
has an _en/_fr pair) — lang has no additional effect there. Read
docs://statcan/addressing and docs://statcan/gotchas before working
with StatCan's productId/vectorId/coordinate system or its known API
quirks.
""".strip()


def build_server() -> FastMCP:
    mcp = FastMCP("maple-data-mcp", version=__version__, instructions=SERVER_INSTRUCTIONS)
    for module_dir in sorted(MODULES_ROOT.iterdir()):
        if module_dir.is_dir() and not module_dir.name.startswith("_"):
            mcp.add_provider(FileSystemProvider(root=module_dir))
    mcp.add_transform(
        BM25SearchTransform(
            max_results=5,
            always_visible=["search_tools"],
            search_tool_name="search_tools",
            call_tool_name="call_tool",
        )
    )
    return mcp


mcp = build_server()
