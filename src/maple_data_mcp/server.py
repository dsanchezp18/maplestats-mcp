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

Currently implemented:

- Statistics Canada, via three APIs: Web Data Service (WDS) for table/
  cube discovery, metadata, and time series (tools prefixed wds_); the
  SDMX REST API for filtered, server-side-sliced series queries (tools
  prefixed sdmx_); and Reference Data as a Service (RDaaS) for
  classifications, codesets, and concordances such as NAICS (tools
  prefixed rdaas_).
- Bank of Canada Valet API: series and group discovery, metadata, and
  observations — exchange rates, interest rates, CPI/inflation, and
  commodity prices (tools prefixed boc_). Read
  docs://boc/well-known-series for verified series/group names.
- Canadian government CKAN open-data portals (dataset search, dataset/
  organization/resource/license detail, and — where the portal
  actually uses them — tags/groups): federal Government of Canada
  (open.canada.ca, tools prefixed ckan_), British Columbia
  (catalogue.data.gov.bc.ca, ckan_bc_), Northwest Territories
  (opendata.gov.nt.ca, ckan_nt_), Quebec (donneesquebec.ca, ckan_qc_),
  Yukon (open.yukon.ca, ckan_yt_), City of Montreal
  (donnees.montreal.ca, ckan_montreal_), and City of Toronto
  (open.toronto.ca, ckan_toronto_). Every portal runs the same CKAN
  Action API software, but each deployment was independently verified
  live and genuinely differs in whether it uses tags/groups and in its
  language: BC, NWT, Yukon, and Toronto are English-only; Quebec and
  Montreal are French-only; only the federal portal is bilingual (and
  even there, ckan_list_organizations doesn't attach per-language
  fields, always returning its "English | French" combined title).
  Every ckan_ tool accepts lang: "en"|"fr" for interface consistency,
  but on a monolingual portal it is a documented no-op — read that
  portal's own module docstring before assuming a request will change
  what comes back.

Every StatCan tool accepts lang: "en"|"fr", but it only changes what
comes back for RDaaS tools and wds_get_full_table_download_csv, whose
upstream APIs are genuinely single-language per request. WDS and SDMX
metadata/data tools already return both languages in one response
(every field has an _en/_fr pair) — lang has no additional effect
there. Read docs://statcan/addressing and docs://statcan/gotchas
before working with StatCan's productId/vectorId/coordinate system or
its known API quirks. boc_ tools accept lang for consistency with
every other tool here, but it has no effect: the Bank of Canada Valet
API has no language dimension at all.
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
