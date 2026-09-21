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

- Statistics Canada, via six APIs. Web Data Service (WDS) for table/
  cube discovery, metadata, and time series (tools prefixed wds_); the
  SDMX REST API for filtered, server-side-sliced series queries (tools
  prefixed sdmx_); and Reference Data as a Service (RDaaS) for
  classifications, codesets, and concordances such as NAICS (tools
  prefixed rdaas_). The 2021 Census Profile SDMX API (tools prefixed
  statcan_census_profile_, a separate host from the two SDMX/WDS
  services above): statcan_census_profile_search_geography finds a
  geography's DGUID across all 14 published levels (province down to
  dissemination area), statcan_census_profile_search_characteristic
  finds a characteristic code among 2,631 (each carrying parent_code
  when it's a sub-item of a broader one, e.g. an age-group breakdown),
  and statcan_census_profile_get_data fetches counts/rates for any
  geography x characteristic combination. Confirmed live 2026-09-20:
  the public Census Profile search UI itself has no JSON API (a legacy
  ColdFusion app, pure server-rendered HTML) — this goes through the
  separate, documented Web Data Service instead; that service's
  metadata endpoints need an Accept header rather than the documented
  format= query param; its data endpoint is genuinely slow (45-48s for
  a single query, confirmed via raw curl bypassing this client
  entirely, hence an explicit 60s timeout); and French output needs an
  Accept-Language header, not a query parameter (handled internally —
  lang: en|fr still works normally). This SDMX service covers only the
  2021 census — confirmed by listing every dataflow it serves — so
  earlier censuses (2001, 2006, 2011, 2016) are covered separately by
  statcan_census_profile_archive_list_geography_levels and
  statcan_census_profile_archive_get_download_link, which resolve each
  year's official bulk CSV/TAB download link (no live query API exists
  for these years; 1996 has no equivalent bulk-download page under this
  URL scheme and is not covered). The Daily's official Atom feeds
  (tools prefixed statcan_daily_): statcan_daily_get_releases returns
  StatCan's official release bulletin (new/updated tables, survey
  results, analytical products) for the last 100 days, across all
  subjects or filtered to one of 30. Confirmed live 2026-09-20: The
  Daily's own web pages (search, calendar) are plain server-rendered
  HTML with no JSON API — this goes through StatCan's documented Atom
  feed family instead (www150.statcan.gc.ca/eng/sc/rss), which needs
  no API key. A feed entry's title/summary are XHTML divs that can
  hold inline markup (e.g. a `<span class="refper">` wrapping a
  reference period inside the title) — the client joins all text
  within the div rather than only its direct text, or that inline
  text would be silently dropped.
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
  what comes back. Every ckan_ module here except Yukon also has a
  ckan_<portal>_datastore_search tool, which queries actual row data
  out of a DataStore-active resource (check a resource's
  datastore_active flag first, from ckan_get_dataset or
  ckan_get_resource) instead of only handing back a download URL for
  the whole file — added across the whole family after discovering the
  gap on the federal module, where it unlocks real row-level querying
  for CRA (e.g. filtering a registered charity's directors/officers by
  business number, out of a 569,000+ row resource) and OSFI (e.g.
  querying a bank's M4 consolidated balance sheet line items directly
  rather than downloading the full quarterly return file); exact-match
  `filters` work on any resource size there, but that deployment
  rejects full-text `q` search with HTTP 409 for any resource over
  100,000 rows. Also confirmed live and working: BC (Foundation Skills
  Assessment district-level results, filterable by district/grade/
  subject/year), Alberta, Ontario, Quebec, Northwest Territories,
  Montreal, Toronto, and Regina. Yukon's deployment genuinely has no
  DataStore extension installed at all (`datastore_search` answers
  "Action name not known", confirmed live) — no tool is defined there
  as a result. One real, portal-specific quirk found this way: every
  DataStore-active resource tried on Alberta's deployment (the
  datastore_active flag itself is set correctly) returns HTTP 500 from
  datastore_search — a confirmed-live, portal-side backend issue, not
  a client bug; the tool still exists there and correctly surfaces
  that as an UpstreamError rather than silently failing.
