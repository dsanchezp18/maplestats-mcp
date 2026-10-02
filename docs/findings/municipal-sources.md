# Municipal sources

Findings moved from [`ROADMAP.md`](../ROADMAP.md) on 2026-09-25. Each section
records what was checked, against which live responses, and what the
module does about it. Dates are when a finding was confirmed; the
status in `ROADMAP.md` is the current one.

## Montreal

**Status:** Shipped.

donnees.montreal.ca, CKAN Action API: `ckan_*` (`portal="montreal"`), 9
tools (added `ckan_datastore_search` 2026-09-20; also added a
`datastore_active` field to `ResourceInfo`, which this module had never
tracked at all before). French-only — `lang` is a documented no-op.
Confirmed live its own error message for an unmatched DataStore resource is
in French ("Indisponible: Resource ... was not found."), mixed with the rest
of the message in English -- passed through as-is.

## Regina

**Status:** Shipped.

openregina.ca, CKAN Action API: `ckan_*` (`portal="regina"`), 10 tools
(search, dataset/organization/resource/license detail, tags, curated
thematic groups, and -- added 2026-09-20 -- `ckan_datastore_search`,
confirmed live against a real parking-violations resource with 16,340+
rows). English-only. 1,379 datasets. Unlike `ckan_bc`, `group_list` is
public here — no authentication workaround needed. `open.regina.ca` (the
city's own linked domain) did not resolve directly in this session;
`openregina.ca` is the confirmed-live canonical host.

## Vancouver

**Status:** Shipped.

opendata.vancouver.ca, Opendatasoft (Explore API V2):
`opendatasoft_vancouver_*`, 3 tools (dataset search, dataset detail with
fields/download links, direct record queries with ODSQL filtering/sorting).
The first Opendatasoft-platform source in this codebase — added a new
`shared/opendatasoft.py` adaptor rather than forcing it into the
CKAN/Socrata/ArcGIS shape. Confirmed live 2026-09-19: full-text search needs
ODSQL's `search(*, '...')` function — a bare `q=` catalog parameter is
silently ignored and returns the whole unfiltered catalogue instead of
erroring, so both the search and record-query client functions build that
clause internally.

`limit` is capped at 100 per request on both the catalog and records
endpoints; both share one error envelope (`{"error_code": ..., "message":
...}`) across a missing dataset (404), an out-of-range parameter (400), and
a malformed caller-supplied `where`/`order_by` clause (400). English-only.
200 datasets confirmed live.

## Markham

**Status:** Shipped.

data-markham.opendata.arcgis.com, ArcGIS Hub: `arcgis_hub_*`
(`portal="markham"`), 3 tools, same shape. Not part of a shared "York Region
cluster" instance — its own independent Hub deployment, confirmed live. Some
catalogue items' `properties.url` points at
`utility.arcgis.com/usrsvcs/servers/...` rather than an `*.arcgis.com` org
domain — still contains `/rest/services/` and is handled by the existing
generic client unchanged. English-only. 219 datasets confirmed live.

## Aurora

**Status:** Shipped.

town-of-aurora-data-hub-aurora.hub.arcgis.com (Town of Aurora, Ontario),
ArcGIS Hub: `arcgis_hub_*` (`portal="aurora"`), 3 tools, same shape. Not
part of a shared "York Region cluster" instance — its own independent Hub
deployment, confirmed live. **Real find while researching this row**: the
more obvious-looking domain `opendata-cityofaurora.hub.arcgis.com` is a
different, similarly-named city — its own licence text states it is hosted
by Esri "on behalf of Aurora, IL" (Aurora, Illinois) — confirmed live by
checking that domain's actual dataset content and coordinates before
shipping the wrong source.

English-only. 1 dataset confirmed live (a small catalogue).

## Durham Region

**Status:** Shipped.

opendata.durham.ca, ArcGIS Hub: `arcgis_hub_*` (`portal="durham"`), 3 tools,
same shape. **Found and fixed a real bug in the shared `default_layer_index`
helper (`shared/arcgis.py`) while shipping this row**: Durham's catalogue
items point at a specific layer (e.g. layer 129) of one large shared
`Durham_OpenData/MapServer` exposing 200+ layers, rather than at a
single-purpose service — the existing logic stripped that trailing layer id
and re-listed the service root, which would have silently returned an
unrelated layer (0, "ADDR_Durham") instead of the one the catalogue item
actually represents.

`default_layer_index` now returns a service url's own trailing numeric layer
id directly when present, before ever listing the root; this also benefits
every other ArcGIS Hub module already shipped, with no behavior change
confirmed for any of them (their fixtures/live services have no such
trailing digit). English-only. 229 datasets confirmed live.

opendata.durham.ca, ArcGIS Hub: `arcgis_hub_*` (`portal="durham"`), 3 tools,
same shape. **Found and fixed a real bug in the shared `default_layer_index`
helper (`shared/arcgis.py`) while shipping this row**: Durham's catalogue
items point …

## Waterloo Region

**Status:** Shipped.

rowopendata-rmw.opendata.arcgis.com (Region of Waterloo), ArcGIS Hub:
`arcgis_hub_*` (`portal="waterloo_region"`), 3 tools, same shape. Neither
`opendata.regionofwaterloo.ca` (does not resolve) nor the Region's own
"GeoHub" (`region-of-waterloo-geohub-rmw.hub.arcgis.com`, confirmed live to
carry almost no dataset-type content — 2 items total, both Hub pages) is the
real catalogue; `rowopendata-rmw` is. English-only. 358 datasets confirmed
live.

## Grande Prairie (County)

**Status:** Shipped.

county-of-grande-prairie-open-data-cogp.hub.arcgis.com, ArcGIS Hub:
`arcgis_hub_*` (`portal="grande_prairie_county"`), 3 tools, same shape,
self-hosted service domain (`opendataservices.countygp.ab.ca`) rather than
`*.arcgis.com`. **Real portal-side data-quality issue found while shipping
this row**: the "Fire Permit Zones" item's `properties.url` points at
`/arcgisadmin/rest/services/...`, which returns HTTP 500 on every request
(confirmed with multiple user agents) — every other item checked instead
uses a working `/arcgis/rest/services/...` path on the same domain, so this
is one mis-published item's metadata, not a client bug or a broken portal.

English-only. 25 datasets confirmed live.

county-of-grande-prairie-open-data-cogp.hub.arcgis.com, ArcGIS Hub:
`arcgis_hub_*` (`portal="grande_prairie_county"`), 3 tools, same shape,
self-hosted service domain (`opendataservices.countygp.ab.ca`) rather than
`*.arcgis.com`. **Real …

## Lethbridge

**Status:** Shipped.

opendata.lethbridge.ca (Lethbridge Open Data Catalogue), ArcGIS Hub:
`arcgis_hub_*` (`portal="lethbridge"`), 3 tools, same shape. Confirmed live
this deployment's catalogue items commonly point at a self-hosted
`gis.lethbridge.ca` MapServer with the item's own url already ending in a
specific layer/table digit — exercises the same trailing-layer-id resolution
path fixed for Durham Region. English-only. 24 datasets confirmed live.

## Edmonton Police Service

**Status:** Shipped.

Community Safety Data Portal feature services on services9.arcgis.com (EPS's
own ArcGIS Online org, found by resolving the Community Safety Map's item
ids), not in data.edmonton.ca. New module `modules/eps/` (`eps_*`, 3 tools:
list occurrences, grouped counts, last load date), reusing
`shared/arcgis.py`. Confirmed live 2026-09-22: the `EPS_OCC_30DAY` service
is misnamed and holds a rolling ~12 months (79,018 rows); a 2023-only
historic view holds 81,344 rows; nothing public covers 2024 to mid-September
2025.

Location is nearest intersection only.

## Edmonton Transit Service real-time

**Status:** Shipped.

gtfs.edmonton.ca GTFS-Realtime (protobuf): new module `modules/ets/`
(`ets_*`, 3 tools: vehicle positions, stop predictions, service alerts).
Adds the `gtfs-realtime-bindings` dependency (pulls in `protobuf`).
Confirmed live 2026-09-22: ~260 vehicles, ~1,200 trip updates, ~100 alerts;
trip updates carry ETS's per-stop `scheduled_time` and `trip_headsign`, and
keep already-served stops in the feed (filtered out by default). The static
schedule stays on data.edmonton.ca via `socrata_*`.

## Transit schedules (static GTFS)

**Status:** Shipped for the TTC, STM (buses), OC Transpo and Calgary Transit;
TransLink not built.

New module `modules/transit/` (`transit_*`, 6 tools, one `agency` argument:
`transit_list_agencies`, `transit_get_feed_info`, `transit_search_routes`,
`transit_search_stops`, `transit_get_stop_departures`,
`transit_get_route_summary`). Nothing is stored: each zip's central
directory and small tables are read by HTTP range, and `stop_times.txt`
(14 to 71 MB compressed, 100 to 373 MB inflated) is streamed in 4 MB ranges,
inflated incrementally and filtered to the requested stop or trips, so memory
stays flat. Adding an agency is one entry in `constants.AGENCIES`.

Checked live 2026-10-01 (all answer 206 to a `Range` request without a key):

| Agency | Zip | Size | Licence and terms |
|---|---|---|---|
| TTC | ckan0.cf.opendata.inter.prod-toronto.ca ... /completegtfs.zip (City of Toronto open data, "Merged GTFS - TTC Routes and Schedules") | 84 MB | Open Government Licence - Toronto (use, copy, publish, distribute "for any lawful purpose", including commercially; attribution: "Contains information licensed under the Open Government Licence - Toronto."). The CKAN record says "License not specified"; the City's licence page covers its open data. |
| STM | www.stm.info/sites/default/files/gtfs/gtfs_stm.zip | 43 MB | CC BY 4.0 per STM's "Terms of use for GTFS and API". The same page says "Metro schedules are for information purposes only ... and cannot be used to develop an application on metro schedules", so metro lines (route_type 1) are excluded from route and departure results; buses are included. |
| OC Transpo | oct-gtfs-emasagcnfmcgeham.z01.azurefd.net/public-access/GTFSExport.zip (OC Transpo's own host) | 45 MB | OC Transpo's developer terms say the data is "separately licensed under the City of Ottawa Open Data Terms of Use", a worldwide, royalty-free licence to use, modify and distribute "for any lawful purpose". The City catalogue still lists octranspo.com/files/google_transit.zip, which returns 404; the Azure host needs no key (only real-time needs an account). |
| Calgary Transit | data.calgary.ca/download/npk7-z3bj/application%2Fzip (redirects to a CDN) | 18 MB | Open Government Licence - City of Calgary v2.1 (the "Open Calgary Terms of Use"): use, copy, publish, distribute for any lawful purpose including commercial, with attribution. |

**TransLink (Metro Vancouver) is not built.** The zip itself
(gtfs-static.translink.ca/gtfs/google_transit.zip, 16 MB) is open and
range-readable, but the terms at
translink.ca/about-us/doing-business-with-translink/app-developer-resources/gtfs/gtfs-data
say: "You must provide TransLink sufficient information as TransLink may
request to identify you, your organization or company, who will be using the
Data, where it will be distributed and whether the use of the data is for
non-commercial or commercial purposes. TransLink reserves the right to impose
conditions or restrictions on your use of the Data." The licence is "limited,
revocable and non-exclusive", and the data must carry the legend "Route and
arrival data used in this product or service is provided by permission of
TransLink ...". A public server cannot identify its callers to TransLink or
promise their purpose, so the feed is left out until the operator has an
agreement with TransLink; then it is one entry in `constants.AGENCIES`.

Quirks found against the live feeds:

- The City of Toronto's download host answered about half of all requests
  with a transient HTTP 502 (a stretch of 100 % on 2026-10-01, larger ranges
  failing more often), and HEAD more often than GET. Every range request is
  retried (6 attempts, `shared/remote_zip.py` and `transit/zipstream.py`) and
  a failed read reloads the directory and tries again. The first stop or route
  lookup on the TTC can still take minutes.
- Throughput differs: Calgary's CDN delivered about 330 KB/s, so its 13.5 MB
  `stop_times.txt` took about 40 s the first time; later calls for the same
  stop or route are cached for an hour.
- Calgary's zip has no `feed_info.txt` (no validity dates) and 521 routes
  with repeated short names, so a route number can need the `route_id`.
- STM and OC Transpo run trips past 24:00; the listing includes the previous
  service day's after-midnight trips and flags them.

## EPCOR Edmonton water quality

**Status:** Shipped.

New module `modules/epcor/` (`epcor_*`, 2 tools). Daily treated-water
readings come from the per-plant iframe
`apps.epcor.ca/DailyWaterQuality/Default.aspx?zone=ELS|Rossdale` (7 days,
year-less date labels), found 2026-09-22 by inspecting the page in a browser
-- the earlier "PDF-only" verdict was wrong. The report index parses ~246
PDF links from the live Water Quality Reports page because file names change
convention mid-2025 and include a typo.

2026-09-25: the report-PDF listing tool was removed (the server serves data,
not documents); `epcor_get_daily_water_quality` remains. New module
`modules/epcor/` (`epcor_*`, originally 2 tools). Daily treated-water
readings come from the per-plant iframe
`apps.epcor.ca/DailyWaterQuality/Default.aspx?zone=ELS|Rossdale` (7 days,
year-less date labels), found 2026-09-22 by inspecting …

## Edmonton-metro gaps

**Status:** Not shipped.

Re-checked 2026-09-27, unchanged: data.leduc.ca's Hub API lists one
Hub Page and no datasets; the "City of Spruce Grove Open Data" group is
invitation-only and empty to anonymous search; no Beaumont, Alberta or
Fort Saskatchewan open-data group exists.

Re-checked 2026-09-22 through ArcGIS Online group search: Leduc's Hub
(data.leduc.ca) holds only a Terms of Use page; Spruce Grove's open-data
group is empty; Fort Saskatchewan has none. The public "City of Beaumont
Open Data" feature services on services3.arcgis.com belong to Beaumont,
**California** (FEMA flood zones, neighbouring Banning/Calimesa) -- not
shipped; Beaumont, Alberta's own group is empty. Provincially published
datasets for these municipalities remain reachable via `ckan_*`
(`portal="ab"`).

## Cochrane

**Status:** Shipped (re-checked 2026-09-27).

Re-checked 2026-09-27: the Town of Cochrane's Hub site item ("Cochrane
GeoHub", org `M1SNYuFIW9v2gSO7`) now points at `geohub.cochrane.ca`, and
that domain's Hub Search API answers anonymously (29 datasets; all layers
tried answer queries). Added as `portal="cochrane"`, config-only. The old
`data-cochranegis.opendata.arcgis.com` still returns `GWM_0003` (HTTP
401/404), as before. Found by looking the org up through ArcGIS Online
(`cochranegis.maps.arcgis.com/sharing/rest/portals/self`, then a search
for its Hub Site Application items).

Layers there are often not layer 0 ("Parks" is layer 18), which exposed a
download-link bug affecting every portal; see "ArcGIS Hub download links"
below.

Earlier finding:

`data-cochranegis.opendata.arcgis.com` renders its public pages fine (HTTP
200) but its Hub Search API and DCAT feed both reject anonymous access
(`GWM_0003: You do not have permissions...`, HTTP 401/404) — confirmed live
with multiple user agents. The org's API access appears to require
authentication this server does not have; re-investigate only if that
changes.

## Okotoks

**Status:** Shipped (re-checked 2026-09-27).

Re-checked 2026-09-27: `okotoksmaps-okotoks.hub.arcgis.com` still answers
`GWM_0003`, but the town (org `Fl5sQFvYY7w7mPQj`) now runs "Okotoks Open
Data" at `maps-okotoks.hub.arcgis.com`, whose Hub API answers. That site
has no `dataset` collection (`/collections/dataset` is a 404 "Collection
with id \"dataset\" not found"); `/api/search/v1/collections` lists only
`all`, which holds 58 Feature Services, a Hub Page and the site itself. So
the portal is configured with `collection="all"` and
`default_item_type="Feature Service"`; the `type` filter works on `all`.
All 58 layers answer anonymous count queries; their ids are not 0
(Floodway is 35).

## Red Deer

**Status:** Shipped.

reddeer.opendata.arcgis.com (City of Red Deer AGOL org `8EWx42uKeMSu9Wcl`),
ArcGIS Hub: `arcgis_hub_*` (`portal="red_deer"`), config-only. ~170 items
confirmed live 2026-09-22; smoke test passed (search "trail", item detail,
feature queries on both an AGOL-hosted layer and a self-hosted
`arcgis.reddeer.ca` FeatureServer). Quirks: the city's curated
`data.reddeer.ca` is a bespoke ASP.NET catalogue (~22 datasets, no API) and
stays uncovered; `data-reddeer.opendata.arcgis.com` returns 401 (private org
id); the Hub mixes in orthophoto Image Services, duplicate-titled layers,
and many Survey123 `_form`/`_results` layers, so filter by `item_type` or
keyword.

## Surrey

**Status:** Shipped.

opendata-surrey.hub.arcgis.com (City of Surrey Open Data Catalog), ArcGIS
Hub: `arcgis_hub_*` (`portal="surrey"`), 3 tools, same shape. The city's
older CKAN-era URL, `data.surrey.ca`, now 301-redirects here — confirmed
live this is a full platform migration, not a parallel CKAN portal to also
cover.

## Halton Region

**Status:** Shipped via its municipalities (re-checked 2026-09-27).

Re-checked 2026-09-27: `opendata.halton.ca` and `data.halton.ca` still do
not resolve, `halton.ca/open-data` is a 404, and ArcGIS Online has no
Halton Region open-data group or Hub site. Three of the region's four
municipalities run Hub sites whose API answers, added config-only:

- Oakville: `portal-exploreoakville.opendata.arcgis.com`, "Town of
  Oakville Open Data Portal", 157 datasets (transit, budget results,
  citizen survey, energy use, infrastructure layers).
