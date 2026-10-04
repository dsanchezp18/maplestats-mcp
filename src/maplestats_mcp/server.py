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
from maplestats_mcp.shared.dereference import CachedDereferenceMiddleware
from maplestats_mcp.shared.timeouts import ToolTimeoutMiddleware
from maplestats_mcp.shared.usage import STATS, UsageMiddleware
from maplestats_mcp.shared.validation import ValidationErrorMiddleware

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
and arguments) returns R, Python, Stata and Julia code, and an Excel Power
Query, that retrieves and cleans the same data; reproduce_workbook returns
the rows as a formatted Excel workbook. Read docs://catalogue for a
bilingual one-line description of every module.

Sources, by tool-name prefix:
- Statistics Canada: wds_ (tables/cubes, vectors), sdmx_ (filtered
  series), sdmx_space_ (extra SDMX spaces: CCEI energy with ECCC emissions
  and NRCan indicators, and the shared space), rdaas_ (classifications,
  e.g. NAICS), statcan_census_profile_ (2021),
  statcan_census_profile_2016_, statcan_census_profile_archive_ (2001-2016
  bulk links), statcan_census_tables_ (2006-2016 cross-tabulations),
  statcan_daily_ (The Daily, release calendar), statcan_indicators_,
  statcan_delta_ (daily bulk-update files, vintage tables),
  statcan_reference_ (definitions, methods, analysis), statcan_surveys_
  (survey directory, IMDB metadata, RDC/RTRA holdings), statcan_geo_
  (census geography), statcan_sdg_ (SDG hub), statcan_pumf_ (public use
  microdata: find, downloads, codebooks), statcan_lode_ (open databases:
  healthcare, schools, buildings, addresses, proximity), cimt_ (trade by
  HS commodity, partner, province, monthly from 1988).
- Provincial and territorial statistics agencies: bc_stats_ (BC Stats
  Excel tables), isq_ (Institut de la statistique du Quebec),
  nl_stats_ (Newfoundland and Labrador Statistics Agency workbooks),
  yukon_stats_ (Yukon Bureau of Statistics tables), ab_economic_ (Alberta
  Economic Dashboard), ab_opendata_ (Open Alberta Excel and CSV files).
- Borealis (Canadian Dataverse): borealis_ (Beyond 20/20 tables from
  university libraries; ODESI DDI metadata, public files only).
- Bank of Canada Valet: boc_. CMHC housing: cmhc_ (HMIP tables), cmhc_dt_
  (Excel data tables). ECCC weather, climate, hydrometric: eccc_.
- ISED: ised_corporations_, ised_spectrum_, ised_cipo_ (trademarks),
  ised_ip_horizons_ (patents, bulk IP files), ised_clean_growth_.
- Federal agencies: competition_bureau_ (merger reviews), fcac_ (credit
  card and bank account comparisons), pbo_ (Parliamentary Budget Officer
  publications and tables), pmprb_ (patented medicine prices), Health
  Canada health products: hc_drug_ (Drug Product Database, DIN lookup),
  hc_nhp_ (licensed natural health products), hc_device_ (medical device
  licences), hc_vigilance_ (adverse reaction reports), ircc_
  (Express Entry rounds), ircc_monthly_ (monthly immigration counts),
  cra_digital_economy_registry_, gc_infobase_ (federal spending, FTEs),
  cihi_ (health-system indicators), phac_infobase_ (surveillance files),
  nrcan_geo_ (geocoding, place names), nrcan_energy_use_, nrcan_nbac_
  (burned areas), cer_ (Canada Energy Regulator), cgc_ (Canadian Grain
  Commission), cdc_ (Canadian Dairy Commission), cfia_ (reportable animal
  diseases), tc_recalls_ (vehicle recalls), recalls_ (all recalls and
  safety alerts), gazette_ (Canada Gazette), earthquakes_, dfo_iwls_
  (tides, water levels), nfd_
  (National Forestry Database), cwfis_ (wildfire hotspots, fire weather).
- Elections and Parliament: elections_results_ (federal results by
  riding), elections_financial_returns_ (candidate returns),
  elections_provincial_ (QC, AB, BC, SK results), ourcommons_ (official
  House of Commons MPs, roles, party standings), senate_ (Senate votes),
  represent_ (who represents a postal code; unofficial Open North).
- Provincial and municipal sources: aer_ (Alberta Energy Regulator),
  ab_wildfire_ (Alberta wildfire status), bcgw_ (BC Geographic
  Warehouse), bc_lobbyists_ (BC Registrar of Lobbyists), nl_opendata_,
  opendatasoft_vancouver_, eps_ (Edmonton police occurrences), ets_
  (Edmonton real-time transit), epcor_ (Edmonton water quality),
  electricity_ontario_ (IESO), electricity_quebec_ (Hydro-Quebec).
- Portal families, each with a `portal` argument and a list_portals tool:
  ckan_ (open.canada.ca, provincial and city CKAN catalogues;
  ckan_datastore_search for rows, ckan_describe_resource and
  ckan_read_resource for Excel and CSV files), arcgis_hub_ (provincial,
  city and regional ArcGIS Hub portals), socrata_ (Nova Scotia, New
  Brunswick, Calgary, Edmonton, Winnipeg).
- Static transit timetables: transit_, with an `agency` argument --
  transit_list_agencies, and transit_list_national_agencies for about 100
  more from StatCan's snapshot.

Routing hints: many federal administrative series (IRCC permits beyond
ircc_monthly_, CRA tax statistics and charities, OSFI bank returns, ISED
insolvency data, AAFC market prices, CFIA food testing) are ordinary
open.canada.ca datasets -- use ckan_search_datasets with portal="federal"
and fq="organization:<org>" (cic, cra-arc, osfi-bsif, ic, aafc-aac,
cfia-acia).

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
        # Replaced by CachedDereferenceMiddleware below: same output, but each
        # schema is dereferenced once instead of on every search_tools/call_tool.
        dereference_schemas=False,
    )
    mcp.add_middleware(CachedDereferenceMiddleware())
    for module_dir in sorted(MODULES_ROOT.iterdir()):
        if module_dir.is_dir() and not module_dir.name.startswith("_"):
            mcp.add_provider(ModuleProvider(root=module_dir))
    mcp.add_middleware(ValidationErrorMiddleware())
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