- Canadian ArcGIS Hub open-data portals, provincial and municipal:
  Manitoba (Data MB, geoportal.gov.mb.ca, arcgis_mb_), Saskatchewan
  (Saskatchewan GeoHub, geohub.saskatchewan.ca, arcgis_sk_), Prince
  Edward Island (data.princeedwardisland.ca, arcgis_pe_), Hamilton
  (Open Hamilton, open.hamilton.ca, arcgis_hamilton_), London, Ontario
  (opendata.london.ca, arcgis_london_), Kitchener (Kitchener GeoHub,
  arcgis_kitchener_), Windsor (Windsor Open Data Portal,
  arcgis_windsor_), Saskatoon (arcgis_saskatoon_), Victoria (VicMap,
  opendata.victoria.ca, arcgis_victoria_), Surrey (arcgis_surrey_),
  Ottawa (open.ottawa.ca, arcgis_ottawa_), Halifax Regional
  Municipality (data-hrm.hub.arcgis.com, arcgis_halifax_), Mississauga
  (data.mississauga.ca, arcgis_mississauga_), Peel Region
  (data.peelregion.ca, arcgis_peel_), Durham Region
  (opendata.durham.ca, arcgis_durham_), the Region of Waterloo
  (rowopendata-rmw.opendata.arcgis.com, arcgis_waterloo_region_),
  Metro Vancouver (open-data-portal-metrovancouver.hub.arcgis.com,
  arcgis_metro_vancouver_), York Region
  (insights-york.opendata.arcgis.com, arcgis_york_), Markham
  (data-markham.opendata.arcgis.com, arcgis_markham_), Newmarket
  (published as NavigateNewmarket, navigate-newmarket.hub.arcgis.com,
  arcgis_newmarket_), Aurora, Ontario
  (town-of-aurora-data-hub-aurora.hub.arcgis.com, arcgis_aurora_),
  Medicine Hat (opendata.medicinehat.ca, arcgis_medicine_hat_), the
  City of Grande Prairie (opendata-cityofgp.hub.arcgis.com,
  arcgis_grande_prairie_), the County of Grande Prairie
  (county-of-grande-prairie-open-data-cogp.hub.arcgis.com,
  arcgis_grande_prairie_county_ — a separate government and catalogue
  from the city), St. Albert (data.stalbert.ca, arcgis_st_albert_),
  Lethbridge (opendata.lethbridge.ca, arcgis_lethbridge_), Airdrie
  (data-airdrie.opendata.arcgis.com, arcgis_airdrie_), and Strathcona
  County (opendata-strathconacounty.hub.arcgis.com,
  arcgis_strathcona_county_).
  Every deployment runs the same ArcGIS Hub Search API v3 and classic
  ArcGIS REST FeatureServer/MapServer query API, verified live against
  all twenty-eight, with dataset search/detail, direct row queries
  against a FeatureServer/MapServer layer, and CSV/Shapefile/GeoJSON/
  KML download links. The *_query_feature_layer tools default
  layer_index to the service's own first reported layer or table id
  rather than assuming 0 — a hosted table (no geometry) can genuinely
  sit at a non-zero id, some cities' services live on a government
  domain rather than an *.arcgis.com one, and (confirmed live adding
  Durham Region, then again adding Lethbridge and the County of Grande
  Prairie) an item's url can already name a specific layer of a large
  or self-hosted service — that trailing layer id, when present, is
  used directly rather than re-listing the service root and picking
  its first layer, which would otherwise silently return an unrelated
  dataset. Dataset content on every one of these twenty-eight portals
  was confirmed live to be English-only, except Manitoba, Saskatchewan,
  and Prince Edward Island, whose content is bilingual within a field
  rather than split by language. Two things worth knowing before
  querying these: opendata-cityofaurora.hub.arcgis.com is a
  similarly-named but different city (Aurora, Illinois) —
  arcgis_aurora_ points at the real Aurora, Ontario deployment; and
  the County of Grande Prairie's own catalogue has at least one item
  (Fire Permit Zones) whose service url points at a broken
  `/arcgisadmin/rest/services/...` path that returns HTTP 500 on any
  request — a portal-side metadata issue on that one item, not a
  client bug, confirmed by checking that every other item's
  `/arcgis/rest/services/...` path works normally.