- Burlington: `navburl-burlington.opendata.arcgis.com`, "Navigate
  Burlington", 99 datasets (service business plans, facility energy,
  layers).
- Milton: `discover-milton.hub.arcgis.com`, "Discover the Town of
  Milton", 25 datasets. Its "Current Road Closures" layer can be empty.

Halton Hills (`tohhgis`) has no Hub site, only 7 loose public feature
services; not added. `plan_query` maps "Halton" to the three portals.

Earlier finding:

`opendata.halton.ca` does not resolve; no live Halton Region government
portal was found. Only a separate Conservation Halton ArcGIS Hub
(`conservationhalton-camaps.opendata.arcgis.com`) exists — confirmed live
this is a different body (a conservation authority, not the regional
government) and was not adopted as a substitute.

## Grande Prairie (City)

**Status:** Shipped.

opendata-cityofgp.hub.arcgis.com, ArcGIS Hub: `arcgis_hub_*`
(`portal="grande_prairie"`), 3 tools, same shape. Distinct government and
catalogue from the County of Grande Prairie below — confirmed live these are
two separate portals, not a split of one. English-only. 41 datasets
confirmed live.

## St. Albert

**Status:** Shipped.

data.stalbert.ca (City of St. Albert Open Data Portal), ArcGIS Hub:
`arcgis_hub_*` (`portal="st_albert"`), 3 tools, same shape.
`prd-stalbert.opendata.arcgis.com` is the same site under its raw Hub
subdomain — `data.stalbert.ca` is the confirmed-live canonical public alias,
used as `DOMAIN`. English-only. 34 datasets confirmed live.

