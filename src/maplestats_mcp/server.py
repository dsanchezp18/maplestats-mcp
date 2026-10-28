"""The FastMCP server instance: module auto-registration + tool search.

One provider per modules/* subdirectory, which collects every
@tool/@resource/@prompt-decorated function in the module's tools.py,
resources.py and prompts.py files, sub-API folders included
(modules/statcan/{wds,sdmx,rdaas}/). Folders starting with "_" are
skipped, so modules/_example/ (the template new sources copy) never
registers its demo tools live.

A module in tool_catalogue.json gets a LazyModuleProvider, which lists
its tools from the catalogue and imports its code on first use (see
catalogue.py); a module missing from it gets a ModuleProvider, which
imports it at startup.

Only public fastmcp APIs are used here, plus the provider hooks fastmcp
documents for overriding (`_list_tools`, `_get_tool` and their resource
and prompt counterparts); tests/test_fastmcp_api.py checks both, so a
fastmcp upgrade that moves one fails there by name.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import inspect
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.exceptions import NotFoundError
from fastmcp.prompts.base import Prompt
from fastmcp.resources.base import Resource
from fastmcp.resources.template import ResourceTemplate
from fastmcp.server.context import Context
from fastmcp.server.providers.local_provider import LocalProvider
from fastmcp.server.transforms import GetToolNext
from fastmcp.server.transforms.search import (
    BM25SearchTransform,
    SearchResultSerializer,
    serialize_tools_for_output_json,
)
from fastmcp.tools import Tool
from fastmcp.tools.base import ToolResult
from fastmcp.utilities.components import FastMCPComponent
from fastmcp.utilities.versions import VersionSpec
from mcp.types import Icon, ToolAnnotations

from maplestats_mcp import __version__, config
from maplestats_mcp.catalogue import (
    EXTRA_FILES,
    MODULES_ROOT,
    TOOL_FILES,
    TOOL_SWITCHES,
    CatalogueTool,
    component_files,
    import_components,
    module_dirs,
    read_catalogue,
)
from maplestats_mcp.shared import search, semantic
from maplestats_mcp.shared.breaker import render_status
from maplestats_mcp.shared.dereference import CachedDereferenceMiddleware
from maplestats_mcp.shared.private_logs import configure_private_logs
from maplestats_mcp.shared.response_budget import ResponseBudgetMiddleware
from maplestats_mcp.shared.timeouts import ToolTimeoutMiddleware
from maplestats_mcp.shared.usage import STATS, UsageMiddleware
from maplestats_mcp.shared.validation import CallLanguageMiddleware, ValidationErrorMiddleware

# Data tools read public sources. The workbook export can save a local file;
# its own annotations and the call_tool wrapper describe that exception. Modules in
# _LOCAL_MODULES compute from bundled metadata without calling a source,
# so they are not open-world.
_LOCAL_MODULES = frozenset({"planner"})

_logger = logging.getLogger("maplestats_mcp.server")

# Listed directly, so search_tools never returns or indexes them.
SEARCH_ALWAYS_VISIBLE = ("search_tools", "plan_query")


def _read_only_annotations(open_world: bool) -> ToolAnnotations:
    return ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=open_world,
    )


def _export_annotations() -> ToolAnnotations:
    local_exports = config.get_transport() == "stdio"
    return ToolAnnotations(
        read_only_hint=not local_exports,
        destructive_hint=local_exports,
        idempotent_hint=not local_exports,
        open_world_hint=True,
    )


def _prepare(component: FastMCPComponent, annotations: ToolAnnotations) -> None:
    """Server-wide tool settings, the same for a catalogue entry and its real tool."""
    if not isinstance(component, Tool):
        return
    STATS.register_tools((component.name,))
    if component.name == "reproduce_workbook":
        component.annotations = _export_annotations()
    elif component.annotations is None:
        component.annotations = annotations
    # Directories such as Claude's require a human-readable title.
    if component.title is None:
        component.title = component.name.replace("_", " ").capitalize()


def _module_annotations(root: Path) -> ToolAnnotations:
    return _read_only_annotations(root.name not in _LOCAL_MODULES)


def _register(
    provider: LocalProvider, component: FastMCPComponent, annotations: ToolAnnotations
) -> None:
    _prepare(component, annotations)
    if isinstance(component, Tool):
        provider.add_tool(component)
    elif isinstance(component, ResourceTemplate):
        provider.add_template(component)
    elif isinstance(component, Resource):
        provider.add_resource(component)
    elif isinstance(component, Prompt):
        provider.add_prompt(component)


class ModuleProvider(LocalProvider):
    """A module's tools.py, resources.py and prompts.py, imported at startup.

    LazyModuleProvider is the default whenever the catalogue lists the module.
    This used to be a FileSystemProvider with its private loader replaced; it
    needs nothing of that class but the import, which catalogue.py does.
    """

    def __init__(self, root: Path) -> None:
        super().__init__(on_duplicate="replace")
        # Resolved, as FileSystemProvider did: the import names modules relative to it.
        self._root = Path(root).resolve()
        annotations = _module_annotations(self._root)
        for component in import_components(self._root, component_files(self._root)):
            _register(self, component, annotations)

    def __repr__(self) -> str:
        return f"ModuleProvider(root={self._root!r})"


class LazyModuleProvider(LocalProvider):
    """A module whose tools are listed from the catalogue and imported on first use.

    Only the provider hooks FastMCP documents for overriding are replaced
    (`_list_tools`, `_get_tool` and their resource and prompt
    counterparts), the same ones FileSystemProvider overrides for its
    reload mode. Listing and search read catalogue entries; a call resolves
    its tool through `_get_tool`, which imports the module's tools.py files
    the first time. resources.py and prompts.py are imported apart, on the
    first resource or prompt request, so listing resources does not import
    every module's tools.
    """

    def __init__(self, root: Path, entry: dict[str, Any]) -> None:
        super().__init__(on_duplicate="replace")
        self._root = root
        self._annotations = _module_annotations(root)
        files = [root / name for name in entry["files"]]
        self._tool_files = [path for path in files if path.name in TOOL_FILES]
        self._extra_files = [path for path in files if path.name in EXTRA_FILES]
        self._tools_loaded = False
        self._extras_loaded = not self._extra_files
        self._listed: list[Tool] = []
        for item in entry["tools"]:
            switch = TOOL_SWITCHES.get(item["name"])
            if switch is not None and not switch():
                continue
            listed = CatalogueTool.model_validate(item)
            _prepare(listed, self._annotations)
            self._listed.append(listed)
        self._names = frozenset(tool.name for tool in self._listed)

    def _import(self, files: list[Path]) -> None:
        for component in import_components(self._root, files):
            _register(self, component, self._annotations)

    def _load_tools(self) -> None:
        # Synchronous on purpose: no other request runs between the check and
        # the flag, so two first calls cannot import the module twice.
        if not self._tools_loaded:
            self._import(self._tool_files)
            self._tools_loaded = True

    def _load_extras(self) -> None:
        if not self._extras_loaded:
            self._import(self._extra_files)
            self._extras_loaded = True

    async def _list_tools(self) -> Sequence[Tool]:
        return list(self._listed)

    async def _get_tool(self, name: str, version: VersionSpec | None = None) -> Tool | None:
        # Every provider is asked for every name, so only this module's own
        # names may import it.
        if name not in self._names:
            return None
        self._load_tools()
        return await super()._get_tool(name, version)

    async def _list_resources(self) -> Sequence[Resource]:
        self._load_extras()
        return await super()._list_resources()

    async def _get_resource(self, uri: str, version: VersionSpec | None = None) -> Resource | None:
        self._load_extras()
        return await super()._get_resource(uri, version)

    async def _list_resource_templates(self) -> Sequence[ResourceTemplate]:
        self._load_extras()
        return await super()._list_resource_templates()

    async def _get_resource_template(
        self, uri: str, version: VersionSpec | None = None
    ) -> ResourceTemplate | None:
        self._load_extras()
        return await super()._get_resource_template(uri, version)

    async def _list_prompts(self) -> Sequence[Prompt]:
        self._load_extras()
        return await super()._list_prompts()

    async def _get_prompt(self, name: str, version: VersionSpec | None = None) -> Prompt | None:
        self._load_extras()
        return await super()._get_prompt(name, version)

    async def get_tasks(self) -> Sequence[FastMCPComponent]:
        # The server asks for task components when it starts serving; the
        # catalogue builder refuses task components, so there are none, and
        # answering from the default would import every module.
        return []

    def __repr__(self) -> str:
        return f"LazyModuleProvider(root={self._root!r})"


class AnnotatedBM25SearchTransform(BM25SearchTransform):
    """search_tools and call_tool, built here from public fastmcp APIs only.

    Until 2026-10 this overrode BM25SearchTransform's private `_search`,
    `_make_search_tool` and `_make_call_tool`, which capped fastmcp below 4.2.
    It now overrides only the public Transform hooks (`transform_tools`,
    `get_tool`) and reads the catalogue through CatalogTransform's public
    `get_tool_catalog`; nothing of BM25SearchTransform runs. It stays a
    subclass so `isinstance(t, BM25SearchTransform)` still finds it
    (scripts/build_site.py does), and keeps the attributes that script reads
    (`_index.k1`, `_index.b`, `_max_results`, `_always_visible`) as its own.

    The ranking is fastmcp's BM25 with shared/search.py's tokenizer, rebuilt
    on a catalogue change the same way, with two additions measured in
    tests/discovery_benchmark/phase2.md: exact identifiers (a tool name, a
    StatCan table or vector number) lift the tools that take them, and
    MAPLE_SEARCH=hybrid fuses BM25 with the optional semantic index. The
    synthetic tools' schemas and search_tools' output keep fastmcp's format.
    """

    def __init__(
        self,
        *,
        max_results: int = 5,
        always_visible: list[str] | None = None,
        search_tool_name: str = "search_tools",
        call_tool_name: str = "call_tool",
        search_result_serializer: SearchResultSerializer | None = None,
        mode: str | None = None,
    ) -> None:
        # The base's own settings are never read; ours are set below.
        super().__init__()
        self._max_results = max_results
        self._always_visible = set(always_visible or [])
        self._search_tool_name = search_tool_name
        self._call_tool_name = call_tool_name
        self._serializer: SearchResultSerializer = (
            search_result_serializer or serialize_tools_for_output_json
        )
        self._index = search.ScoredBM25Index()
        self._indexed: list[Tool] = []
        self._last_hash = ""
        self._mode = mode or semantic.search_mode()
        self._semantic: semantic.SemanticIndex | None = None
        self._semantic_tried = False
        self._semantic_rows: list[int | None] = []

    # The two Transform hooks fastmcp calls: list the pinned and synthetic
    # tools, and resolve the synthetic names (every other name goes on).

    async def transform_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        pinned = [t for t in tools if t.name in self._always_visible]
        return [*pinned, self._make_search_tool(), self._make_call_tool()]

    async def get_tool(
        self, name: str, call_next: GetToolNext, *, version: VersionSpec | None = None
    ) -> Tool | None:
        if name == self._search_tool_name:
            return self._make_search_tool()
        if name == self._call_tool_name:
            return self._make_call_tool()
        return await call_next(name, version=version)

    async def searchable_tools(self, ctx: Context) -> list[Tool]:
        """The catalogue search_tools ranks: every tool the caller may see, less the pinned."""
        tools = await self.get_tool_catalog(ctx)
        return [t for t in tools if t.name not in self._always_visible]

    def _load_semantic(self) -> None:
        # Loaded on the first search, not at startup: the model costs about two
        # seconds and 220 MB, which a bm25 server, or one never searched, never pays.
        self._semantic_tried = True
        try:
            self._semantic = semantic.SemanticIndex.load(semantic.index_dir())
        except (semantic.SemanticUnavailable, OSError, ValueError, KeyError) as exc:
            _logger.warning("MAPLE_SEARCH=hybrid, but searching by BM25 only: %s", exc)

    async def _search(self, tools: Sequence[Tool], query: str) -> Sequence[Tool]:
        texts = [search.searchable_text(t) for t in tools]
        current_hash = hashlib.sha256(json.dumps(sorted(texts)).encode()).hexdigest()
        if current_hash != self._last_hash:
            index = search.ScoredBM25Index(self._index.k1, self._index.b)
            index.build(texts)
            self._index, self._indexed, self._last_hash = index, list(tools), current_hash
            self._semantic_rows = []
        scores = self._index.scores(query)
        if self._mode == "hybrid":
            if not self._semantic_tried:
                self._load_semantic()
            if self._semantic is not None:
                if not self._semantic_rows:
                    self._semantic_rows = self._semantic.rows(
                        [(t.name, t.description or "") for t in self._indexed]
                    )
                    stale = self._semantic_rows.count(None)
                    if stale:
                        _logger.warning(
                            "semantic index lacks %d of %d tools (new or changed since the "
                            "build); they are ranked by BM25 only",
                            stale,
                            len(self._indexed),
                        )
                ranking = self._semantic.ranking(query, self._semantic_rows, semantic.FUSION_DEPTH)
                scores = semantic.fuse(scores, ranking)
        scores = search.apply_boosts(scores, search.identifier_boosts(query, self._indexed))
        # The catalog is deduplicated by name; resolve the current version's schema.
        by_name = {t.name: t for t in tools}
        return [
            by_name[self._indexed[i].name] for i in search.top_indices(scores, self._max_results)
        ]

    def _make_search_tool(self) -> Tool:
        transform = self

        # The parameter and return annotations are fastmcp's, so the input and
        # output schemas clients already know stay the same.
        async def search_tools(
            query: Annotated[
                str,
                "What you need, in plain English or French, e.g. 'Calgary rent "
                "index' or 'taux de chômage Québec'. Topic words work better "
                "than tool names.",
            ],
            ctx: Context = None,  # type: ignore[assignment]  # fastmcp injects it
        ) -> str | list[dict[str, Any]]:
            results = await transform._search(await transform.searchable_tools(ctx), query)
            rendered = transform._serializer(results)
            return await rendered if inspect.isawaitable(rendered) else rendered

        return Tool.from_function(
            fn=search_tools,
            name=self._search_tool_name,
            title="Search tools",
            description=_SEARCH_TOOLS_DESCRIPTION,
            annotations=_read_only_annotations(open_world=False),
        )

    def _make_call_tool(self) -> Tool:
        transform = self

        async def call_tool(
            name: Annotated[
                str,
                "Exact tool name as returned by search_tools or plan_query, "
                "e.g. 'boc_get_observations'.",
            ],
            arguments: Annotated[
                dict[str, Any] | None,
                "Object matching that tool's inputSchema from search_tools. "
                "Omit or pass {} for a tool with no required parameters.",
            ] = None,
            ctx: Context = None,  # type: ignore[assignment]  # fastmcp injects it
        ) -> ToolResult:
            if name in {transform._call_tool_name, transform._search_tool_name}:
                raise ValueError(
                    f"'{name}' is a synthetic search tool and cannot be called via the "
                    "call_tool proxy"
                )
            # As fastmcp's proxy does: the name comes from the model, so it may
            # reach only what the model could have found through search_tools.
            if not any(t.name == name for t in await transform.get_tool_catalog(ctx)):
                raise NotFoundError(f"Unknown tool: {name!r}")
            return await ctx.fastmcp.call_tool(name, arguments)

        return Tool.from_function(
            fn=call_tool,
            name=self._call_tool_name,
            title="Call a tool",
            description=_CALL_TOOL_DESCRIPTION,
            annotations=_export_annotations(),
        )


async def searchable_tools(server: FastMCP) -> list[Tool]:
    """Every tool `server`'s search_tools ranks, read the way search_tools reads them."""
    transform = next(t for t in server.transforms if isinstance(t, AnnotatedBM25SearchTransform))
    async with Context(fastmcp=server) as ctx:
        return await transform.searchable_tools(ctx)


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
inputSchema search_tools returned for it. Data tools read public sources
(StatCan, Bank of Canada, open-data portals). reproduce_workbook can save
an Excel file on a local stdio server; hosted exports return base64. Returns that
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
For a whole StatCan table, or hundreds of series, use
wds_get_full_table_download (a CSV link: the rows are not returned) rather
than the vector tools, which return every observation inline and suit a
handful of series.
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
  statcan_census_profile_archive_ (2001-2016 bulk links),
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
  yukon_stats_ (Yukon Bureau of Statistics tables), nwt_stats_ (NWT
  Bureau of Statistics workbooks), ab_economic_ (Alberta
  Economic Dashboard), ab_opendata_ (Open Alberta Excel and CSV files).