- City of Vancouver Open Data Portal (opendata.vancouver.ca), an
  Opendatasoft deployment (tools prefixed opendatasoft_vancouver_) —
  the only Opendatasoft-platform source in this codebase (every other
  source above is CKAN, Socrata, or ArcGIS Hub). Verified live against
  the Explore API V2: dataset search/detail with fields and download
  links (CSV/JSON/GeoJSON), and direct record queries with ODSQL
  filtering (`where`), sorting (`order_by`), or a full-text `query`
  match. Full-text search on this platform genuinely requires
  Opendatasoft's own query language — confirmed live that a bare `q=`
  parameter is silently ignored (returns the full, unfiltered
  catalogue) while `where=search(*, '...')` correctly filters; both
  opendatasoft_vancouver_search_datasets and
  opendatasoft_vancouver_query_records build that clause internally, so
  a caller never needs to write raw ODSQL just to do a keyword search.
  English-only.
- Natural Resources Canada's National Burned Area Composite (NBAC,
  tools prefixed nrcan_nbac_) — the only OGC WFS 2.0/GeoServer-platform
  source in this codebase. nrcan_nbac_query_fires queries mapped fire
  polygons/records (start/end dates, adjusted burned area in hectares,
  cause, admin_area) for every fire event mapped in Canada since 1972,
  filtered with a standard OGC CQL expression against the layer's own
  field names (e.g. "admin_area = 'BC' AND year >= 2017 AND year <=
  2024"). `include_geometry` defaults to false for a lightweight,
  attribute-only query — NBAC's polygon geometry is large (the full
  shapefile export is over 1GB) — and reprojects to plain lat/lon
  (EPSG:4326) when a caller does ask for it. Confirmed live this
  GeoServer deployment always answers an error (a malformed
  `CQL_FILTER`, an unknown layer) as an OGC XML ExceptionReport, not
  JSON, regardless of the requested outputFormat.
- Canadian Socrata (SODA) open-data portals: Nova Scotia
  (data.novascotia.ca, socrata_ns_), New Brunswick (gnb.socrata.com,
  socrata_nb_), and the cities of Calgary (data.calgary.ca,
  socrata_calgary_), Edmonton (data.edmonton.ca, socrata_edmonton_),
  and Winnipeg (data.winnipeg.ca, socrata_winnipeg_). Every deployment
  runs the same platform (cross-domain discovery API, per-domain Views
  API, SODA row-query API), verified live for all five: dataset
  search/detail, categories, tags, and — unlike this server's CKAN
  portals, which only expose opaque downloadable resources — direct
  SoQL row queries against a dataset's actual data. Nova Scotia,
  Calgary, Edmonton, and Winnipeg are English-only at the dataset
  level; New Brunswick's content is bilingual within each field
  (English/French together) rather than split by language, so lang is
  a documented no-op on every one of these tools, same as this
  server's CKAN portals.
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