## Edmonton Metropolitan Region Board

**Status:** Shipped.

emrgis.emrb.ca (EMRGIS, also served at
gis-capitalregion.opendata.arcgis.com), ArcGIS Hub: `arcgis_hub_*`
(`portal="emrb"`), config-only. 85 regional growth-plan datasets confirmed
live 2026-09-22; smoke test passed. An earlier check of emrb.ca's home page
found no data links -- the Hub lives on its own subdomain.

## ArcGIS Hub download links

Fixed 2026-09-27, found while adding Cochrane and Okotoks; it affected
every `arcgis_hub_*` portal. `arcgis_hub_get_dataset` built its
download links as `/api/download/v1/items/<id>/<fmt>?layers=0` from the
Hub item's id, and two things were wrong, both checked live:

- A layer-level item's Hub id is `<item id>_<layer id>` (Cochrane
  "Parks": `93d9602d6f7a40beae96106397ee3a83_18`; Ottawa items end in
  `_1`). The download API rejects it with HTTP 400 "itemId must match
  /^(?:(?![g-z])[a-z0-9])+$/". It wants the bare 32-character id.
- `layers` must be the layer's own id, not its position: Cochrane
  "Parks" (18) and Okotoks "Floodway" (35) answer `layers=0` with 404.

Links now use the bare id with the suffix's layer id, or, for an id
without a suffix, the service's first layer id (the same lookup
`query_feature_layer` uses, now cached for an hour). The live smoke test
now requests the csv link of the item it queried and expects HTTP 302
(redirect to the file) or 202 (export queued); all 37 portals with
working downloads pass. Red Deer's download API answers HTTP 500 "A
domain record with hostname = reddeer.opendata.arcgis.com does not
exist" for every item, and `hub.arcgis.com` only reports an export
"Pending" since 2024, so that portal is marked `downloads=False` and
returns no links; its layers remain queryable.

