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
from fastmcp.server.providers.filesystem_discovery import (
    extract_components,
    import_module_from_file,
)
from fastmcp.server.transforms.search import BM25SearchTransform

from maplestats_mcp import __version__, config
from maplestats_mcp.shared import search
from maplestats_mcp.shared.timeouts import ToolTimeoutMiddleware

MODULES_ROOT = Path(__file__).parent / "modules"
_COMPONENT_FILES = frozenset({"tools.py", "resources.py", "prompts.py"})


class ModuleProvider(FileSystemProvider):
    """FileSystemProvider limited to tools.py, resources.py and prompts.py.

    The stock provider imports every .py file under its root, including
    each module's __tests__/ (which pulls in pytest) and client helpers:
    250 files and about 6 s of startup on 2026-09-24, long enough for MCP
    clients to time out while launching the server. The stock provider
    also only logs a warning when a file fails to import, so a broken
    module silently disappeared; here the failure is raised.
    """

    def _load_components(self) -> None:
        if self._loaded:
            self._components.clear()
        files = sorted(
            path
            for path in self._root.rglob("*.py")
            if path.name in _COMPONENT_FILES
            and "__pycache__" not in path.parts
            and "__tests__" not in path.parts
        )
        for file_path in files:
            module = import_module_from_file(file_path, provider_root=self._root)
            for component in extract_components(module):
                self._register_component(component)
        self._loaded = True