- Borealis (Canadian Dataverse): borealis_ (Beyond 20/20 tables from
  university libraries; ODESI DDI metadata, public files only).
- Bank of Canada Valet: boc_. CMHC housing: cmhc_ (HMIP tables), cmhc_dt_
  (Excel data tables). CREA MLS Home Price Index: crea_ (links, terms and
  attribution only, no values). ECCC weather, climate, hydrometric: eccc_;
  gridded climate projections (CMIP6/CMIP5, SSP/RCP): eccc_coverages_.
  ECCC Data Catalogue files (browse, search, read CSV/Excel; NPRI and GHGRP
  facility lookups): eccc_datamart_.
- World Bank WDI, Canada and G7/OECD peers: worldbank_. BIS statistics
  (policy rates, debt service ratios, credit, house prices, banking and
  payment statistics), Canada and peers: bis_.
- ISED: ised_corporations_, ised_spectrum_, ised_cipo_ (trademarks),
  ised_ip_horizons_ (patents, bulk IP files), ised_clean_growth_.
- Federal agencies: finance_frt_ (Fiscal Reference Tables: federal and
  provincial revenue, spending, deficits, debt), finance_fiscal_monitor_
  (monthly federal results), competition_bureau_ (merger reviews), fcac_ (credit
  card and bank account comparisons), pbo_ (Parliamentary Budget Officer
  publications and tables), pmprb_ (patented medicine prices), telecom_
  (CRTC mobile and Internet plan prices, telecom market indicators), pmra_
  (pesticide products, residue limits), Health Canada health products:
  hc_drug_ (Drug Product Database, DIN lookup), hc_nhp_ (licensed natural
  health products), hc_device_ (medical device licences), hc_vigilance_
  (adverse reaction reports), ircc_
  (Express Entry rounds), ircc_monthly_ (monthly immigration counts),
  cra_digital_economy_registry_, cra_charities_ (registered charities, directors),
  gc_infobase_ (federal spending, FTEs),
  cihi_ (health-system indicators), phac_infobase_ (surveillance files),
  nrcan_geo_ (geocoding, place names), nrcan_energy_use_, nrcan_nbac_
  (burned areas), nrcan_minerals_ (annual mineral production by
  province), cer_ (Canada Energy Regulator), cgc_ (Canadian Grain
  Commission), cdc_ (Canadian Dairy Commission), cfia_ (reportable animal
  diseases), tc_recalls_ (vehicle recalls), recalls_ (all recalls and
  safety alerts), cbsa_ (current border wait times), cbsa_tariff_
  (Customs Tariff duty rates by tariff item), gazette_ (Canada
  Gazette), earthquakes_, dfo_iwls_
  (tides, water levels), nfd_
  (National Forestry Database), cwfis_ (wildfire hotspots, fire weather),
  isc_ (First Nation profiles, registered population, drinking water
  advisories).