- Environment and Climate Change Canada / Meteorological Service of
  Canada (MSC GeoMet-OGC-API, api.weather.gc.ca, tools prefixed
  eccc_): weather alerts, current surface observations (SWOB), city
  forecasts, air quality health index (AQHI), climate stations/daily/
  hourly/monthly observations and 1981-2010 normals, hydrometric water
  level/flow, marine forecasts, and long-term climate extremes. This
  server publishes ~100 OGC API - Features collections with genuinely
  different property schemas per collection (confirmed live); rather
  than a bespoke tool per dataset, eccc_query_items works generically
  against any collection_id, with eccc_search_collections/
  eccc_get_collection for discovering one and its queryable property
  names first. Two real quirks to know before calling it: an unknown
  property filter is silently ignored upstream and returns zero rows
  instead of an error (eccc_query_items checks filter/sortby/field
  names against the collection's own queryables first and raises a
  clear error instead), and datetime filtering support is genuinely
  inconsistent per collection and not predictable from its metadata
  (works on hydrometric-realtime, fails with HTTP 500 on
  weather-alerts). Read docs://eccc/well-known-collections and
  docs://eccc/gotchas before relying on either. eccc_ tools accept
  lang for interface consistency, but it has no effect: MSC GeoMet has
  no language query parameter at all — bilingual content is already
  split into separate _en/_fr suffixed properties within one response.

