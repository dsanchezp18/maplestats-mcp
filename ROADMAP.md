# Roadmap

Source coverage plan for MapleData MCP. This is the authoritative list of
what the package will cover — scoped by Daniel on 2026-09-14, superseding
any narrower or broader source list implied elsewhere.

Current implementation snapshot (2026-09-17): shipped modules cover
Statistics Canada, the Bank of Canada, federal CKAN, Alberta, British
Columbia, Ontario, Quebec, the Northwest Territories, Yukon, Montreal, and
Toronto. The rows below are the source-of-truth for remaining work; each
row has its own status.

Status values: `Not started` / `In progress` / `Shipped` / `Blocked`.
A source is marked `Shipped` only after its implemented functions and
important portal-specific behavior have been checked against live responses;
the Notes column records limits or remaining portal-specific work.

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

| Province | Status | Portal (reference) |
|---|---|---|
| Ontario | Shipped | data.ontario.ca, CKAN Action API: `ckan_on_*`, 8 tools. Bilingual dataset fields, tags, groups, organizations, and resources were verified against live responses. |
| British Columbia | Shipped | catalogue.data.gov.bc.ca, CKAN Action API: `ckan_bc_*`, 9 tools (search, dataset/org/resource/license detail, tags, groups). English-only. BC Geographic Warehouse (WFS) is a separate, not-yet-built source. |
| Quebec | Shipped | donneesquebec.ca (API at `/recherche/api/3/action/`), CKAN Action API: `ckan_qc_*`, 8 tools. French-only — `lang` is a documented no-op. |
| Alberta | Shipped | open.alberta.ca, CKAN Action API: `ckan_ab_*`, 7 tools. Dataset, organization, resource, license, and tag responses were verified against live responses; the portal does not expose useful groups in the tested catalogue. |
| Manitoba | Not CKAN | geoportal.gov.mb.ca — ArcGIS Hub ("Data MB"), not CKAN. Needs a separate ArcGIS Hub adaptor, out of scope for the CKAN adaptor. |
| Saskatchewan | Not CKAN | geohub.saskatchewan.ca — ArcGIS Hub, not CKAN. |
| Nova Scotia | Not CKAN | data.novascotia.ca — Socrata, not CKAN. |
| New Brunswick | Not CKAN | gnb.socrata.com — Socrata, not CKAN. GeoNB and a federal-CKAN subset remain separate, not-yet-built sources. |
| Newfoundland and Labrador | Not CKAN | opendata.gov.nl.ca — a custom platform (`?page-id=` URL scheme; both `site_read` and `package_list` 404), not CKAN. |
| Prince Edward Island | Not CKAN | data.princeedwardisland.ca — ArcGIS Online/Hub, not CKAN. |

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

Open item: inventory remaining major cities not yet checked (e.g.
Hamilton, London, Kitchener, Windsor, Regina, Saskatoon, Victoria,
Surrey, Laval, Gatineau) and add each once a real portal is confirmed.

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