## Brampton, Kingston, Kelowna, Barrie, Burnaby, Fredericton, Greater Sudbury, Guelph

Added config-only on 2026-09-29 after a probe of guessed ArcGIS Hub domains
against `/api/search/v1/collections/dataset/items` (the older `/api/v3`
endpoint answers with the global ArcGIS count for any host, so it cannot
show whether a site exists). Datasets confirmed live: Brampton 352
(`geohub.brampton.ca`), Kingston 201 (`opendatakingston.cityofkingston.ca`),
Kelowna 133 (`opendata.kelowna.ca`), Barrie 113 (`opendata.barrie.ca`),
Burnaby 66 (`data.burnaby.ca`), Fredericton 66
(`data-fredericton.opendata.arcgis.com`), Greater Sudbury 50
(`opendata.greatersudbury.ca`), Guelph 41 (`explore.guelph.ca`). The smoke
test passed for all eight (search, detail, feature query, CSV link).
`plan_query` maps each city; Brampton now also lists the Peel portal.

Guessed domains that returned 401, 400, 404 or did not resolve (Richmond,
Vaughan, St. John's, Moncton, Nanaimo, Abbotsford, Delta, Whitehorse,
Thunder Bay, Coquitlam, Langley, Kamloops, Brantford, Whitby, Oshawa, New
Westminster, Saanich, Peterborough, Prince George, Niagara) are probably
wrong domains, not confirmed absences.

