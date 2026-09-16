# Roadmap

Source coverage plan for MapleData MCP. This is the authoritative list of
what the package will cover — scoped by Daniel on 2026-09-14, superseding
any narrower or broader source list implied elsewhere. Every source below
is currently **Not started**; none of this is built yet, fork or
otherwise.

Status values: `Not started` / `In progress` / `Shipped`.

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
| Ontario | Not started | data.ontario.ca |
| British Columbia | Not started | catalogue.data.gov.bc.ca + BC Geographic Warehouse (WFS) |
| Quebec | Not started | donneesquebec.ca |
| Alberta | Not started | open.alberta.ca |
| Manitoba | Not started | geoportal.gov.mb.ca |
| Saskatchewan | Not started | geohub.saskatchewan.ca |
| Nova Scotia | Not started | data.novascotia.ca (Socrata) |
| New Brunswick | Not started | gnb.socrata.com + GeoNB + federal CKAN subset |
| Newfoundland and Labrador | Not started | opendata.gov.nl.ca |
| Prince Edward Island | Not started | data.princeedwardisland.ca |

## Territorial (all 3)

| Territory | Status | Portal (reference) |
|---|---|---|
| Northwest Territories | Not started | opendata.gov.nt.ca |
| Yukon | Not started | open.yukon.ca |
| Nunavut | Not started | TBD — no confirmed portal identified yet |

## Municipal (all that apply — established open-data portals)

Cities and regions with a verified open-data portal. This list is a
starting inventory, not a hard ceiling — add a city/region here once its
portal is confirmed to exist and be reachable.

| Municipality / region | Status | Portal (reference) |
|---|---|---|
| Toronto | Not started | open.toronto.ca |
| Montreal | Not started | donnees.montreal.ca |
| Vancouver | Not started | opendata.vancouver.ca |
| Calgary | Not started | data.calgary.ca |
| Edmonton | Not started | data.edmonton.ca |
| Ottawa | Not started | open.ottawa.ca |
| Winnipeg | Not started | data.winnipeg.ca |
| Halifax | Not started | catalogue.open.halifax.ca |
| Mississauga | Not started | data.mississauga.ca |
| York Region | Not started | york.ca/open-data |
| Markham | Not started | ArcGIS Hub (via York Region cluster) |
| Newmarket | Not started | ArcGIS Hub (via York Region cluster) |
| Aurora | Not started | ArcGIS Hub (via York Region cluster) |
| Peel Region | Not started | data.peelregion.ca |
| Durham Region | Not started | opendata.durham.ca |
| Halton Region | Not started | opendata.halton.ca |
| Waterloo Region | Not started | opendata.regionofwaterloo.ca |
| Metro Vancouver | Not started | open.metrovancouver.org |

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