- Elections and Parliament: elections_results_ (federal results by
  riding), elections_financial_returns_ (candidate returns),
  elections_provincial_ (QC, AB, BC, SK, MB results), ourcommons_ (official
  House of Commons MPs, roles, party standings), senate_ (Senate votes),
  represent_ (who represents a postal code; unofficial Open North).
- Provincial and municipal sources: aer_ (Alberta Energy Regulator),
  ab_wildfire_ (Alberta wildfire status), bc_env_ (BC air quality,
  AQHI, snow, groundwater wells, provincial streamflow), bcgw_ (BC Geographic
  Warehouse), bc_lobbyists_ (BC Registrar of Lobbyists), drivebc_ (BC
  highway road events and closures), nl_opendata_,
  opendatasoft_vancouver_, eps_ (Edmonton police occurrences), ets_
  (Edmonton real-time transit), epcor_ (Edmonton water quality),
  electricity_ontario_ (IESO), electricity_quebec_ (Hydro-Quebec, including water flows at its
  dams), oeb_
  (Ontario Energy Board: utility RRR filings, reliability, rates), on_fir_
  (Ontario municipal Financial Information Return: revenue, expenses,
  taxes, reserves, debt by municipality, 2000 on).
- Portal families, each with a `portal` argument and a list_portals tool:
  ckan_ (open.canada.ca, provincial and city CKAN catalogues;
  ckan_datastore_search for rows, ckan_describe_resource and
  ckan_read_resource for Excel and CSV files), arcgis_hub_ (provincial,
  city and regional ArcGIS Hub portals), socrata_ (Nova Scotia, New
  Brunswick, Calgary, Edmonton, Winnipeg).