## Moncton, Abbotsford, Whitby, Oshawa, Niagara Falls, Niagara Region, St. Catharines, Thunder Bay, Peterborough, Coquitlam, Saanich, Kamloops, Prince George

Added config-only on 2026-09-29. The guessed domains of the previous batch were
wrong, so the real ones came from an ArcGIS Online search for public Hub Site
Applications titled with each city, then each was checked against
`/api/search/v1/collections/dataset/items` (a made-up host answers with no
count, a real one with `numberMatched`). Datasets confirmed live: Moncton 54
(`ouvert.moncton.ca`), Abbotsford 136 (`opendata-abbotsford.hub.arcgis.com`),
Whitby 19 (`geohub-whitby.hub.arcgis.com`), Oshawa 314
(`city-oshawa.opendata.arcgis.com`), Niagara Falls 301 (`open.niagarafalls.ca`),
Niagara Region 44 (`open.niagararegion.ca`), St. Catharines 12
(`st-catharines-open-data-2-stcatharines.hub.arcgis.com`), Thunder Bay 67
(`opendata.thunderbay.ca`), Peterborough 94 (`data-ptbo.opendata.arcgis.com`),
Coquitlam 27 (`data.coquitlam.ca`), Saanich 51
(`opendata-saanich.hub.arcgis.com`), Kamloops 156
(`mydata-kamloops.opendata.arcgis.com`), Prince George 175
(`data-cityofpg.opendata.arcgis.com`). The smoke test passed for twelve
(search, detail, feature query, CSV link). Oshawa passed search and detail, and
its one feature-layer query (a slow layer) timed out on two runs; another Oshawa
layer (drop-in program schedule) answers, and most of its 314 items are
CSV-only. The `/api/v3` endpoint answers with the global ArcGIS count for any
host, so it cannot show whether a site exists.

