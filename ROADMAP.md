# Roadmap

Source coverage plan for MapleData MCP. This is the authoritative list of
what the package will cover — scoped by Daniel on 2026-09-14, superseding
any narrower or broader source list implied elsewhere.

Current implementation snapshot (2026-09-18): shipped modules cover
Statistics Canada, the Bank of Canada, federal CKAN, Alberta, British
Columbia, Ontario, Quebec, Nova Scotia, New Brunswick, Manitoba,
Saskatchewan, Prince Edward Island, the Northwest Territories, Yukon,
Montreal, Toronto, Regina, Hamilton, London, Kitchener, Windsor,
Saskatoon, Victoria, and Surrey (Laval and Gatineau are covered
through the existing Quebec CKAN module, not a dedicated one). The
rows below are the source-of-truth for remaining work; each row has
its own status.

Status values: `Not started` / `In progress` / `Shipped` / `Blocked`.
A source is marked `Shipped` only after its implemented functions and
important portal-specific behavior have been checked against live responses;
the Notes column records limits or remaining portal-specific work. `Not CKAN`
is retained only where it communicates an intentional platform boundary: the
portal is identified, but it needs a different adaptor rather than the CKAN
adaptor.

## Federal

Only these five — no other federal source is in scope (drug database,
recalls, nutrient file, open parliament, and similar federal modules
seen in benchmark research are explicitly excluded).

| Source | Status | Notes |
|---|---|---|
| Statistics Canada (StatCan) | Shipped | WDS + SDMX + RDaaS: table/cube discovery, metadata, series retrieval, change detection, classifications. |
| Bank of Canada | Shipped | Valet API: exchange rates, interest rates, commodity prices, CPI/inflation, series metadata. |
| Federal Open Data (CKAN, open.canada.ca) | Shipped | ~48K-dataset catalogue: search, dataset details, organizations, resources, licenses. |
| IRCC Immigration | Not started | Permanent residents, study/work permits, Express Entry, asylum, citizenship, and related administrative series. |
| Weather / Climate (Environment Canada MSC GeoMet) | Not started | Current conditions, forecasts, alerts, climate normals, air quality, hydrology, marine, severe weather, snow. |

## Provincial (all 10)

### Next provincial sequence

The four CKAN provinces, the Socrata pair, and the ArcGIS Hub trio are now
shipped. The remaining provincial work should stay adaptor-first so one
implementation unlocks several provinces:

For this provincial phase, "coverage" means the official/main provincial
portal. Municipal portals and secondary departmental or specialized portals
are out of scope unless they are later promoted explicitly.

| Sequence | Adaptor | Provincial coverage | Reason |
|---|---|---|---|
| 1 | Socrata | Nova Scotia, New Brunswick | Shipped 2026-09-18: `socrata_ns_*`/`socrata_nb_*`, verified live against `api.us.socrata.com`'s catalog API, the per-domain Views API, and the SODA row-query API for both `data.novascotia.ca` and `gnb.socrata.com`. The same adaptor also unlocks Calgary, Edmonton, and Winnipeg (all confirmed Socrata) when a municipal phase is scoped in. |
| 2 | ArcGIS Hub / ArcGIS REST | Manitoba, Saskatchewan, Prince Edward Island | Shipped 2026-09-18: `arcgis_mb_*`/`arcgis_sk_*`/`arcgis_pe_*`, verified live against all three portals' Hub Search API v3 (`/api/search/v1/collections/dataset/items`), the classic ArcGIS REST FeatureServer/MapServer query API, and the `/api/download/v1` export API. Two real quirks only found by calling every function against all three portals live (not caught by mocked tests alone): a catalogue item's `properties.url` is sometimes the bare service root and sometimes already a specific layer endpoint, and the default layer/table id to query is not always 0 — Saskatchewan services can live on a government domain (`gis.saskatchewan.ca`) rather than `*.arcgis.com`, and a PEI item's service reported its one queryable table at id 2 with an empty `layers` list. This adaptor also creates a path for many municipal and specialized geographic portals (see the Municipal section below). |
| 3 | Newfoundland and Labrador custom portal | Newfoundland and Labrador | The provincial open-data catalogue has its own page-based interface and downloadable tabular/spatial files. Map its live endpoints separately after the two reusable adaptors are working; do not force it into CKAN or Socrata. This is now the next provincial implementation. |

