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

SERVER_INSTRUCTIONS = """
MapleData MCP — one MCP server for Canadian public data.

Read docs://catalogue for a bilingual (English/French) one-line
description of every module below — useful for a French-language
client deciding which source to query.

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
  Alberta (open.alberta.ca, ckan_ab_), Ontario (data.ontario.ca,
  ckan_on_), Yukon (open.yukon.ca, ckan_yt_), City of Montreal
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
- Canadian ArcGIS Hub open-data portals, provincial and municipal:
  Manitoba (Data MB, geoportal.gov.mb.ca, arcgis_mb_), Saskatchewan
  (Saskatchewan GeoHub, geohub.saskatchewan.ca, arcgis_sk_), Prince
  Edward Island (data.princeedwardisland.ca, arcgis_pe_), Hamilton
  (Open Hamilton, open.hamilton.ca, arcgis_hamilton_), London, Ontario
  (opendata.london.ca, arcgis_london_), Kitchener (Kitchener GeoHub,
  arcgis_kitchener_), Windsor (Windsor Open Data Portal,
  arcgis_windsor_), Saskatoon (arcgis_saskatoon_), Victoria (VicMap,
  opendata.victoria.ca, arcgis_victoria_), and Surrey (arcgis_surrey_).
  Every deployment runs the same ArcGIS Hub Search API v3 and classic
  ArcGIS REST FeatureServer/MapServer query API, verified live against
  all ten, with dataset search/detail, direct row queries against a
  FeatureServer/MapServer layer, and CSV/Shapefile/GeoJSON/KML download
  links. The *_query_feature_layer tools default layer_index to the
  service's own first reported layer or table id rather than assuming
  0 — a hosted table (no geometry) can genuinely sit at a non-zero id,
  and some cities' services live on a government domain rather than
  an *.arcgis.com one. Dataset content on every one of these ten
  portals was confirmed live to be English-only, except Manitoba,
  Saskatchewan, and Prince Edward Island, whose content is bilingual
  within a field rather than split by language.
- City of Regina Open Data (openregina.ca), CKAN Action API: search,
  dataset/organization/resource/license detail, tags, and curated
  thematic groups (tools prefixed ckan_regina_). Unlike ckan_bc, this
  deployment's group_list is public with no authentication workaround
  needed. English-only.
- Newfoundland and Labrador Open Data (opendata.gov.nl.ca), a custom
  page-based catalogue rather than CKAN: local search/pagination over
  tabular and spatial listings, topic tags, and dataset metadata with
  official file download links (tools prefixed nl_opendata_). The portal
  is English-only and has no documented JSON catalogue API.
- IRCC (Immigration, Refugees and Citizenship Canada) Express Entry
  rounds of invitations, from a static JSON feed IRCC publishes on
  canada.ca (tools prefixed ircc_) -- not a CKAN dataset, confirmed live
  to be a different platform from open.canada.ca: draw history, CRS
  (Comprehensive Ranking System) cutoff scores, invitations issued, and
  candidate-pool CRS score distribution. The French feed's bytes are
  Windows-1252 despite an undeclared charset, and two 2018-05-30 rounds
  share draw number 91 with letter suffixes ("91a"/"91b") instead of
  sequential numbers -- both handled by this module. IRCC's other
  administrative series (permanent residents, study/work permits,
  asylum, citizenship) are ordinary open.canada.ca CKAN datasets
  published by the "ircc" organization, already reachable via
  ckan_search_datasets(fq="organization:ircc") on the federal CKAN
  module above.

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