- Canada Mortgage and Housing Corporation (CMHC), via the Housing
  Market Information Portal (HMIP, www03.cmhc-schl.gc.ca/hmip-pimh,
  tools prefixed cmhc_): Rental Market Survey vacancy rates and rents,
  new housing construction (starts/completions), secondary rental
  market, seniors' rental housing, and population/household/core-
  housing-need indicators, for Canada and by province, as a historical
  time series or a current cross-tabulation. This is a legacy ASP.NET
  MVC/Kendo UI portal with no JSON API and no hardcoded table
  catalogue here: cmhc_list_categories/cmhc_get_table_options discover
  categories and their valid breakdowns live from HMIP's own
  navigation, cmhc_get_table_data resolves those into a concrete
  TableId from an embedded JSON blob and fetches the actual numbers
  through HMIP's own official CSV export (confirmed live end-to-end,
  including its cp1252/Windows-1252 encoding — not UTF-8 and not
  strict latin-1, confirmed against a real em-dash byte). Unlike most
  tools here, lang genuinely changes behaviour: category names are
  different strings per language (confirmed: "Primary Rental Market"
  vs "Marché locatif primaire"), not just surrounding prose, so a
  category name from one language cannot be passed with the other.
  Only Canada and province-level geography are covered — no live
  CMA/city-level discovery endpoint was found. cmhc_get_table_data also
  accepts an optional filters dict (e.g. {"dwelling_type_desc_en":
  "Row"}, {"season": "April"}) for tables that support an extra
  narrowing dimension beyond column_field/row_field — confirmed live
  these genuinely change returned values, validated against the
  table's own available_filters before being sent. Read
  docs://cmhc/well-known-categories and docs://cmhc/gotchas before
  relying on the suppressed-value markers ("**"/"++"/"n/a"), the "-"
  real-zero marker, or the reliability-flag legend (present only on
  statistically-sampled tables, not census-style administrative ones).
  A second, unrelated CMHC platform is also
  covered: the "Data Tables" document catalogue (www.cmhc-schl.gc.ca,
  a Sitecore site, tools prefixed cmhc_dt_) — official per-edition
  Excel publications for Rental Market Survey and Household
  Characteristics tables (Canadian Housing Survey tables are not yet
  mapped). cmhc_dt_list_tables/cmhc_dt_get_table discover a category's
  tables and their geography/edition options (Sitecore GUIDs, a
  completely different id scheme from HMIP's small integers);
  cmhc_dt_get_download_url resolves any of those combinations to a
  direct download link through the site's own resolver API
  (api/Sitecore/PubsAndReports/GetFileDetails, found via live network-
  request inspection, not documentation) rather than guessing at a
  filename pattern — confirmed live that guessing fails for at least
  one older edition whose filename omits a suffix later editions have.

- Innovation, Science and Economic Development Canada (ISED), via three
  separate platforms. Corporations Canada's federal corporation lookup
  API (ised-isde.canada.ca, tools prefixed ised_corporations_):
  ised_corporations_get_corporation looks up one federal corporation by
  its numeric corporation id or 9-digit business number, returning
  current status, names, addresses, director limits, annual-return
  filing history, and incorporation/by-law activities. This is a
  single-record lookup, not a name search — there is no documented
  search-by-name endpoint. Two real quirks confirmed live: an
  unmatched id/business number still answers HTTP 200, with the body
  becoming a two-element list of plain error strings instead of the
  usual record shape (handled internally, surfaced as a normal
  not-found error); and the upstream address field is genuinely
  spelled "adresses", not "addresses". The Spectrum Management
  System's licence site data (a single Esri-hosted ArcGIS FeatureServer
  with no Hub Search catalogue in front of it, tools prefixed
  ised_spectrum_): ised_spectrum_query_licences queries ~840,000
  wireless spectrum licence site records (licensee, service type,
  transmit/receive frequencies, tower location/height, antenna
  specs), refreshed monthly, reusing this server's existing generic
  ArcGIS FeatureServer query plumbing directly against one fixed known
  service url rather than a Hub catalogue. The Canadian Trademarks
  Database (CIPO)'s search API (ised-isde.canada.ca/cipo/trademark-search,
  tools prefixed ised_cipo_): ised_cipo_search_trademarks searches over
  2 million Canadian trademark records (registered, pending, expunged,
  abandoned) by owner name, mark text, goods/services text,
  application/registration number, Nice classification, or Vienna
  design code. Confirmed live 2026-09-20: this endpoint is not
  documented as a public API anywhere — it backs the search UI's own
  XHR calls — but is a plain unauthenticated JSON POST, no session
  cookie or CSRF token required, and stayed reachable outside the
  browser. Two real quirks confirmed live: searchfield1 accepts only
  the exact internal dropdown codes (any other value returns HTTP 500
  with no detail, not a 400 — see constants.SEARCH_FIELD_TO_API); and
  there is no pagination — start/startRow/offset/page/pageNum were all
  tried live and silently ignored, so max_return only caps how many
  top-ranked matches come back in one call, with no way to page past
  that count. ISED's own bulk statistical
  datasets (Financial Performance Data, historical insolvency
  statistics, and a bulk CSV export of the same federal-corporations
  register) are ordinary CKAN datasets published by the "ic"
  organization on open.canada.ca, reachable via
  ckan_search_datasets(fq="organization:ic") — none of these
  particular resources are DataStore-active, so ckan_get_dataset's
  bulk download link is the only access path for them, not
  ckan_datastore_search. The Canada Revenue Agency's tax-filer
  statistics (T1/T2, GST/HST, TFSA, Canada Child Benefits, lists of
  registered charities) and the Office of the Superintendent of
  Financial Institutions' regulated-entity data (banks, insurers,
  trust and loan companies, and their financial return filings) are
  likewise ordinary CKAN datasets, under the "cra-arc" and
  "osfi-bsif" organizations respectively — but here several key
  resources genuinely are DataStore-active and confirmed live
  queryable with ckan_datastore_search: a CRA charity's directors/
  officers table (569,000+ rows, filterable by business number) and
  OSFI's bank regulatory returns (e.g. the M4 consolidated balance
  sheet, filterable by institution/period/line item) both return real
  row data this way, not just a CSV link. CRA's own Bankruptcy-
  adjacent data note: the Office of the Superintendent of Bankruptcy's
  *individual* debtor records search (ised-isde.canada.ca, part of
  ISED) requires an account and charges a per-search fee — genuinely
  paywalled and authentication-gated, not open data, so it is out of
  scope; ISED's free, open *aggregate* insolvency statistics (monthly/
  annual counts by NAICS industry or Forward Sortation Area) remain
  reachable via ckan_search_datasets(fq="organization:ic") as bulk
  downloads, with no DataStore-active resources found among them.

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