- Static transit timetables: transit_, with an `agency` argument --
  transit_list_agencies (including exo, RTC, STL, STS and STQ ferries in
  Quebec), and transit_list_national_agencies for about 100 more from
  StatCan's snapshot.

Routing hints: many federal administrative series (IRCC permits beyond
ircc_monthly_, CRA tax statistics and charities, OSFI bank returns, ISED
insolvency data, AAFC market prices, CFIA food testing) are ordinary
open.canada.ca datasets -- use ckan_search_datasets with portal="federal"
and fq="organization:<org>" (cic, cra-arc, osfi-bsif, ic, aafc-aac,
cfia-acia).

Language: every tool accepts lang "en"|"fr". On single-language or
already-bilingual sources it is a documented no-op; each module's
docstring says which. Read docs://statcan/addressing and
docs://statcan/gotchas before StatCan work, and the docs://boc/,
docs://eccc/, and docs://cmhc/ resources for those sources.

Every result carries a provenance block (source URL, query time,
freshness, limits). Failures are raised as errors, never returned as
empty successes.

If a tool misbehaves (an error that looks like a server fault, data that
contradicts its provenance or the source, a response that does not match
its description), tell the user and offer to draft a report for the
maintainers, who appreciate them. Say the user will not have to write or
file it by hand: you can submit it to GitHub for them, after they have read
and approved the exact text. Read docs://report-issue for the template and
the steps. Never file anything before the user approves the final text.
""".strip()


REPORT_ISSUE_TEMPLATE = """\
# Reporting a MapleStats MCP issue