Not shipped: Langley (the site answers but the Hub search API returns no
count), Richmond BC, Vaughan, Richmond Hill, Nanaimo, North Vancouver, St.
John's, Sault Ste. Marie, Wood Buffalo, Charlottetown, Whitehorse and
Yellowknife (no public Hub site found by that search; several use other
platforms). Not yet re-checked by another route.

## Police and conservation authority portals (Toronto and Ottawa police, six Ontario conservation authorities)

Added config-only on 2026-09-30, together with the Ontario GeoHub (a provincial
geospatial hub, 242 datasets, `ontariogeohub-lio.opendata.arcgis.com`) and
Parks Canada (`data-apca.opendata.arcgis.com`, 25 datasets). Found by an
ArcGIS Online search for public Hub Site Applications (the keyword "police"
alone returned only United States agencies), then confirmed by the Hub
`numberMatched`: Toronto Police Public Safety Data Portal 71
(`data.torontopolice.on.ca`; the older `torontops.hub.arcgis.com` lists 111
items, mostly map layers, and has the same shootings and neighbourhood crime
rate datasets), Ottawa Police 98 items but only the `all` collection (13
feature layers, so searches default to Feature Service, as for Okotoks),
Conservation Halton 36, Credit Valley Conservation 2, Niagara Peninsula 31,
Hamilton 31, Central Lake Ontario 27 and Quinte 14. The smoke test passed for
all ten.