| Province | Status | Portal (reference) |
|---|---|---|
| Ontario | Shipped | data.ontario.ca, CKAN Action API: `ckan_on_*`, 8 tools. Bilingual dataset fields, tags, groups, organizations, and resources were verified against live responses. |
| British Columbia | Shipped | catalogue.data.gov.bc.ca, CKAN Action API: `ckan_bc_*`, 9 tools (search, dataset/org/resource/license detail, tags, groups). English-only. BC Geographic Warehouse (WFS) is a separate, not-yet-built source. |
| Quebec | Shipped | donneesquebec.ca (API at `/recherche/api/3/action/`), CKAN Action API: `ckan_qc_*`, 8 tools. French-only — `lang` is a documented no-op. |
| Alberta | Shipped | open.alberta.ca, CKAN Action API: `ckan_ab_*`, 7 tools. Dataset, organization, resource, license, and tag responses were verified against live responses; the portal does not expose useful groups in the tested catalogue. |
| Manitoba | Shipped | geoportal.gov.mb.ca (Data MB), ArcGIS Hub: `arcgis_mb_*`, 3 tools (dataset search, item detail with download links, direct FeatureServer/MapServer row queries). Content is bilingual within each field (not split by language) — `lang` is a documented no-op. Verified against live Hub Search API v3, ArcGIS REST query, and `/api/download/v1` responses. |
| Saskatchewan | Shipped | geohub.saskatchewan.ca (Saskatchewan GeoHub), ArcGIS Hub: `arcgis_sk_*`, 3 tools, same shape as Manitoba's. Some items' FeatureServer/MapServer services live on a government domain (`gis.saskatchewan.ca`) rather than `*.arcgis.com` — the shared client checks for `/rest/services/` in the URL, not an `arcgis.com` domain, because of this. Verified against live responses. |
| Nova Scotia | Shipped | data.novascotia.ca, Socrata (SODA): `socrata_ns_*`, 5 tools (catalogue search, dataset detail, categories, tags, direct SoQL row queries). English-only. Verified against live discovery/Views/SODA responses. |
| New Brunswick | Shipped | gnb.socrata.com, Socrata (SODA): `socrata_nb_*`, 5 tools (catalogue search, dataset detail, categories, tags, direct SoQL row queries). Content is bilingual within each field (English/French together) rather than split fields — `lang` is a documented no-op. GeoNB map services remain a separate, not-yet-built spatial surface. Verified against live discovery/Views/SODA responses. |
| Newfoundland and Labrador | Not CKAN | opendata.gov.nl.ca — a custom page-based catalogue, not CKAN. Verified 2026-09-17: tabular and spatial listings use `?page-id=datasets-tabular` / `?page-id=datasets-spatial`; dataset metadata uses `?id=<dataset-id>&page-id=datasetdetails`; files are binary downloads at `/public/opendata/filedownload/?file-id=<file-id>`. The catalogue exposes useful metadata (creator, publisher, geography, time coverage, dates, rights, topics, revision, format, size) and CSV/XLS/TXT/KMZ/shapefile files, but no documented JSON search/catalogue API; `site_read` and `package_list` are not valid CKAN routes. Build a focused HTML catalogue adaptor only after contract tests for these routes and pagination/search behavior. Keep the official GeoAtlas spatial surface separate: `https://dnrmaps.gov.nl.ca/arcgis/rest/services/GeoAtlas` is a reusable ArcGIS REST target with MapServer layer queries, KML generation, and a DataExtract GPServer. Portal content observed is English-only; preserve the Open Government Licence—Newfoundland and Labrador attribution and every source/detail/download URL. |
| Prince Edward Island | Shipped | data.princeedwardisland.ca, ArcGIS Hub: `arcgis_pe_*`, 3 tools, same shape as Manitoba's. At least one item's underlying service reports an empty `layers` list with its one queryable table at a non-zero id (2) — the default-layer-index resolution this adaptor added because of that applies here too. Verified against live responses. |

## Territorial (all 3)