Offer this when something looks wrong: an error that looks like a server
fault rather than bad input, data that contradicts its provenance block or
the source itself, a response shape that does not match the tool's
description, or a source that appears to have moved or changed. Do not offer
it for the user's own typos, empty results that are correct, or a source that
is temporarily down and returned the typed upstream-unavailable error.

Ask once, in a sentence: "That looks like a bug in the server. Want me to
report it to the maintainers? You won't need to write or file anything
yourself; I'll draft it, show you the exact text, and submit it to GitHub
only after you approve it." On a yes, fill in the template below from what
you know about the failed call. The conversation may hold personal details,
file paths or keys: leave out anything the report does not need.

Then show the complete final title and body in one short block and STOP.
Do not file in the same turn. Wait for the user's next message: it must
approve that exact text (or ask for changes). If they ask for edits, redraft,
show the whole report again, and wait again. File only after an explicit
approval of the text as last shown. A yes to the question above is not
approval of the text.

1. If a GitHub tool or the `gh` CLI is available and signed in, create the
   issue in dsanchezp18/maplestats-mcp with the label `bug` (for `gh`:
   `gh issue create --repo dsanchezp18/maplestats-mcp --label bug --title
   "<tool name>: <short symptom>" --body-file <file>`). Search open issues
   first (`gh issue list --search "<tool name>"`) and comment on a matching
   one instead of opening a duplicate. File the approved text unchanged.