Not added: a search hit named "Conservation Open Data" is the California
Department of Conservation. Peel, Halton, York, Durham, Waterloo, London,
Hamilton, Calgary, Saskatoon, Winnipeg, Halifax and Vancouver police sites
were probed (several guessed domains) and none answered; Calgary and Winnipeg
police data already sit on their cities' Socrata portals. Other conservation
authorities (Grand River, Toronto and Region, Lake Simcoe, Rideau Valley and
others) did not turn up a public Hub site in that search.

## More municipal portals, rechecked 2026-10-02

Method: an ArcGIS Online search for public Hub Site Applications titled with each
city (also Web Mapping Applications and Feature Services for the named targets),
web searches for each target's own open-data page, then for every host found
`/api/search/v1/collections/dataset/items` (a real Hub answers with
`numberMatched`), the site's `robots.txt` (all Hub sites serve the platform
default: `Crawl-delay: 60`, `/api` not disallowed) and the licence text on
sampled items and on the city's terms page. Added config-only; the Hub smoke
test (search, detail, feature query, CSV link, error paths) passed for all
twelve. Penticton's CSV link answered HTTP 400 once for one layer and 302 on
the rerun, so treat its download links as occasionally flaky.

Added (datasets, licence):

- Delta, `opendata-deltabc.hub.arcgis.com` (16): Open Government Licence; the
  city moved to this ArcGIS Hub from its older catalogue in January 2026.