# Sent to every client on initialize, so it stays a short routing index
# (it used to be ~32 KB of per-source detail, re-read by the model on
# every session and repeatedly out of date). Per-source quirks live in
# each module's tool docstrings, its MODULE_DESCRIPTION (surfaced by
# docs://catalogue, which is generated and cannot drift), and its
# docs:// resources.
SERVER_INSTRUCTIONS = """
MapleStats MCP -- one server for Canadian public data.

How to use it: for a question that may need several sources, call
plan_query first; it returns the tools to call across agencies, in order,
with caveats on combining them. To find one tool, call search_tools with a
plain-language query (English or French). Then call_tool with the name.
After fetching data, offer the analyst scripts: reproduce_code (tool name
and arguments) returns R, Python, Stata and Julia code that retrieves and
cleans the same data. Read docs://catalogue
for a bilingual one-line description of every module.

Sources, by tool-name prefix:
- Statistics Canada: wds_ (tables/cubes, vectors), sdmx_ (filtered
  series), rdaas_ (classifications, e.g. NAICS), statcan_census_profile_
  (2021), statcan_census_profile_2016_, statcan_census_profile_archive_
  (2001-2016 bulk links), statcan_daily_ (The Daily releases),
  statcan_indicators_, statcan_delta_ (daily bulk-update files),
  statcan_reference_ (definitions/methods, analysis), statcan_surveys_
  (survey directory + IMDB metadata), statcan_geo_ (census geography),
  statcan_sdg_ (Sustainable Development Goals hub), statcan_pumf_ (public
  use microdata files: find, list downloads, read codebooks),
  statcan_census_tables_ (2006-2016 census cross-tabulations: CSV, SDMX,
  Beyond 20/20 IVT).
- Borealis (Canadian Dataverse): borealis_ (Beyond 20/20 IVT tables from
  university libraries: historical censuses, Business Patterns, LFS review).
- Bank of Canada Valet: boc_ (rates, FX, CPI, commodity prices).
- CMHC housing: cmhc_ (HMIP rental/starts tables), cmhc_dt_ (Excel data
  tables).
- ECCC weather/climate/hydrometric: eccc_.
- ISED: ised_corporations_ (federal corporations), ised_spectrum_
  (spectrum licences), ised_cipo_ (trademarks), ised_ip_horizons_
  (CIPO patent lookup and search, bulk IP files and data dictionaries),
  ised_clean_growth_ (federal cleantech investment 2016-2024).
- Competition Bureau merger reviews: competition_bureau_.
- Parliamentary Budget Officer publications and their tables (costings of
  bills and measures, economic and fiscal outlooks): pbo_.
- IRCC: ircc_ (Express Entry draws), ircc_monthly_ (monthly permanent and
  temporary residents, permits, asylum claims). Elections Canada candidate financial
  returns: elections_financial_returns_. CRA digital economy platform
  operators registry: cra_digital_economy_registry_. Alberta Energy
  Regulator: aer_. BC Geographic Warehouse: bcgw_. NRCan burned areas:
  nrcan_nbac_. CanadaBuys federal tenders and contract awards: canadabuys_.
  DFO tides and water levels: dfo_iwls_. Alberta Economic Dashboard:
  ab_economic_. Institut de la statistique du Quebec tables: isq_. NRCan energy use (Comprehensive Energy Use Database,
  household/commercial/industrial energy surveys): nrcan_energy_use_.
  Canada Energy Regulator (pipeline throughput, energy exports, tolls):
  cer_. GC InfoBase federal spending and results (Estimates, Public
  Accounts, program spending and FTEs): gc_infobase_. CIHI health-system
  indicators (Indicator Library): cihi_. NRCan geocoding and official
  place names: nrcan_geo_. Transport Canada vehicle recalls: tc_recalls_.
  Canada Gazette notices and regulations: gazette_.
  Earthquakes Canada event catalogue: earthquakes_. House of Commons bills,
  votes, MPs and Hansard (unofficial OpenParliament.ca): parliament_.
  Senate of Canada recorded votes: senate_.
- CKAN catalogues (federal open.canada.ca, Ontario, BC, Alberta, Quebec,
  NWT, Yukon, Montreal, Toronto, Regina): ckan_, with a `portal`
  argument -- ckan_list_portals lists the keys. ckan_datastore_search
  runs row-level queries on DataStore-active resources.
- ArcGIS Hub portals (33 provinces, cities, regions): arcgis_hub_, with a
  `portal` argument -- arcgis_hub_list_portals lists the keys.
- Socrata portals (Nova Scotia, New Brunswick, Calgary, Edmonton,
  Winnipeg): socrata_, with a `portal` argument -- socrata_list_portals.
- Vancouver (Opendatasoft): opendatasoft_vancouver_. Newfoundland and
  Labrador: nl_opendata_. Edmonton: eps_ (police
  occurrences), ets_ (real-time transit), epcor_ (water quality).

Routing hints: many federal administrative series (IRCC permits, CRA
tax statistics and charities, OSFI bank returns, ISED insolvency data)
(beyond ircc_monthly_) are ordinary open.canada.ca datasets -- use ckan_search_datasets with
portal="federal" and fq="organization:<org>" (cic for IRCC, cra-arc, osfi-bsif, ic).

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
    lines = ["# MapleStats MCP — module catalogue / catalogue des modules", ""]
    for module_dir in sorted(MODULES_ROOT.iterdir()):
        if not module_dir.is_dir() or module_dir.name.startswith("_"):
            continue
        module = importlib.import_module(f"maplestats_mcp.modules.{module_dir.name}")
        name = getattr(module, "MODULE_NAME", module_dir.name)
        description_en = getattr(module, "MODULE_DESCRIPTION", "")
        description_fr = getattr(module, "MODULE_DESCRIPTION_FR", "")
        lines.append(f"## {name}")
        lines.append(f"EN: {description_en}")
        lines.append(f"FR: {description_fr}")
        lines.append("")
    return "\n".join(lines)


def build_server() -> FastMCP:
    search.install()
    mcp = FastMCP("maplestats-mcp", version=__version__, instructions=SERVER_INSTRUCTIONS)
    for module_dir in sorted(MODULES_ROOT.iterdir()):
        if module_dir.is_dir() and not module_dir.name.startswith("_"):
            mcp.add_provider(ModuleProvider(root=module_dir))
    mcp.add_middleware(ToolTimeoutMiddleware(config.get_tool_timeout_seconds()))
    mcp.add_transform(
        BM25SearchTransform(
            max_results=5,
            always_visible=["search_tools", "plan_query"],
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