2. Otherwise give the user one prefilled link to click:
   https://github.com/dsanchezp18/maplestats-mcp/issues/new?template=bug_report.yml&title=<url-encoded title>
   and the body text to paste. Never put the report in the URL beyond the title.
3. Return the issue link. If filing fails, say so and fall back to step 2.

The user's approval covers this one report only. Never file, comment or post
anything without it, and never as a side effect of another task.

## Template

**Tool name:** <exact tool name, e.g. statcan_get_data_from_vectors>

**Arguments and result:**
- Arguments (as passed to call_tool): <JSON>
- What came back: <the error text, or a short snippet of the response>

**What you expected:** <one or two sentences, with the source's own figure or
page if it was checked>

**Why it looks wrong:** <the evidence: provenance as-of date versus the
source, a field that is null or missing, a count that does not match>

**Version:** <output of `uvx maplestats-mcp --version`, or the server version>

## Before sending

- Keep only the tool call and the response. Strip personal identifiers, file
  paths, keys and the rest of the conversation.
- Say what was already tried (a retry, different arguments, `lang`).
- One issue per report.
"""


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
    configure_private_logs()
    STATS.register_tools(("search_tools", "call_tool", "plan_query"))
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
        website_url="https://maplestats.danielstats.io/",
        icons=[icon],
        # Replaced by CachedDereferenceMiddleware below: same output, but each
        # schema is dereferenced once instead of on every search_tools/call_tool.
        dereference_schemas=False,
    )
    mcp.add_middleware(CachedDereferenceMiddleware())
    catalogue = read_catalogue() or {}
    for module_dir in module_dirs():
        entry = catalogue.get(module_dir.name)
        # A module the catalogue does not list yet (a new one) loads eagerly.
        if entry is None:
            mcp.add_provider(ModuleProvider(root=module_dir))
        else:
            mcp.add_provider(LazyModuleProvider(module_dir, entry))
    mcp.add_middleware(ValidationErrorMiddleware())
    mcp.add_middleware(CallLanguageMiddleware())
    # One byte budget for every tool's result, and the fitness-for-use caveats in
    # its provenance; inside the language middleware so its notes follow lang.
    mcp.add_middleware(ResponseBudgetMiddleware())
    # Usage counting goes outside the timeout: a timeout cancels the call
    # beneath it, which an inner counter never sees as an error, so a call
    # that timed out would be missing from /stats.
    if config.get_usage_stats_enabled():
        mcp.add_middleware(UsageMiddleware(STATS))
    mcp.add_middleware(ToolTimeoutMiddleware(config.get_tool_timeout_seconds()))
    mcp.add_transform(
        AnnotatedBM25SearchTransform(
            max_results=5,
            always_visible=list(SEARCH_ALWAYS_VISIBLE),
            search_tool_name="search_tools",
            call_tool_name="call_tool",
            search_result_serializer=search.serialize_tools_compact,
        )
    )

    @mcp.resource("docs://catalogue")
    def module_catalogue_doc() -> str:
        """Bilingual (EN/FR) directory of every module this server exposes,
        by name and description — use this to see what a source covers in
        French before deciding which tools to call."""
        return _build_module_catalogue()

    @mcp.resource("docs://report-issue")
    def report_issue_doc() -> str:
        """When and how to offer the user a bug report for this server, with
        the template to fill in. Read it when a tool misbehaves."""
        return REPORT_ISSUE_TEMPLATE

    @mcp.resource("docs://status")
    def upstream_status_doc() -> str:
        """Upstream hosts MapleStats has paused after repeated failures (EN/FR),
        with when each is tried again. Read it when tools for one source keep
        failing with UpstreamUnavailable."""
        return render_status()

    return mcp


mcp = build_server()
