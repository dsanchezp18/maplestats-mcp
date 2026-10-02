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

import base64
import importlib
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers import FileSystemProvider
from fastmcp.server.providers.filesystem_discovery import (
    extract_components,
    import_module_from_file,
)
from fastmcp.server.transforms.search import BM25SearchTransform
from fastmcp.tools import Tool
from mcp.types import Icon, ToolAnnotations

from maplestats_mcp import __version__, config
from maplestats_mcp.shared import search
from maplestats_mcp.shared.timeouts import ToolTimeoutMiddleware
from maplestats_mcp.shared.usage import STATS, UsageMiddleware

MODULES_ROOT = Path(__file__).parent / "modules"
_COMPONENT_FILES = frozenset({"tools.py", "resources.py", "prompts.py"})

# Every tool only reads public data, so the MCP behaviour hints are the
# same everywhere and set once here rather than on each @tool. Modules in
# _LOCAL_MODULES compute from bundled metadata without calling a source,
# so they are not open-world.
_LOCAL_MODULES = frozenset({"planner"})


def _read_only_annotations(open_world: bool) -> ToolAnnotations:
    return ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=open_world,
    )


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
        annotations = _read_only_annotations(self._root.name not in _LOCAL_MODULES)
        for file_path in files:
            module = import_module_from_file(file_path, provider_root=self._root)
            for component in extract_components(module):
                if isinstance(component, Tool) and component.annotations is None:
                    component.annotations = annotations
                # Directories such as Claude's require a human-readable title.
                if isinstance(component, Tool) and component.title is None:
                    component.title = component.name.replace("_", " ").capitalize()
                self._register_component(component)
        self._loaded = True


class AnnotatedBM25SearchTransform(BM25SearchTransform):
    """BM25 search whose synthetic search_tools/call_tool carry the same
    read-only hints as the module tools (call_tool can only reach them)."""

    def _make_search_tool(self) -> Tool:
        search_tool = super()._make_search_tool()
        search_tool.annotations = _read_only_annotations(open_world=False)
        search_tool.title = "Search tools"
        search_tool.description = _SEARCH_TOOLS_DESCRIPTION
        _describe_param(
            search_tool,
            "query",
            "What you need, in plain English or French, e.g. 'Calgary rent "
            "index' or 'taux de chômage Québec'. Topic words work better "
            "than tool names.",
        )
        return search_tool

    def _make_call_tool(self) -> Tool:
        call_tool = super()._make_call_tool()
        call_tool.annotations = _read_only_annotations(open_world=True)
        call_tool.title = "Call a tool"
        call_tool.description = _CALL_TOOL_DESCRIPTION
        _describe_param(
            call_tool,
            "name",
            "Exact tool name as returned by search_tools or plan_query, "
            "e.g. 'boc_get_observations'.",
        )
        _describe_param(
            call_tool,
            "arguments",
            "Object matching that tool's inputSchema from search_tools. "
            "Omit or pass {} for a tool with no required parameters.",
        )
        return call_tool


# Glama and similar registries grade these two synthetic tools on their
# descriptions alone; FastMCP's defaults say what they do but not when to
# pick each one, or what happens on a bad name.
_SEARCH_TOOLS_DESCRIPTION = """\
Find the right data tool for one specific need by plain-language search.

Use for: locating a tool when you know roughly what data you want
(a StatCan table, Bank of Canada series, a city's open-data portal).
Returns the best-matching tool definitions, ranked by relevance, each
with its name, description and full input schema, in the same format
as list_tools. Read-only; it searches this server's catalogue only and
calls no external API.
Use plan_query instead when a question may span several sources or you
do not know where to start; use call_tool to run a tool once you have
its name. Queries in English or French both work. An empty result
means no tool matched: rephrase with topic words (e.g. 'housing
starts' rather than 'CMHC table').
"""

_CALL_TOOL_DESCRIPTION = """\
Run one data tool found through search_tools or plan_query.

Use for: executing a tool by exact name with arguments that match the
inputSchema search_tools returned for it. Every reachable tool is
read-only: it fetches public data from the upstream agency (StatCan,
Bank of Canada, open-data portals) and changes nothing. Returns that
tool's typed result, including a provenance block (source, URL, query
time, freshness).
Errors come back as MCP tool errors, not as data: an unknown or
misspelled name raises 'Unknown tool' (search again for the exact
name), invalid arguments raise a validation error naming the field,
and upstream outages or empty matches raise a typed error explaining
what to change. search_tools, call_tool and plan_query cannot be called
through it; call them directly. Tool calls are subject to the server's
timeout (MAPLE_TOOL_TIMEOUT_SECONDS, default 120).
"""