| Territory | Status | Portal (reference) |
|---|---|---|
| Northwest Territories | Shipped | opendata.gov.nt.ca, CKAN Action API: `ckan_nt_*`, 8 tools. English-only. Small catalogue (341 datasets). |
| Yukon | Shipped | open.yukon.ca, CKAN Action API: `ckan_yt_*`, 8 tools. English-only (site UI is bilingual-chrome only; dataset content is not). 3,841 datasets. |
| Nunavut | Not started | TBD — no confirmed portal identified yet |

## Municipal (all that apply — established open-data portals)

Cities and regions with a verified open-data portal. This list is a
starting inventory, not a hard ceiling — add a city/region here once its
portal is confirmed to exist and be reachable.

| Municipality / region | Status | Portal (reference) |
|---|---|---|
| Toronto | Shipped | open.toronto.ca (UI) / `ckan0.cf.opendata.inter.prod-toronto.ca` (Action API host — the UI domain is not the API), CKAN Action API: `ckan_toronto_*`, 7 tools (no groups — confirmed unused). English-only. 557 datasets. |
| Montreal | Shipped | donnees.montreal.ca, CKAN Action API: `ckan_montreal_*`, 8 tools. French-only — `lang` is a documented no-op. |
| Laval | Shipped (via `ckan_qc_*`) | No standalone portal — Laval publishes through the shared Données Québec CKAN instance (donneesquebec.ca) already covered by `ckan_qc_*`, confirmed live: `ville-de-laval` is a real organization there. No dedicated module needed. |
| Gatineau | Shipped (via `ckan_qc_*`) | Same as Laval: Gatineau publishes through the shared Données Québec CKAN instance, confirmed live (`ville-de-gatineau` organization) — already covered by `ckan_qc_*`, no dedicated module needed. |
| Regina | Shipped | openregina.ca, CKAN Action API: `ckan_regina_*`, 9 tools (search, dataset/organization/resource/license detail, tags, and curated thematic groups). English-only. 1,379 datasets. Unlike `ckan_bc`, `group_list` is public here — no authentication workaround needed. `open.regina.ca` (the city's own linked domain) did not resolve directly in this session; `openregina.ca` is the confirmed-live canonical host. |
| Hamilton | Shipped | open.hamilton.ca (Open Hamilton), ArcGIS Hub: `arcgis_hamilton_*`, 3 tools, same shape as the provincial ArcGIS Hub modules (search, item detail with download links, direct FeatureServer/MapServer row queries). English-only. |
| London | Shipped | opendata.london.ca (City of London Open Data), ArcGIS Hub: `arcgis_london_*`, 3 tools, same shape. English-only. |
| Kitchener | Shipped | open-kitchenergis.opendata.arcgis.com (Kitchener GeoHub), ArcGIS Hub: `arcgis_kitchener_*`, 3 tools, same shape. English-only. |
| Windsor | Shipped | open-data-portal-citywindsor.hub.arcgis.com (Windsor Open Data Portal), ArcGIS Hub: `arcgis_windsor_*`, 3 tools, same shape. English-only; confirmed live this catalogue has zero datasets matching "water" despite 177 total datasets — not every catalogue matches every test keyword. |
| Saskatoon | Shipped | data-citysaskatoon.opendata.arcgis.com, ArcGIS Hub: `arcgis_saskatoon_*`, 3 tools, same shape. English-only; small catalogue (10 datasets confirmed live). |
| Victoria | Shipped | opendata.victoria.ca (VicMap), ArcGIS Hub: `arcgis_victoria_*`, 3 tools, same shape. English-only. |
| Surrey | Shipped | opendata-surrey.hub.arcgis.com (City of Surrey Open Data Catalog), ArcGIS Hub: `arcgis_surrey_*`, 3 tools, same shape. English-only. The city's older CKAN-era URL, `data.surrey.ca`, now 301-redirects here — confirmed live this is a full platform migration, not a parallel CKAN portal to also cover. |
| Vancouver | Not CKAN | opendata.vancouver.ca — Opendatasoft, not CKAN/Socrata/ArcGIS. |
| Calgary | Not CKAN | data.calgary.ca — Socrata, not CKAN. |
| Edmonton | Not CKAN | data.edmonton.ca — Socrata, not CKAN. |
| Ottawa | Not CKAN | open.ottawa.ca — migrated off CKAN to ArcGIS Hub (per the city's own 2023/24 announcement). |
| Winnipeg | Not CKAN | data.winnipeg.ca — Socrata, not CKAN. |
| Halifax | Not CKAN | catalogue.open.halifax.ca does not resolve; the real portal (data-hrm.hub.arcgis.com) is ArcGIS Hub, not CKAN. |
| Mississauga | Not CKAN | data.mississauga.ca — ArcGIS Hub, not CKAN. |
| York Region | Not CKAN | york.ca/open-data — ArcGIS Hub, not CKAN. |
| Markham | Not CKAN | ArcGIS Hub (via York Region cluster), confirmed. |
| Newmarket | Not CKAN | ArcGIS Hub (via York Region cluster), confirmed. |
| Aurora | Not CKAN | ArcGIS Hub (via York Region cluster), confirmed. |
| Peel Region | Not CKAN | data.peelregion.ca — ArcGIS Hub, not CKAN. |
| Durham Region | Not CKAN | opendata.durham.ca — ArcGIS Online/Hub, not CKAN. |
| Halton Region | Unknown | opendata.halton.ca does not resolve; no live Halton Region portal was found (only a separate Conservation Halton ArcGIS Hub, a different body). |
| Waterloo Region | Not CKAN | opendata.regionofwaterloo.ca — ArcGIS Hub, not CKAN. |
| Metro Vancouver | Not CKAN | open.metrovancouver.org — ArcGIS Hub, not CKAN. |

Shipped 2026-09-18: Hamilton, London, Kitchener, Windsor, Saskatoon,
Victoria, and Surrey (all ArcGIS Hub), Regina (CKAN), and Laval/
Gatineau (already covered via the shared `ckan_qc_*` Données Québec
module, no dedicated module needed) — the major-city inventory named
below as an open item. Vancouver, Calgary, Edmonton, Ottawa, Winnipeg,
and the smaller municipalities/regions below remain their own rows;
Calgary, Edmonton, and Winnipeg are confirmed Socrata and would reuse
the existing `shared/socrata.py` adaptor if a municipal Socrata phase
is scoped in (see the provincial sequence table above).

Open item: every city from the original example list (Hamilton,
London, Kitchener, Windsor, Regina, Saskatoon, Victoria, Surrey,
Laval, Gatineau) is now shipped or covered. Inventory further major
cities not yet checked (e.g. Quebec City, Longueuil, Burnaby,
Richmond, Vaughan, Kelowna, Sherbrooke, Trois-Rivières, St. John's,
Barrie, Guelph, Kingston) and add each once a real portal is
confirmed.

## Census and specialized federal agencies

Sources beyond the core five federal modules and beyond generic
CKAN/portal coverage — each needs its own adaptor design.

| Agency / source | Status | Notes |
|---|---|---|
| Census (StatCan Census Program / Census Profile) | Not started | Distinct from generic StatCan table access — needs its own discovery layer (geography, profile variables, PUMFs). |
| CMHC | Not started | Housing and rental-market data. No verified dedicated MCP exists yet for this — a genuine greenfield build. Investigate existing community access patterns for CMHC data as a reference. |
| CRTC | Not started | Telecommunications/broadcasting market data: plan prices, subscribers, revenues, broadband, competition indicators. |
| CER (Canada Energy Regulator) | Not started | Oil, gas, NGL/LNG, pipeline, energy trade/export/price/infrastructure data. |
| CRA (Canada Revenue Agency) | Not started | T1/T2 tax statistics, tax-filer aggregates, benefits, charities, other administrative tax datasets. |
| ISED (Innovation, Science and Economic Development Canada) | Not started | Spectrum/radio licensing, broadband/connectivity, corporations, insolvencies, business datasets. |
| OSFI (Office of the Superintendent of Financial Institutions) | Not started | Banks, insurers, federally regulated pension plans, regulatory/balance-sheet statistics. |
| Transport Canada + CTA (Canadian Transportation Agency) | Not started | Aviation, rail, transport regulatory data, complaints, accessibility, infrastructure. |
| Elections Canada | Not started | Election results, candidates, political financing/contributions, polling divisions, electoral geography. |
| CanadaBuys (PSPC procurement) | Not started | Tenders, procurement notices, contract awards, procurement metadata. |