- Yellowknife, `opendata.yellowknife.ca` (6): the city's Open Data Licence v1
  allows commercial reuse with attribution. Portal is a classic Hub Open Data
  site.
- Cambridge ON, `opendata-cityofcambridge.hub.arcgis.com` (48): Open Data
  Licence v2.1, commercial reuse with attribution. A second site,
  `data-cityofcambridge.opendata.arcgis.com` (425), is a personal-account site
  using Region of Waterloo licence text, so it was not used.
- Maple Ridge, `gis-mapleridge.opendata.arcgis.com` (61): Open Government
  Licence. `opengov2-mapleridge.opendata.arcgis.com` (88) is a second site.
- Pickering, `data-cityofpickering.hub.arcgis.com` (268): City of Pickering
  Open Data Licence v1 (commercial reuse); many items are Central Lake Ontario
  Conservation layers under that authority's own licence.
- Sarnia (14), Saint John NB `catalogue-saintjohn.opendata.arcgis.com` (233,
  bilingual titles), Port Moody `data.portmoody.ca` (104), White Rock
  `data.whiterockcity.ca` (59), Penticton `open.penticton.ca` (136),
  Orangeville (18), Canmore (19): each has an Open Government Licence style
  licence that permits reuse.

Not added:

- Richmond BC, Vaughan, Richmond Hill, North Vancouver (city), St. John's,
  Sault Ste. Marie, Wood Buffalo, Charlottetown: not found. No Hub Site
  Application, web page or guessed domain (`opendata.<city>`, `data-<city>.
  opendata.arcgis.com`, 401, 400 or no DNS) turned up a public portal. The
  ArcGIS Online hits for "Richmond" are Richmond, Virginia.
- Nanaimo: `data.nanaimo.ca` redirects to nanaimo.ca's Open Data Catalogue, the
  City's own Open Data Publisher with a REST API; different platform with no
  adaptor.
- Whitehorse: `data.whitehorse.ca` is a static download page, not a platform
  with an API; different platform with no adaptor.
- District of North Vancouver: `geoweb.dnv.org/data` is the district's custom
  GEOweb (the City of North Vancouver is a separate municipality); no adaptor.
- Langley (City): `data-langleycity.opendata.arcgis.com` answers 404 on the
  search API; unchanged from the earlier finding.
- Belleville (43 datasets): the item licence limits use to personal,
  non-commercial purposes. Terms.
- Welland (32): the licence points to a terms-of-use page that is rendered by
  JavaScript, so its text could not be verified. Terms.
- Drummondville (6), Caledon (5), Haldimand (10), Cobourg (13), Edmundston (18),
  Chatham-Kent (11 and a 100-item census site), Fort St. John (55): small
  catalogues or no licence stated; not added, could be revisited.
- Corner Brook, Brantford, Innisfil, Scugog, Campbell River: the site found
  answered 404, 401 or 400 on the search API. Clarington and North Bay's
  `explore.northbay.ca` and Leduc's `data.leduc.ca` answer but list no
  datasets in the dataset collection.
- Hamilton stays out (blocks automated requests, see the roadmap).