def _describe_param(tool: Tool, param: str, description: str) -> None:
    props = tool.parameters.get("properties", {})
    if param in props:
        props[param]["description"] = description


# Sent to every client on initialize, so it stays a short routing index
# (it used to be ~32 KB of per-source detail, re-read by the model on
# every session and repeatedly out of date). Per-source quirks live in
# each module's tool docstrings, its MODULE_DESCRIPTION (surfaced by
# docs://catalogue, which is generated and cannot drift), and its
# docs:// resources.
SERVER_INSTRUCTIONS = """
MapleStats MCP -- one server for Canadian open data.

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
  (2001-2016 bulk links), statcan_daily_ (The Daily releases, release calendar),
  statcan_indicators_, statcan_delta_ (daily bulk-update files),
  statcan_reference_ (definitions/methods, analysis), statcan_surveys_
  (survey directory + IMDB metadata, RDC and RTRA microdata holdings), statcan_geo_ (census geography),
  statcan_sdg_ (Sustainable Development Goals hub), statcan_pumf_ (public
  use microdata files: find, list downloads, read codebooks),
  statcan_census_tables_ (2006-2016 census cross-tabulations: CSV, SDMX,
  Beyond 20/20 IVT), cimt_ (exports and imports by HS commodity,
  partner, US state and province, monthly from 1988).
- Borealis (Canadian Dataverse): borealis_ (Beyond 20/20 IVT tables from
  university libraries: historical censuses, Business Patterns, LFS review;
  ODESI DDI metadata for StatCan PUMFs and polls, public files only).
- Bank of Canada Valet: boc_ (rates, FX, CPI, commodity prices).
- CMHC housing: cmhc_ (HMIP rental/starts tables), cmhc_dt_ (Excel data
  tables).
- ECCC weather/climate/hydrometric: eccc_.
- ISED: ised_corporations_ (federal corporations), ised_spectrum_
  (spectrum licences), ised_cipo_ (trademarks), ised_ip_horizons_
  (CIPO patent lookup and search, bulk IP files and data dictionaries),
  ised_clean_growth_ (federal cleantech investment 2016-2024).
- Competition Bureau merger reviews: competition_bureau_.
- FCAC credit card and bank account comparison tools (fees, interest
  rates, rewards, low-cost accounts): fcac_.
- Parliamentary Budget Officer publications and their tables (costings of
  bills and measures, economic and fiscal outlooks) and its information
  requests to departments: pbo_.
- Patented Medicine Prices Review Board annual report tables (patented
  drug price index, international price ratios, sales, R&D) and patented
  medicines lists: pmprb_.
- IRCC: ircc_ (Express Entry draws), ircc_monthly_ (monthly permanent and
  temporary residents, permits, asylum claims). Elections Canada candidate financial
  returns: elections_financial_returns_. Federal general election results by riding:
  elections_results_. Provincial election results (Quebec, Alberta, British
  Columbia, Saskatchewan): elections_provincial_. CRA digital economy platform
  operators registry: cra_digital_economy_registry_. Alberta Energy
  Regulator: aer_. BC Geographic Warehouse: bcgw_. NRCan burned areas:
  nrcan_nbac_. Wildfire hotspots, perimeters, fire weather (FWI), large fires and situation reports: cwfis_. Alberta Wildfire live
  status (fires, perimeters, fire danger, fire bans): ab_wildfire_. National Forestry Database (provincial fires,
  harvest, planting, pests, timber revenues): nfd_. CanadaBuys federal tenders and contract awards: canadabuys_.
  BC Registrar of Lobbyists (registrations, lobbying activity reports):
  bc_lobbyists_. DFO tides and water levels: dfo_iwls_. Alberta Economic Dashboard:
  ab_economic_. Institut de la statistique du Quebec tables: isq_. NRCan energy use (Comprehensive Energy Use Database,
  household/commercial/industrial energy surveys): nrcan_energy_use_.
  Canada Energy Regulator (pipeline throughput, energy exports, tolls):
  cer_. Canadian Grain Commission (weekly grain deliveries, stocks and
  terminal exports; monthly grain exports by destination): cgc_. GC
  InfoBase federal spending and results (Estimates, Public Accounts,
  program spending and FTEs): gc_infobase_. CIHI health-system
  indicators (Indicator Library): cihi_. PHAC Health Infobase surveillance
  files (FluWatch+, wastewater, opioid harms, measles, TB): phac_infobase_.
  NRCan geocoding and official place names: nrcan_geo_. Transport Canada vehicle recalls: tc_recalls_.
  Recalls and safety alerts (Health Canada, CFIA food, all agencies): recalls_.
  Canadian Dairy Commission (milk component and butter support prices,
  total quota, milk production and class sales): cdc_. CFIA reportable
  animal diseases (yearly counts, detections, avian influenza infected
  premises): cfia_.
  Canada Gazette notices and regulations: gazette_.
  Earthquakes Canada event catalogue: earthquakes_. House of Commons bills,
  votes, MPs and Hansard (unofficial OpenParliament.ca): parliament_.
  Senate of Canada recorded votes: senate_. Who represents a postal code or
  point (MP, MLA, mayor) and electoral districts with licences (unofficial
  Open North Represent): represent_.
- CKAN catalogues (federal open.canada.ca, Ontario, BC, Alberta, Quebec,
  NWT, Yukon, Montreal, Toronto, Regina): ckan_, with a `portal`
  argument -- ckan_list_portals lists the keys. ckan_datastore_search
  runs row-level queries on DataStore-active resources.
- ArcGIS Hub portals (80 provinces, cities, regions): arcgis_hub_, with a
  `portal` argument -- arcgis_hub_list_portals lists the keys.
- Socrata portals (Nova Scotia, New Brunswick, Calgary, Edmonton,
  Winnipeg): socrata_, with a `portal` argument -- socrata_list_portals.
- Vancouver (Opendatasoft): opendatasoft_vancouver_. Newfoundland and
  Labrador: nl_opendata_. Edmonton: eps_ (police
  occurrences), ets_ (real-time transit), epcor_ (water quality).
  Static transit timetables (TTC, STM buses, OC Transpo, Calgary Transit,
  VIA Rail, GO/UP Express, 12 BC Transit systems):
  transit_, with an `agency` argument -- transit_list_agencies. About 100
  more agencies (StatCan's 2025 snapshot, agency "statcan:<id>"):
  transit_list_national_agencies.
  Electricity demand, generation and prices: electricity_ontario_ (IESO),
  electricity_quebec_ (Hydro-Quebec).

Routing hints: many federal administrative series (IRCC permits, CRA
tax statistics and charities, OSFI bank returns, ISED insolvency data)
(beyond ircc_monthly_) are ordinary open.canada.ca datasets -- use ckan_search_datasets with
portal="federal" and fq="organization:<org>" (cic for IRCC, cra-arc, osfi-bsif, ic).
AAFC market data (red meat, poultry and eggs, dairy, horticulture prices) and
CFIA rabies, aquatic animal disease and food testing data are there too:
aafc-aac, cfia-acia (terrestrial reportable diseases and avian influenza: cfia_).

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
    icon_png = (Path(__file__).parent / "assets" / "favicon.png").read_bytes()
    icon = Icon(
        src="data:image/png;base64," + base64.b64encode(icon_png).decode("ascii"),
        mime_type="image/png",
        sizes=["256x256"],
    )
    mcp = FastMCP(
        "maplestats-mcp",
        version=__version__,
        instructions=SERVER_INSTRUCTIONS,
        website_url="https://dsanchezp18.github.io/maplestats-mcp/",
        icons=[icon],
    )
    for module_dir in sorted(MODULES_ROOT.iterdir()):
        if module_dir.is_dir() and not module_dir.name.startswith("_"):
            mcp.add_provider(ModuleProvider(root=module_dir))
    mcp.add_middleware(ToolTimeoutMiddleware(config.get_tool_timeout_seconds()))
    if config.get_usage_stats_enabled():
        mcp.add_middleware(UsageMiddleware(STATS))
    mcp.add_transform(
        AnnotatedBM25SearchTransform(
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
