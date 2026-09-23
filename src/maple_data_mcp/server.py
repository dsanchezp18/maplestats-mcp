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

import importlib
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers import FileSystemProvider
from fastmcp.server.transforms.search import BM25SearchTransform

from maple_data_mcp import __version__

MODULES_ROOT = Path(__file__).parent / "modules"

# Sent to every client on initialize, so it stays a short routing index
# (it used to be ~32 KB of per-source detail, re-read by the model on
# every session and repeatedly out of date). Per-source quirks live in
# each module's tool docstrings, its MODULE_DESCRIPTION (surfaced by
# docs://catalogue, which is generated and cannot drift), and its
# docs:// resources.
SERVER_INSTRUCTIONS = """
MapleData MCP -- one server for Canadian public data.

How to use it: call search_tools with a plain-language query (English or
French), then call_tool with a tool name it returns. Read docs://catalogue
for a bilingual one-line description of every module.

Sources, by tool-name prefix:
- Statistics Canada: wds_ (tables/cubes, vectors), sdmx_ (filtered
  series), rdaas_ (classifications, e.g. NAICS), statcan_census_profile_
  (2021), statcan_census_profile_2016_, statcan_census_profile_archive_
  (2001-2016 bulk links), statcan_daily_ (The Daily releases),
  statcan_indicators_, statcan_delta_ (daily bulk-update files),
  statcan_reference_ (definitions/methods, analysis), statcan_surveys_
  (survey directory + IMDB metadata), statcan_geo_ (census geography),
  statcan_sdg_ (Sustainable Development Goals hub).
- Bank of Canada Valet: boc_ (rates, FX, CPI, commodity prices).
- CMHC housing: cmhc_ (HMIP rental/starts tables), cmhc_dt_ (Excel data
  tables).
- ECCC weather/climate/hydrometric: eccc_.
- ISED: ised_corporations_ (federal corporations), ised_spectrum_
  (spectrum licences), ised_cipo_ (trademarks).
- IRCC Express Entry draws: ircc_. Elections Canada candidate financial
  returns: elections_financial_returns_. CRA digital economy platform
  operators registry: cra_digital_economy_registry_. Alberta Energy
  Regulator: aer_. BC Geographic Warehouse: bcgw_. NRCan burned areas:
  nrcan_nbac_.
- CKAN catalogues: ckan_ (federal open.canada.ca), ckan_ab_, ckan_bc_,
  ckan_on_, ckan_qc_, ckan_nt_, ckan_yt_, ckan_montreal_, ckan_toronto_,
  ckan_regina_. Most have *_datastore_search for row-level queries on
  DataStore-active resources.
- ArcGIS Hub portals (28 provinces, cities, regions): arcgis_hub_, with a
  `portal` argument -- arcgis_hub_list_portals lists the keys.
- Socrata portals (Nova Scotia, New Brunswick, Calgary, Edmonton,
  Winnipeg): socrata_, with a `portal` argument -- socrata_list_portals.
- Vancouver (Opendatasoft): opendatasoft_vancouver_. Newfoundland and
  Labrador: nl_opendata_.

Routing hints: many federal administrative series (IRCC permits, CRA
tax statistics and charities, OSFI bank returns, ISED insolvency data)
are ordinary open.canada.ca datasets -- use ckan_search_datasets with
fq="organization:<org>" (ircc, cra-arc, osfi-bsif, ic).

Language: most tools accept lang "en"|"fr". On single-language or
already-bilingual sources it is a documented no-op; each module's
docstring says which. Read docs://statcan/addressing and
docs://statcan/gotchas before StatCan work, and the docs://boc/,
docs://eccc/, and docs://cmhc/ resources for those sources.

Every result carries a provenance block (source URL, query time,
freshness, limits). Failures are raised as errors, never returned as
empty successes.
""".strip()


def _build_module_catalogue() -> str:
    """Render every module's MODULE_DESCRIPTION/MODULE_DESCRIPTION_FR pair
    as one bilingual reference doc — the only place those constants are
    actually surfaced (each module's own __init__.py declares them, but
    FileSystemProvider never reads them, so without this they'd be dead)."""
    lines = ["# MapleData MCP — module catalogue / catalogue des modules", ""]
    for module_dir in sorted(MODULES_ROOT.iterdir()):
        if not module_dir.is_dir() or module_dir.name.startswith("_"):
            continue
        module = importlib.import_module(f"maple_data_mcp.modules.{module_dir.name}")
        name = getattr(module, "MODULE_NAME", module_dir.name)
        description_en = getattr(module, "MODULE_DESCRIPTION", "")
        description_fr = getattr(module, "MODULE_DESCRIPTION_FR", "")
        lines.append(f"## {name}")
        lines.append(f"EN: {description_en}")
        lines.append(f"FR: {description_fr}")
        lines.append("")
    return "\n".join(lines)


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

    @mcp.resource("docs://catalogue")
    def module_catalogue_doc() -> str:
        """Bilingual (EN/FR) directory of every module this server exposes,
        by name and description — use this to see what a source covers in
        French before deciding which tools to call."""
        return _build_module_catalogue()

    return mcp


mcp = build_server()
