# Roadmap

Source coverage plan for MapleStats MCP. This is the authoritative list of
what the package will cover — scoped by Daniel on 2026-09-14, superseding
any narrower or broader source list implied elsewhere.

Current implementation snapshot (2026-09-22): shipped modules cover
Statistics Canada, the Bank of Canada, federal CKAN, IRCC Express Entry,
Environment and Climate Change Canada / MSC GeoMet, CMHC, ISED
(Corporations Canada lookup + Spectrum Management System + CIPO
Canadian Trademarks Database search), Elections Canada (CKAN bulk/
DataStore data plus a dedicated `elections_financial_returns` module for
candidate campaign financial returns), CRA's digital economy GST/HST
registry, Health Canada and ESDC (via `ckan_*`), NRCan's
National Burned Area Composite, Alberta (CKAN plus a dedicated `aer`
module for Alberta Energy Regulator statistical reports),
British Columbia (CKAN plus a dedicated `bcgw` module for the BC
Geographic Warehouse's WFS layers), Ontario, Quebec (CKAN, including
MSSS ER-wait-time and health-installation DataStore resources), Nova
Scotia, New Brunswick,
Manitoba, Saskatchewan, Prince Edward Island, Newfoundland and Labrador,
the Northwest Territories, Yukon, Montreal, Toronto, Regina, Hamilton,
London, Kitchener, Windsor, Saskatoon, Victoria, Surrey, Calgary,
Edmonton, Winnipeg, Ottawa, Halifax, Mississauga, Peel Region, Durham
Region, the Region of Waterloo, Metro Vancouver, York Region, Markham,
Newmarket, Aurora, Medicine Hat, the City and County of Grande
Prairie, St. Albert, Lethbridge, Airdrie, Strathcona County, and
Vancouver (Laval and Gatineau are covered through the existing Quebec
CKAN module, not a dedicated one). CRA, OSFI, and CRTC's own data are
likewise already covered through the federal CKAN module -- see the
Census and specialized federal agencies section below for what each
turned out to need (or not need). All 10 provinces and
2 of 3 territories are now shipped (Nunavut is Blocked). The rows below
are the source-of-truth for remaining work; each row has its own status.

Status values: `Not started` / `In progress` / `Shipped` / `Blocked`.
A source is marked `Shipped` only after its implemented functions and
important portal-specific behavior have been checked against live responses;
the Notes column records limits or remaining portal-specific work. `Not CKAN`
is retained only where it communicates an intentional platform boundary: the
portal is identified, but it needs a different adaptor rather than the CKAN
adaptor.

## Federal

Only these five get dedicated, own-adaptor investigation and a named row
in this table. This does **not** exclude other departments' data from
the project: `ckan` (`portal="federal"`) is a generic client that already reaches
every organization publishing on open.canada.ca, not just these five —
confirmed live 2026-09-21 that Health Canada (`hc-sc`, 2,983 datasets)
and ESDC (`esdc-edsc`, 266 datasets) are both fully searchable today via
the existing `ckan_search_datasets`/`ckan_get_dataset`/
`ckan_datastore_search` tools, the same as CRA/CRTC/OSFI/Elections
Canada below. Corrected 2026-09-21 after this was misread as "no other
federal department's CKAN data is in scope" — that was never the
intent. What remains genuinely excluded is narrow, record-lookup-shaped
data outside CKAN's dataset model entirely (Health Canada's Drug
Product Database, per-record recalls/safety-alert lookup tools, the
nutrient file) — not
general public-health, labour-market, or other departmental statistics
published as ordinary CKAN datasets, which are in scope like any other
organization's CKAN data (see the Health Canada and ESDC rows in the
Census and specialized federal agencies section below).

| Source | Status | Notes |
|---|---|---|
| Statistics Canada (StatCan) | Shipped | WDS + SDMX + RDaaS: table/cube discovery, metadata, series retrieval, change detection, classifications; the 2021 Census Profile SDMX API and its pre-2021 archived bulk-download equivalent (see the Census row below); and The Daily's official Atom feeds (release bulletin, see below). |
| Bank of Canada | Shipped | Valet API: exchange rates, interest rates, commodity prices, CPI/inflation, series metadata. |
| Federal Open Data (CKAN, open.canada.ca) | Shipped | ~48K-dataset catalogue: search, dataset details, organizations, resources, licenses. |
| IRCC Immigration | Shipped | Express Entry rounds of invitations (tools prefixed `ircc_`): draw history, CRS cutoffs, invitations issued, and candidate-pool CRS score distribution, from a static JSON feed at … [Details](docs/findings/federal-sources.md#ircc-immigration) |
| Weather / Climate (Environment Canada MSC GeoMet) | Shipped | api.weather.gc.ca, MSC GeoMet-OGC-API (OGC API - Features): `eccc_*`, 4 generic tools (search/list/get collection, query items) covering all ~100 published collections — weather alerts, current surface observations (SWOB), city forecasts … [Details](docs/findings/federal-sources.md#weather--climate-environment-canada-msc-geomet) |

Audited 2026-09-19: spot-checked the AHCCD (`ahccd-stations`/`-annual`/`-monthly`/`-seasonal`/`-trends`) and `climate-normals` collections specifically, since neither had been queried live beyond a one-off check at build time. No functional bug (the generic client handles both correctly), but found the module's own gotchas doc had overgeneralized its bilingual-field-naming claim — confirmed live that bilingual fields use at least three different conventions depending on the collection, not one: `_en`/`_fr` suffixes (`weather-alerts`), `E_`/`F_` prefixes (`climate-normals`), and a single double-underscore-joined field per concept (every `ahccd-*` collection, e.g. `station_name__nom_station` — not two separate fields at all). Also found and documented a real missing-value trap: AHCCD uses `-9999.9` as a sentinel for missing pressure/temperature readings, inconsistently alongside a genuine `null` for the same "no data" case within the same field — confirmed live in `ahccd-annual`. The generic pass-through client does not (and should not) auto-correct this, since it has no per-field semantic knowledge, but `docs://eccc/gotchas` now warns explicitly rather than leaving it to be discovered the hard way. |

## Provincial (all 10)

All CKAN portals below (federal, provincial, territorial, municipal) were
consolidated on 2026-09-23 into one `ckan_*` tool family with a `portal`
argument (`modules/ckan/`), replacing ten per-portal modules; per-portal
tool counts in the rows below predate that change.

### Next provincial sequence

The four CKAN provinces, the Socrata pair, and the ArcGIS Hub trio are now
shipped. The remaining provincial work should stay adaptor-first so one
implementation unlocks several provinces:

For this provincial phase, "coverage" means the official/main provincial
portal. Municipal portals and secondary departmental or specialized portals
are out of scope unless they are later promoted explicitly.

| Sequence | Adaptor | Provincial coverage | Reason |
|---|---|---|---|
| 1 | Socrata | Nova Scotia, New Brunswick | Shipped 2026-09-18: `socrata_*` (`portal="ns"`)/`socrata_*` (`portal="nb"`), verified live against `api.us.socrata.com`'s catalog API, the per-domain Views API, and the SODA row-query API for both `data.novascotia.ca` and `gnb.socrata.com`. [Details](docs/findings/provincial-sources.md#sequence-1-socrata) |
| 2 | ArcGIS Hub / ArcGIS REST | Manitoba, Saskatchewan, Prince Edward Island | Shipped 2026-09-18: `arcgis_hub_*` (`portal="mb"`)/`arcgis_hub_*` (`portal="sk"`)/`arcgis_hub_*` (`portal="pe"`), verified live against all three portals' Hub Search API v3 (`/api/search/v1/collections/dataset/items`), the classic ArcGIS … [Details](docs/findings/provincial-sources.md#sequence-2-arcgis-hub--arcgis-rest) |
| 3 | Newfoundland and Labrador custom portal | Newfoundland and Labrador | The provincial open-data catalogue has its own page-based interface and downloadable tabular/spatial files. Map its live endpoints separately after the two reusable adaptors are working; do not force it into CKAN or Socrata. This is now the next provincial implementation. |

| Province | Status | Portal (reference) |
|---|---|---|
| Ontario | Shipped | data.ontario.ca, CKAN Action API: `ckan_*` (`portal="on"`), 9 tools (added `ckan_datastore_search` 2026-09-20). Bilingual dataset fields, tags, groups, organizations, and resources were verified against live responses. |
| British Columbia | Shipped | catalogue.data.gov.bc.ca, CKAN Action API: `ckan_*` (`portal="bc"`), 10 tools (search, dataset/org/resource/license detail, tags, groups, and -- added 2026-09-20 -- `ckan_datastore_search` for row-level queries against a DataStore-active … [Details](docs/findings/provincial-sources.md#british-columbia) |
| Quebec | Shipped | donneesquebec.ca (API at `/recherche/api/3/action/`), CKAN Action API: `ckan_*` (`portal="qc"`), 9 tools (added `ckan_datastore_search` 2026-09-20, confirmed live against a real-time weather-station-observations resource). [Details](docs/findings/provincial-sources.md#quebec) |
| Alberta | Shipped | open.alberta.ca, CKAN Action API: `ckan_*` (`portal="ab"`), 8 tools (added `ckan_datastore_search` 2026-09-20). [Details](docs/findings/provincial-sources.md#alberta) |
| Manitoba | Shipped | geoportal.gov.mb.ca (Data MB), ArcGIS Hub: `arcgis_hub_*` (`portal="mb"`), 3 tools (dataset search, item detail with download links, direct FeatureServer/MapServer row queries). [Details](docs/findings/provincial-sources.md#manitoba) |
| Saskatchewan | Shipped | geohub.saskatchewan.ca (Saskatchewan GeoHub), ArcGIS Hub: `arcgis_hub_*` (`portal="sk"`), 3 tools, same shape as Manitoba's. [Details](docs/findings/provincial-sources.md#saskatchewan) |
| Nova Scotia | Shipped | data.novascotia.ca, Socrata (SODA): `socrata_*` (`portal="ns"`), 5 tools (catalogue search, dataset detail, categories, tags, direct SoQL row queries). English-only. Verified against live discovery/Views/SODA responses. |
| New Brunswick | Shipped | gnb.socrata.com, Socrata (SODA): `socrata_*` (`portal="nb"`), 5 tools (catalogue search, dataset detail, categories, tags, direct SoQL row queries). [Details](docs/findings/provincial-sources.md#new-brunswick) |
| Newfoundland and Labrador | Shipped | `opendata.gov.nl.ca`, custom HTML catalogue: local search/pagination over tabular and spatial listings, tag discovery, dataset metadata, and official CSV/XLS/TXT/KMZ/shapefile download links. [Details](docs/findings/provincial-sources.md#newfoundland-and-labrador) |
| Prince Edward Island | Shipped | data.princeedwardisland.ca, ArcGIS Hub: `arcgis_hub_*` (`portal="pe"`), 3 tools, same shape as Manitoba's. At least one item's underlying service reports an empty `layers` list with its one queryable table at a non-zero id (2) — the default-layer-index resolution this adaptor added because of that applies here too. Verified against live responses. |

## Territorial (all 3)

| Territory | Status | Portal (reference) |
|---|---|---|
| Northwest Territories | Shipped | opendata.gov.nt.ca, CKAN Action API: `ckan_*` (`portal="nt"`), 9 tools (added `ckan_datastore_search` 2026-09-20; also added a `datastore_active` field to `ResourceInfo`, which this module had never tracked at all before). English-only. Small catalogue (341 datasets). |
| Yukon | Shipped | open.yukon.ca, CKAN Action API: `ckan_*` (`portal="yt"`), 8 tools. English-only (site UI is bilingual-chrome only; dataset content is not). 3,841 datasets. [Details](docs/findings/territorial-sources.md#yukon) |
| Nunavut | Blocked | Investigated 2026-09-19: no dedicated open-data portal exists (`opendata.gov.nu.ca`/`data.gov.nu.ca` don't resolve). [Details](docs/findings/territorial-sources.md#nunavut) |

## Municipal (all that apply — established open-data portals)

> **2026-09-22 consolidation:** the 28 ArcGIS Hub modules and 5 Socrata
> modules in this roadmap (provincial and municipal) were merged into two portal-keyed modules,
> `modules/arcgis_hub/` and `modules/socrata/`. Their code differed only
> in the portal domain, so every per-portal `arcgis_<portal>_*` and
> `socrata_<portal>_*` tool family became `arcgis_hub_*` / `socrata_*`
> with a `portal` argument (`arcgis_hub_list_portals`/
> `socrata_list_portals` enumerate the keys). Their rows keep their
> original shipping notes; the prefixes have been updated.

Cities and regions with a verified open-data portal. This list is a
starting inventory, not a hard ceiling — add a city/region here once its
portal is confirmed to exist and be reachable.

| Municipality / region | Status | Portal (reference) |
|---|---|---|
| Toronto | Shipped | open.toronto.ca (UI) / `ckan0.cf.opendata.inter.prod-toronto.ca` (Action API host — the UI domain is not the API), CKAN Action API: `ckan_*` (`portal="toronto"`), 8 tools (no groups — confirmed unused; added `ckan_datastore_search` 2026-09-20). English-only. 557 datasets. |
| Montreal | Shipped | donnees.montreal.ca, CKAN Action API: `ckan_*` (`portal="montreal"`), 9 tools (added `ckan_datastore_search` 2026-09-20; also added a `datastore_active` field to `ResourceInfo`, which this module had never tracked at all before). [Details](docs/findings/municipal-sources.md#montreal) |
| Laval | Shipped (via `ckan_*` (`portal="qc"`)) | No standalone portal — Laval publishes through the shared Données Québec CKAN instance (donneesquebec.ca) already covered by `ckan_*` (`portal="qc"`), confirmed live: `ville-de-laval` is a real organization there. No dedicated module needed. |
| Gatineau | Shipped (via `ckan_*` (`portal="qc"`)) | Same as Laval: Gatineau publishes through the shared Données Québec CKAN instance, confirmed live (`ville-de-gatineau` organization) — already covered by `ckan_*` (`portal="qc"`), no dedicated module needed. |
| Quebec City | Shipped (via `ckan_*` (`portal="qc"`)) | Checked 2026-09-24: Ville de Québec publishes through Données Québec as organization `ville-de-quebec` (35 datasets, e.g. `vque_26` trees, `vque_18` streets); `donnees.ville.quebec.qc.ca` does not resolve. No dedicated module needed. |
| Longueuil | Shipped (via `ckan_*` (`portal="qc"`)) | Checked 2026-09-24: organization `ville-de-longueuil` on Données Québec (31 datasets). |
| Sherbrooke | Shipped (via `ckan_*` (`portal="qc"`)) | Checked 2026-09-24: organizations `ville-de-sherbrooke` (7 datasets) and `ville-de-sherbrooke-donnees-geomatiques` on Données Québec. |
| Trois-Rivières | Shipped (via `ckan_*` (`portal="qc"`)) | Checked 2026-09-24: organization `ville-de-trois-rivieres` on Données Québec (40 datasets). |
| Regina | Shipped | openregina.ca, CKAN Action API: `ckan_*` (`portal="regina"`), 10 tools (search, dataset/organization/resource/license detail, tags, curated thematic groups, and -- added 2026-09-20 -- `ckan_datastore_search`, confirmed live against a real … [Details](docs/findings/municipal-sources.md#regina) |
| Hamilton | Shipped | open.hamilton.ca (Open Hamilton), ArcGIS Hub: `arcgis_hub_*` (`portal="hamilton"`), 3 tools, same shape as the provincial ArcGIS Hub modules (search, item detail with download links, direct FeatureServer/MapServer row queries). English-only. |
| London | Shipped | opendata.london.ca (City of London Open Data), ArcGIS Hub: `arcgis_hub_*` (`portal="london"`), 3 tools, same shape. English-only. |
| Kitchener | Shipped | open-kitchenergis.opendata.arcgis.com (Kitchener GeoHub), ArcGIS Hub: `arcgis_hub_*` (`portal="kitchener"`), 3 tools, same shape. English-only. |
| Windsor | Shipped | open-data-portal-citywindsor.hub.arcgis.com (Windsor Open Data Portal), ArcGIS Hub: `arcgis_hub_*` (`portal="windsor"`), 3 tools, same shape. English-only; confirmed live this catalogue has zero datasets matching "water" despite 177 total datasets — not every catalogue matches every test keyword. |
| Saskatoon | Shipped | data-citysaskatoon.opendata.arcgis.com, ArcGIS Hub: `arcgis_hub_*` (`portal="saskatoon"`), 3 tools, same shape. English-only; small catalogue (10 datasets confirmed live). |
| Victoria | Shipped | opendata.victoria.ca (VicMap), ArcGIS Hub: `arcgis_hub_*` (`portal="victoria"`), 3 tools, same shape. English-only. |
| Surrey | Shipped | opendata-surrey.hub.arcgis.com (City of Surrey Open Data Catalog), ArcGIS Hub: `arcgis_hub_*` (`portal="surrey"`), 3 tools, same shape. English-only. The city's older CKAN-era URL, `data.surrey.ca`, now 301-redirects here — confirmed live this is a full platform migration, not a parallel CKAN portal to also cover. |
| Vancouver | Shipped | opendata.vancouver.ca, Opendatasoft (Explore API V2): `opendatasoft_vancouver_*`, 3 tools (dataset search, dataset detail with fields/download links, direct record queries with ODSQL filtering/sorting). [Details](docs/findings/municipal-sources.md#vancouver) |
| Calgary | Shipped | data.calgary.ca, Socrata (SODA): `socrata_*` (`portal="calgary"`), 5 tools, same shape as Nova Scotia/New Brunswick's. English-only. 413 datasets confirmed live. |
| Edmonton | Shipped | data.edmonton.ca, Socrata (SODA): `socrata_*` (`portal="edmonton"`), 5 tools, same shape. English-only. 1,421 datasets confirmed live — the largest Socrata catalogue this server covers. |
| Ottawa | Shipped | open.ottawa.ca, ArcGIS Hub: `arcgis_hub_*` (`portal="ottawa"`), 3 tools, same shape as the other ArcGIS Hub municipal modules (migrated off CKAN per the city's own 2023/24 announcement). English-only. 241 datasets confirmed live. |
| Winnipeg | Shipped | data.winnipeg.ca, Socrata (SODA): `socrata_*` (`portal="winnipeg"`), 5 tools, same shape. English-only. 235 datasets confirmed live. |
| Halifax | Shipped | data-hrm.hub.arcgis.com (Halifax Regional Municipality), ArcGIS Hub: `arcgis_hub_*` (`portal="halifax"`), 3 tools, same shape. `catalogue.open.halifax.ca` does not resolve; this is the confirmed-live real domain. English-only. 245 datasets confirmed live. |
| Mississauga | Shipped | data.mississauga.ca, ArcGIS Hub: `arcgis_hub_*` (`portal="mississauga"`), 3 tools, same shape. English-only. 207 datasets confirmed live. |
| York Region | Shipped | insights-york.opendata.arcgis.com, ArcGIS Hub: `arcgis_hub_*` (`portal="york"`), 3 tools, same shape. English-only. 224 datasets confirmed live. A second, separate York-affiliated Hub site (`opendata-yorkcosc.hub.arcgis.com`) also exists but was not adopted as canonical. |
| Markham | Shipped | data-markham.opendata.arcgis.com, ArcGIS Hub: `arcgis_hub_*` (`portal="markham"`), 3 tools, same shape. [Details](docs/findings/municipal-sources.md#markham) |
| Newmarket | Shipped | navigate-newmarket.hub.arcgis.com (published as "NavigateNewmarket"), ArcGIS Hub: `arcgis_hub_*` (`portal="newmarket"`), 3 tools, same shape. Not part of a shared "York Region cluster" instance — its own independent Hub deployment, confirmed live. English-only. 20 datasets confirmed live. |
| Aurora | Shipped | town-of-aurora-data-hub-aurora.hub.arcgis.com (Town of Aurora, Ontario), ArcGIS Hub: `arcgis_hub_*` (`portal="aurora"`), 3 tools, same shape. [Details](docs/findings/municipal-sources.md#aurora) |
| Peel Region | Shipped | data.peelregion.ca, ArcGIS Hub: `arcgis_hub_*` (`portal="peel"`), 3 tools, same shape. English-only. 88 datasets confirmed live. |
| Durham Region | Shipped | opendata.durham.ca, ArcGIS Hub: `arcgis_hub_*` (`portal="durham"`), 3 tools, same shape. **Found and fixed a real bug in the shared `default_layer_index` helper (`shared/arcgis.py`) while shipping this row**: Durham's catalogue items point … [Details](docs/findings/municipal-sources.md#durham-region) |
| Halton Region | Unknown | `opendata.halton.ca` does not resolve; no live Halton Region government portal was found. Only a separate Conservation Halton ArcGIS Hub (`conservationhalton-camaps.opendata.arcgis.com`) exists — confirmed live this is a different body (a conservation authority, not the regional government) and was not adopted as a substitute. |
| Waterloo Region | Shipped | rowopendata-rmw.opendata.arcgis.com (Region of Waterloo), ArcGIS Hub: `arcgis_hub_*` (`portal="waterloo_region"`), 3 tools, same shape. [Details](docs/findings/municipal-sources.md#waterloo-region) |
| Metro Vancouver | Shipped | open-data-portal-metrovancouver.hub.arcgis.com, ArcGIS Hub: `arcgis_hub_*` (`portal="metro_vancouver"`), 3 tools, same shape. English-only. 39 datasets confirmed live. |
| Medicine Hat | Shipped | opendata.medicinehat.ca, ArcGIS Hub: `arcgis_hub_*` (`portal="medicine_hat"`), 3 tools, same shape. English-only. 40 datasets confirmed live. |
| Grande Prairie (City) | Shipped | opendata-cityofgp.hub.arcgis.com, ArcGIS Hub: `arcgis_hub_*` (`portal="grande_prairie"`), 3 tools, same shape. Distinct government and catalogue from the County of Grande Prairie below — confirmed live these are two separate portals, not a split of one. English-only. 41 datasets confirmed live. |
| Grande Prairie (County) | Shipped | county-of-grande-prairie-open-data-cogp.hub.arcgis.com, ArcGIS Hub: `arcgis_hub_*` (`portal="grande_prairie_county"`), 3 tools, same shape, self-hosted service domain (`opendataservices.countygp.ab.ca`) rather than `*.arcgis.com`. **Real … [Details](docs/findings/municipal-sources.md#grande-prairie-county) |
| St. Albert | Shipped | data.stalbert.ca (City of St. Albert Open Data Portal), ArcGIS Hub: `arcgis_hub_*` (`portal="st_albert"`), 3 tools, same shape. `prd-stalbert.opendata.arcgis.com` is the same site under its raw Hub subdomain — `data.stalbert.ca` is the confirmed-live canonical public alias, used as `DOMAIN`. English-only. 34 datasets confirmed live. |
| Lethbridge | Shipped | opendata.lethbridge.ca (Lethbridge Open Data Catalogue), ArcGIS Hub: `arcgis_hub_*` (`portal="lethbridge"`), 3 tools, same shape. [Details](docs/findings/municipal-sources.md#lethbridge) |
| Airdrie | Shipped | data-airdrie.opendata.arcgis.com (City of Airdrie Open Data), ArcGIS Hub: `arcgis_hub_*` (`portal="airdrie"`), 3 tools, same shape. English-only. 37 datasets confirmed live. |
| Strathcona County | Shipped | opendata-strathconacounty.hub.arcgis.com (Strathcona County Open Data), ArcGIS Hub: `arcgis_hub_*` (`portal="strathcona_county"`), 3 tools, same shape. English-only. 115 datasets confirmed live. |
| Parkland County | Shipped | opendata.parklandcounty.com, ArcGIS Hub: `arcgis_hub_*` (`portal="parkland_county"`), config-only. 20 datasets confirmed live 2026-09-22; smoke test passed (search, detail, feature query). Found via an Edmonton-metro coverage sweep. |
| Sturgeon County | Shipped | data-sturgeoncounty.opendata.arcgis.com (Sturgeon County Atlas), ArcGIS Hub: `arcgis_hub_*` (`portal="sturgeon_county"`), config-only. 29 datasets confirmed live 2026-09-22; smoke test passed. |
| Alberta Geological Survey | Shipped | geology-ags-aer.opendata.arcgis.com (AER's geology arm), ArcGIS Hub: `arcgis_hub_*` (`portal="alberta_geological_survey"`), config-only. 41 datasets confirmed live 2026-09-22; smoke test passed. |
| Edmonton Police Service | Shipped | Community Safety Data Portal feature services on services9.arcgis.com (EPS's own ArcGIS Online org, found by resolving the Community Safety Map's item ids), not in data.edmonton.ca. [Details](docs/findings/municipal-sources.md#edmonton-police-service) |
| Edmonton Metropolitan Region Board | Shipped | emrgis.emrb.ca (EMRGIS, also served at gis-capitalregion.opendata.arcgis.com), ArcGIS Hub: `arcgis_hub_*` (`portal="emrb"`), config-only. 85 regional growth-plan datasets confirmed live 2026-09-22; smoke test passed. An earlier check of emrb.ca's home page found no data links -- the Hub lives on its own subdomain. |
| Edmonton Transit Service real-time | Shipped | gtfs.edmonton.ca GTFS-Realtime (protobuf): new module `modules/ets/` (`ets_*`, 3 tools: vehicle positions, stop predictions, service alerts). [Details](docs/findings/municipal-sources.md#edmonton-transit-service-real-time) |
| EPCOR Edmonton water quality | Shipped | New module `modules/epcor/` (`epcor_*`, 2 tools). Daily treated-water readings come from the per-plant iframe `apps.epcor.ca/DailyWaterQuality/Default.aspx?zone=ELS|Rossdale` (7 days, year-less date labels), found 2026-09-22 by inspecting … [Details](docs/findings/municipal-sources.md#epcor-edmonton-water-quality) |
| Edmonton-metro gaps | Not shipped | Re-checked 2026-09-22 through ArcGIS Online group search: Leduc's Hub (data.leduc.ca) holds only a Terms of Use page; Spruce Grove's open-data group is empty; Fort Saskatchewan has none. [Details](docs/findings/municipal-sources.md#edmonton-metro-gaps) |
| Cochrane | Blocked | `data-cochranegis.opendata.arcgis.com` renders its public pages fine (HTTP 200) but its Hub Search API and DCAT feed both reject anonymous access (`GWM_0003: You do not have permissions...`, HTTP 401/404) — confirmed live with multiple … [Details](docs/findings/municipal-sources.md#cochrane) |
| Okotoks | Blocked | `okotoksmaps-okotoks.hub.arcgis.com` has the identical failure mode as Cochrane above — public pages load, API calls are rejected with the same `GWM_0003` error. Same re-investigation condition. |
| Red Deer | Shipped | reddeer.opendata.arcgis.com (City of Red Deer AGOL org `8EWx42uKeMSu9Wcl`), ArcGIS Hub: `arcgis_hub_*` (`portal="red_deer"`), config-only. ~170 items confirmed live 2026-09-22; smoke test passed (search "trail", item detail, feature … [Details](docs/findings/municipal-sources.md#red-deer) |

Shipped 2026-09-18: Hamilton, London, Kitchener, Windsor, Saskatoon,
Victoria, and Surrey (all ArcGIS Hub), Regina (CKAN), and Laval/
Gatineau (already covered via the shared `ckan_*` (`portal="qc"`) Données Québec
module, no dedicated module needed). Shipped 2026-09-19: Calgary,
Edmonton, and Winnipeg, reusing the existing `shared/socrata.py`
adaptor built for Nova Scotia/New Brunswick; and, later the same day,
Ottawa, Halifax, Mississauga, Peel Region, Durham Region, the Region
of Waterloo, Metro Vancouver, York Region, Markham, Newmarket, and
Aurora — eleven more ArcGIS Hub deployments, reusing the same
`shared/arcgis.py` adaptor with zero portal-specific code beyond
config (domain, rate limit, description strings). Also shipped
2026-09-19, an Alberta municipal/regional batch requested directly
(starting from Medicine Hat): Medicine Hat, the City of Grande
Prairie, the County of Grande Prairie, St. Albert, Lethbridge,
Airdrie, and Strathcona County — seven more, same adaptor, same zero
portal-specific code pattern. Cochrane and Okotoks were investigated
and found genuinely blocked (their Hub Search API rejects anonymous
access even though the public site renders); Red Deer's bespoke data.reddeer.ca was skipped then; its ArcGIS Hub
site was added later (see the Red Deer row). See the rows
above for what each shipment found, including two real bugs fixed in
the shared adaptor (Durham, generalized further by Lethbridge and the
County of Grande Prairie) and one wrong-city domain caught before
shipping (Aurora). Also shipped 2026-09-19: Vancouver, on a brand new
`shared/opendatasoft.py` adaptor built specifically for this row since
no existing adaptor covered the Opendatasoft platform — see its row
above for the platform quirks found. The smaller municipalities/
regions below remain their own rows, not yet shipped.

Open item: every city from the original example list (Hamilton,
London, Kitchener, Windsor, Regina, Saskatoon, Victoria, Surrey,
Laval, Gatineau, Calgary, Edmonton, Winnipeg) is now shipped or
covered, as are Ottawa, Vancouver, and every ArcGIS-Hub-confirmed
municipality/region this roadmap had previously only identified as
"Not CKAN" (Halifax, Mississauga, York Region, Markham, Newmarket,
Aurora, Peel Region, Durham Region, Region of Waterloo, Metro
Vancouver). Only Halton Region (no live government portal found)
remains open from that set. Inventory further major cities not yet
checked (e.g. Burnaby, Richmond, Vaughan, Kelowna,
St. John's, Barrie, Guelph, Kingston) and add each once a real portal
is confirmed.

## Census and specialized federal agencies

Sources beyond the core five federal modules and beyond generic
CKAN/portal coverage — each needs its own adaptor design.

| Agency / source | Status | Notes |
|---|---|---|
| Census (StatCan Census Program / Census Profile) | Shipped | Investigated and shipped 2026-09-20. The public Census Profile search tool (www12.statcan.gc.ca/census-recensement/...) is a legacy server-rendered ColdFusion (.cfm) app with no JSON API of its own -- confirmed live via network-request … [Details](docs/findings/specialized-federal-sources.md#census-statcan-census-program--census-profile) |
| StatCan catalogues, The Daily, Indicators, Delta File, and other documentation | Shipped | Investigated 2026-09-20 per a direct request. The Daily (StatCan's official release bulletin, www150.statcan.gc.ca/n1/dai-quo/) has no JSON API behind its own search/calendar pages -- confirmed live, plain server-rendered HTML -- but … [Details](docs/findings/specialized-federal-sources.md#statcan-catalogues-the-daily-indicators-delta-file-and-other-documentation) |

Also clarified per a direct question ("SDMX, CORD, NDM") what three recurring terms actually refer to, since all three appear throughout this project's StatCan work without ever being named directly: SDMX (Statistical Data and Metadata eXchange) is the ISO standard protocol already fully covered by both `modules/statcan/sdmx` (generic tables, XML) and `modules/statcan/census_profile` (2021 census, JSON) -- no separate coverage needed. CODR (Common Output Data Repository, confirmed via the DGUID reference document's own text) is StatCan's internal name for the data warehouse behind ordinary tables -- WDS/SDMX are already the public interface to it, not a separate API. "NDM" is the CSS/module namespace (`ndm-results`, `ndm-item`, `block-ndm-plugins`, `ndm-surveys-az`) seen across every Reference/Analysis/Data/surveys page built against this pass. Investigated further per a follow-up request ("NDM, investigate more"): StatCan's own public consultation pages from 2013-2014 use the URL slug pattern `ndm-nmd-*` (French `nmd-ndm-*`), explicitly titled "New Dissemination Model" (e.g. `statcan.gc.ca/en/consultation/2013/ndm-nmd-nt-eng` "New Dissemination Model – Navigation and Tables"), and the methodology publication "Statistics: Power from Data!" (catalogue 11-634-X, chapter 4.1, "Disseminating data through the website") independently corroborates this in prose, describing a 2012-2015 initiative to build "a new, single, mandatory output database ... that provides a common and consistent interface for all data products" and to modernize website navigation, taxonomy, and table structure -- exactly the surface (catalogue/navigation pages, not the data warehouse itself) where the `ndm-*` CSS classes appear. This is a credible, StatCan-sourced expansion (New Dissemination Model) for the namespace, though not a direct confirmation that today's Drupal 10 classes are literally named after that specific 2012-era project rather than reusing its name by convention. A separate, weaker usage exists in third-party packages (`cansim`, `statcanR`), which informally gloss "NDM" as "New Data Model" when referring to the post-2018 CANSIM-replacement table-numbering scheme (e.g. `17-10-0016-01`) -- a StatCan-unconfirmed community inference about the table-ID system, distinct from the website CSS namespace, and not conflated with it here. Investigated a fifth time per a direct question ("catalogues, PDFs, articles, documentation, all that?"): confirmed every Reference/Analysis search result's catalogue number resolves to a real, plain (no session-cookie quirk needed) detail page at `n1/en/catalogue/{number}` listing that document's actual downloadable files -- HTML and PDF, each a direct link, confirmed live. Added `statcan_reference_get_document_formats` to the same module. One real quirk found and handled: a series-level catalogue number's page (e.g. "16-511-X") has no formats of its own -- it instead lists that series' editions, each with its own catalogue number -- and the two page shapes are structurally identical (same link+date row layout), distinguished only by the table's own header text ("Format" vs "Titles"/"Titres"); an earlier version of this parser that assumed every such table was a formats table silently mislabelled 8 edition titles as "formats" for "16-511-X" before this was caught via the live smoke test and fixed. A second quirk: catalogue-number normalization is itself inconsistent -- "16-511-X" resolves with its dashes intact, but "46-28-0001202600100004" only resolves with dashes/spaces stripped (confirmed live, both directions) -- so the tool tries the number exactly as given first, then stripped, before raising NotFound. Investigated a sixth time per a direct request to check for PUMF (Public Use Microdata Files) access. Confirmed live that PUMF data files themselves are directly downloadable with no authentication at all: a real Census PUMF ZIP (`n1/pub/98m0001x/2023001/cen21_ind_98m0001x_part_rec21.zip`, ~173 MB) answers HTTP 200 with `Content-Type: application/zip` on a bare unauthenticated request. The open question was discoverability, not access. Reference resources only indexes PUMF *user-guide* documentation (category "Surveys and statistical programs – Documentation"), not the PUMF products themselves; the actual product listings (category "Public use microdata") turned out to live in a third catalogue on the same Drupal engine, "Data" (`n1/en/type/data`, French `n1/fr/type/donnees`, both confirmed live, 13,342+ items) -- identical structure and quirks to Reference/Analysis, so `CATALOGUE_CONFIG` was extended with a third entry and a `statcan_reference_search_data` tool added at effectively zero new parsing code, the same generalization pattern used for Analysis. Confirmed live: searching "Public Use Microdata Files" there returns 144 results, including real PUMF catalogue numbers (71M0001X for the Labour Force Survey, 98M0001X for the Census) alongside ordinary table PIDs already reachable via WDS/SDMX. A PUMF's own catalogue-number page (via the existing `get_document_formats`) resolves one HTML link, which itself leads one hop further to a bespoke, per-product static page (e.g. `n1/pub/98m0001x/index-eng.htm`, listing every Census PUMF edition from 1991-2021) that is a genuinely different page shape from the Drupal engine -- not parsed generically here, left as a link for the caller to follow, the same design choice already used for the editions case. Investigated a seventh time with a final "leave nothing out" exhaustiveness pass: re-checked StatCan's GitHub org (205 repos, internal platform tooling, nothing exposing a new public API), Trade Data Online (confirmed an ISED product built on StatCan source data, not StatCan's own; StatCan's own equivalent, Canadian International Merchandise Trade, has no live API either), the Postal Code Conversion File (confirmed licensed/restricted, no free programmatic access), My StatCan (confirmed a pure email-subscription layer over The Daily, no separate API), the Business Register (confirmed confidential under the Statistics Act, aggregate-only), and Research Data Centres/Real Time Remote Access (confirmed security-screened microdata-lab access, no API) -- all correctly out of scope, nothing new. One genuine new surface was found: `geo.statcan.gc.ca/geo_wa/rest/services`, a live Esri ArcGIS REST (Map/Feature Service) census-geography API -- the first genuinely queryable (attribute- and spatially-filterable) StatCan geography service in this codebase, distinct from every static bulk boundary-file download already covered. Confirmed live: top-level folders are years 2019-2025 (nothing older is served here); a census year (2021 confirmed) publishes a full suite of ~10 services (Cartographic/Digital boundary files, Agricultural/Population ecumene boundary files, Road Network File, each in English and French), each service one MapServer with one layer per geography level (15 layers confirmed for 2021's Cartographic boundary files: PR/CD/CSD/CMA/ER/FED/CCS/PC/DPL/ADA/CT/DA/DB/FSA/CAR); an intercensal year publishes a much smaller set (CSD-level updates and the Road Network File only, confirmed for 2019-2020, 2022-2025) -- this genuinely varies year to year and is not hardcoded. New module `modules/statcan/geo/` (3 tools: list_services, get_layer_detail, query_layer) and a new shared adaptor `shared/arcgis.py` (this is the first ArcGIS REST-platform source in this codebase; `shared/wfs.py` covers OGC WFS 2.0 instead, a different protocol used by NRCan's NBAC). Two real quirks handled, both confirmed live: (1) every error -- an unknown year/service/layer, a malformed `where` clause -- comes back as HTTP 200 with a JSON `{"error": {"code", "message"}}` body, not a non-2xx status, so `shared/arcgis.py` inspects the decoded body on every call rather than relying on `raise_for_status()`; (2) this specific host is intermittently unreliable at the node level -- roughly one in three to five otherwise-identical requests to the exact same URL returns a genuine transient HTTP 500 ("Application Error" or "This web adaptor is not configured with an ArcGIS Enterprise component"), reproduced repeatedly by simply retrying the same URL seconds later, consistent with a load-balanced backend where some nodes are unhealthy -- `shared/http.py`'s existing 3-attempt exponential-backoff retry (already used by every module) is sufficient mitigation and no second retry layer was added. `query_layer` reprojects geometry from the service's native EPSG:3347 (Statistics Canada Lambert) to WGS84 lat/lon (EPSG:4326) by default when geometry is requested (off by default -- polygon boundaries can be large), and surfaces each layer's own `maxRecordCount` cap (6000 confirmed for 2021's Cartographic boundary layers) via an `exceeded_transfer_limit` flag so a caller knows to page with `result_offset` rather than assuming a query returned everything. Investigated an eighth and final time per an explicit "last round" request, closing the exhaustive multi-pass StatCan audit. Checked and confirmed correctly out of scope: GeoSearch's National Address Register API is dead (StatCan's own developers page states the GC API Store it depended on "closed permanently at 12:00 EDT on September 29th, 2023," leaving NAR as a static per-province PUMF CSV, catalogue 46-26-0002, not a live address-to-DGUID lookup); StatCan's website chatbot is an in-house 2026 Census FAQ tool with no data API; legacy CANSIM table/vector IDs are already fully covered by WDS's own `cansimId` field on cube metadata (the static concordance CSV at `statcan.gc.ca/en/developers/concordance` is a one-time June 2018 snapshot of the same mapping, not a new capability); a final developers-hub and Departmental Plan sweep surfaced nothing not already shipped. One genuine new surface was found and shipped: StatCan's own SDG Data Hub (`www144.statcan.gc.ca/sdg-odd/`) links to two separate "Open SDG" platform sites -- the Canadian Indicator Framework (86 indicators) and the Global Indicator Framework (251 indicators, Canada's reporting against the UN's own indicator set) -- each a static site hosted on GitHub Pages, not a StatCan-run API host. Confirmed live that both sites embed their real data API base URL directly in their own page JavaScript (`opensdg.remoteDataBaseUrl`) rather than publishing it as documentation, resolving to a shared third GitHub Pages host (`sdg-data-canada-odd-donnees.github.io`) under two different repo-path prefixes; a discovery index at `{base}/{lang}/meta/all.json` lists every indicator's metadata, `{base}/{lang}/meta/{code}.json` and `{base}/{lang}/data/{code}.json` resolve one indicator's metadata and observations respectively, all free and unauthenticated. New module `modules/statcan/sdg/` (3 tools: search_indicators, get_indicator_metadata, get_indicator_data). One real quirk handled: the two frameworks use genuinely different metadata field names for the same concepts, confirmed live -- the Canadian framework's `sdg_goal`/`national_indicator_description`/`published` versus the Global framework's `SDG_GOAL`/`STAT_CONC_DEF` with no `published` field at all -- normalized to the fields both frameworks share (`goal_number`, `target_number`, `indicator_name`, `reporting_status`) plus a description that tries the Canadian field name first, then the Global one. Errors here are standard HTTP 404s (a plain static-file host), unlike every other quirky embedded-error StatCan API in this module. With this addition, StatCan's public programmatic surface is considered exhaustively covered by this project. Investigated a ninth time, specifically to check whether other StatCan thematic "hub" microsites follow the same pattern the SDG Data Hub turned out to (a presentation layer over a genuinely separate, freely-accessible backing data API): checked the Quality of Life Hub/Framework, the Gender, Diversity and Inclusion Statistics Hub, the CPI Inflation/Personal Inflation Calculator, and several housing dashboards (Census Program Data Viewer, Rural Canada Housing Profiles, New Housing Price Index dashboard). All of these embed either a Power BI report (`dv-vd.cloud.statcan.ca`, requiring a session-scoped Azure AD token issued server-side, not something an external client can legitimately call) or an R Shiny application (`dv-vd.shinyapps.io`, a stateful websocket-driven reactive session, confirmed live via its shiny-server-client/sockjs assets) -- StatCan's standard internal presentation layer over WDS-sourced tables (the Inflation Calculator's math almost certainly runs against CPI table 18-10-0004-01, already covered), not a new data-access route. Unlike the SDG hub's Open SDG GitHub Pages platform, none of these expose a discoverable public REST/JSON surface -- confirmed no new capability. |
| NRCan National Burned Area Composite (NBAC) | Shipped | Investigated and shipped 2026-09-20 in response to a direct request (BC wildfire polygons/dates/adjusted burned area, 2017-2024, for a school-district-level analysis). [Details](docs/findings/specialized-federal-sources.md#nrcan-national-burned-area-composite-nbac) |
| ISED Office of the Superintendent of Bankruptcy (individual bankruptcy records) | Blocked | Investigated 2026-09-20 per a direct request: the OSB's Bankruptcy and Insolvency Records Search (ised-isde.canada.ca) requires an account and charges a minimum $8 per search, confirmed via its own documentation -- paywalled and … [Details](docs/findings/specialized-federal-sources.md#ised-office-of-the-superintendent-of-bankruptcy-individual-bankruptcy-records) |
| Health Canada (public health CKAN data) | Shipped (via `ckan_*`) | Investigated 2026-09-21 to correct an over-broad reading of this roadmap's federal-scope note (see the Federal section intro above). [Details](docs/findings/specialized-federal-sources.md#health-canada-public-health-ckan-data) |
| ESDC (Employment and Social Development Canada) | Shipped (via `ckan_*`) | Investigated 2026-09-21 for the same reason as the Health Canada row above. Confirmed live `esdc-edsc` publishes 266 datasets on the federal CKAN catalogue, already reachable via `ckan_search_datasets(fq="organization:esdc-edsc")`. [Details](docs/findings/specialized-federal-sources.md#esdc-employment-and-social-development-canada) |
| CMHC | Shipped | Housing Market Information Portal (HMIP, www03.cmhc-schl.gc.ca/hmip-pimh), a legacy ASP.NET MVC/Kendo UI portal with no JSON API: `cmhc_*`, 4 tools (list categories, get table options, list provinces, get table data) covering Rental Market … [Details](docs/findings/specialized-federal-sources.md#cmhc) |

Audited 2026-09-19 against the reference `mountainMath/cmhc` R package's own source (not just its docs) and found/fixed a **critical CSV-parsing bug**: the earlier parser assumed every table's CSV export doubles each value column with a trailing quality-flag column (`header[1::2]`) — true for statistically-sampled Rental Market Survey tables, but a census-style administrative table (Starts and Completions Survey, which counts every issued permit rather than sampling) has no flag columns at all, and the blind pairing silently misaligned and corrupted every value from the second column onward (confirmed live against a real Starts-by-CMA table: Barrie's "Row" starts read as 0 with flag "60" instead of the correct 60 with no flag). Replaced with a per-column header walk that only pairs a value column with a flag when the following header cell is genuinely empty. Also fixed two related parsing gaps found the same way: values ≥1,000 use a thousands-comma inside a quoted CSV field (`"1,013"`) which `float()` rejects unless stripped, and a bare `"-"` is CMHC's own notation for a real, counted zero, not a suppressed value — both confirmed against the reference package's own `parse_numeric()` helper and re-verified live. Also added `"n/a"` to the suppressed-value tokens (`"**"`/`"++"`) on the same cross-check. Added a genuine capability gap the audit surfaced: `cmhc_get_table_data` now accepts an optional `filters` dict (e.g. `{"dwelling_type_desc_en": "Row"}`, `{"season": "April"}`), validated against and passed through to HMIP's own `AppliedFilters[i].Key`/`.Value` POST params — confirmed live these genuinely change returned values (national rental vacancy rate for "Row" dwellings differs from "Apartment" for the same period), a capability the reference R package exposes but this module previously did not. |
| CRTC | Shipped (via `ckan_*`) | Investigated 2026-09-19: CRTC's Communications Monitoring Report data (telecom/broadcasting sector revenue and subscriber counts, wholesale/retail pricing, mobile and broadband availability) is not a separate platform -- it is already … [Details](docs/findings/specialized-federal-sources.md#crtc) |
| CER (Canada Energy Regulator) | Shipped | Shipped 2026-09-23: `modules/cer/` (2 tools). The CER has no query API; it publishes bilingual CSVs under cer-rec.gc.ca/open/ and /ouvert/, catalogued as open.canada.ca's `cer-rec` organization (84 datasets). [Details](docs/findings/specialized-federal-sources.md#cer-canada-energy-regulator) |
| CRA (Canada Revenue Agency) | Shipped (via `ckan_*` + new `ckan_datastore_search`) | Investigated 2026-09-20, then investigated again in more depth after an initial pass under-scoped this row: CRA's tax-filer statistics (333 datasets under the `cra-arc` organization -- T1/T2 filing compliance, GST/HST statistics, Canada … [Details](docs/findings/specialized-federal-sources.md#cra-canada-revenue-agency) |
| Proactive Disclosure (government-wide) | Shipped (via `ckan_*` + `ckan_datastore_search`) | Requested directly 2026-09-20. Government of Canada proactive-disclosure publications (contracts over $10,000, travel and hospitality expenses, grants and contributions, position reclassifications, departmental audit committees, briefing … [Details](docs/findings/specialized-federal-sources.md#proactive-disclosure-government-wide) |
| ISED (Innovation, Science and Economic Development Canada) | Shipped | Three modules, split like CMHC's dual-platform pattern (`modules/ised/{corporations,spectrum,cipo}/`): (1) Corporations Canada's federal corporation lookup API (`ised_corporations_*`, 1 tool) -- a single-record lookup by numeric … [Details](docs/findings/specialized-federal-sources.md#ised-innovation-science-and-economic-development-canada) |
| Government of Canada `open-data` GitHub org / `ckanext-canada` / `ckanext-recombinant` | Investigated, no capability change | Investigated 2026-09-20 per a direct request to check the federal open-data GitHub presence for anything not already covered. [Details](docs/findings/specialized-federal-sources.md#government-of-canada-open-data-github-org--ckanext-canada--ckanext-recombinant) |
| OSFI (Office of the Superintendent of Financial Institutions) | Shipped (via `ckan_*` + new `ckan_datastore_search`) | Investigated 2026-09-20, then investigated again in more depth alongside CRA: OSFI's regulated-entity data (36 datasets under the `osfi-bsif` organization -- "Banks", "Trust companies", "Loan companies", "Foreign bank branches", "Life … [Details](docs/findings/specialized-federal-sources.md#osfi-office-of-the-superintendent-of-financial-institutions) |
| Transport Canada + CTA (Canadian Transportation Agency) | Shipped (recalls) | Shipped 2026-09-23: `modules/tc_recalls/` (2 tools) on Transport Canada's Motor Vehicle Safety Recalls Database API (data.tc.gc.ca/v1.3/api/{eng,fra}/vehicle-recall-database): search by make, model and model-year range, and a bilingual … [Details](docs/findings/specialized-federal-sources.md#transport-canada--cta-canadian-transportation-agency) |
| Elections Canada | Shipped (via `ckan_*` + new `elections_financial_returns` module) | Investigated and shipped 2026-09-21. Elections Canada publishes 54 datasets under the `elections` organization (`organization_autocomplete` confirmed the real org slug is `elections`, not `elections-canada`) on the existing federal CKAN … [Details](docs/findings/specialized-federal-sources.md#elections-canada) |
| CanadaBuys (PSPC procurement) | Shipped | `modules/canadabuys/` (3 tools): `canadabuys_search_tenders` (open or today's new tender notices, filter by keyword, category, region, buyer), `canadabuys_search_awards` (award notices per fiscal year 2022-2023 onward, filter by supplier … [Details](docs/findings/specialized-federal-sources.md#canadabuys-pspc-procurement) |
| House of Commons (OpenParliament.ca) | Shipped | Shipped 2026-09-24: `modules/openparliament/` (7 `parliament_` tools) over api.openparliament.ca, an unofficial JSON API by OpenParliament.ca/Open North that re-publishes LEGISinfo, House votes, Hansard and committee evidence (no official … [Details](docs/findings/specialized-federal-sources.md#house-of-commons-openparliamentca) |
| Senate of Canada votes | Shipped | Shipped 2026-09-24: `modules/senate/` (2 tools) parsing sencanada.ca's vote pages, since the Senate publishes no votes API: `senate_list_votes` (a session's votes from 42-1 on, with totals, related bill and result; EN and FR pages) and … [Details](docs/findings/specialized-federal-sources.md#senate-of-canada-votes) |
| GC InfoBase (Treasury Board, government spending and results) | Shipped | Shipped 2026-09-23: `modules/gc_infobase/` (2 tools) over the official "GC InfoBase - Open Datasets" package on open.canada.ca (52 bilingual CSVs: Estimates, Public Accounts by vote/standard object/transfer payment, planned and actual … [Details](docs/findings/specialized-federal-sources.md#gc-infobase-treasury-board-government-spending-and-results) |
| Justice Laws (federal statutes and regulations) | Out of scope | Decided 2026-09-23: legislation text is out of scope for this data server. A `justice_laws` module was built on the Legis.xml XML service and then removed; see git history (commit 4bc99e1) if this is revisited. |
| Canada Gazette (regulatory notices) | Shipped | Shipped 2026-09-23: `modules/gazette/` (3 tools). Issues come from the official RSS feeds (`/rss/p1-eng.xml`, 435 issues; `/rss/p2-eng.xml`, 232; no Part III feed); `gazette_get_issue` parses an issue's index page into notices with … [Details](docs/findings/specialized-federal-sources.md#canada-gazette-regulatory-notices) |
| CIHI (Canadian Institute for Health Information) | Shipped | Shipped 2026-09-23: `modules/cihi/` (3 tools). CIHI retired Your Health System and the Health Indicators Interactive Tool (the old URLs now redirect to a "Modernizing how we deliver data" page) in favour of the Indicator Library, whose … [Details](docs/findings/specialized-federal-sources.md#cihi-canadian-institute-for-health-information) |
| NRCan energy use (Office of Energy Efficiency, National Energy Use Database) | Shipped | Shipped 2026-09-23: `modules/nrcan_energy_use/` (3 tools) over oee.nrcan.gc.ca, which has no JSON API: product list (11 survey editions: SHEU 2019/2015 and by CMA, multi-unit residential 2018, SCIEU 2019/2014/2009, arenas 2014, ICE … [Details](docs/findings/specialized-federal-sources.md#nrcan-energy-use-office-of-energy-efficiency-national-energy-use-database) |
| NRCan geospatial (geo.ca geolocation, CanVec, geospatial catalogue) | Shipped | Shipped 2026-09-23: `modules/nrcan_geo/` (2 tools). `nrcan_geo_locate` uses the Geolocator (geolocator.api.geo.ca; the old geogratis geolocation URL now redirects and answers HTTP 500) for places, addresses, postal codes and FSAs. [Details](docs/findings/specialized-federal-sources.md#nrcan-geospatial-geoca-geolocation-canvec-geospatial-catalogue) |
| Earthquakes Canada (NRCan) | Shipped | Shipped 2026-09-24: `modules/earthquakes/` (1 tool, `earthquakes_search`) on the FDSN event web service (earthquakescanada.nrcan.gc.ca/fdsnws/event/1/query, `format=text`): date range (default last 30 days, up to ~5 years), magnitude … [Details](docs/findings/specialized-federal-sources.md#earthquakes-canada-nrcan) |
| DFO (Fisheries and Oceans Canada) tides and water levels | Shipped | Shipped 2026-09-23: `modules/dfo_iwls/` (3 tools) on the IWLS API (api-iwls.dfo-mpo.gc.ca): station search over ~1,575 stations, station detail with datum offsets, and `wlp-hilo`/`wlp`/`wlo` series. [Details](docs/findings/specialized-federal-sources.md#dfo-fisheries-and-oceans-canada-tides-and-water-levels) |
| Alberta Economic Dashboard | Shipped | Shipped 2026-09-23, reworked the same day around the dashboard's published API: `modules/ab_economic/` (5 tools). [Details](docs/findings/specialized-federal-sources.md#alberta-economic-dashboard) |

| StatCan public use microdata files (PUMFs) | Shipped | Shipped 2026-09-24: `statcan_pumf_` (5 tools): search, ZIP listings, codebooks read by HTTP range request (LFS CSV, Stata, SPSS, SAS formats; EN/FR) and `statcan_pumf_tabulate` (weighted totals, shares and means with DuckDB, disk cache). [Details](docs/findings/specialized-federal-sources.md#statcan-public-use-microdata-files-pumfs) |
| Census data tables 2006-2016 (Beyond 20/20) | Shipped | Checked 2026-09-25: StatCan has retired the 2011 Census tabulations (index and downloads redirect to its page-not-found notice; 2011 NHS, 2006 and 2016 still work), so the tools point to the Borealis copies (27 datasets … [Details](docs/findings/specialized-federal-sources.md#census-data-tables-2006-2016-beyond-2020) |
| Cross-source planning and reproducible code | Shipped | Shipped 2026-09-24: `plan_query` (always visible; topic and place routing across agencies) and `reproduce_code` (R, Python, Stata and Julia scripts that fetch and clean the same data; cansim and canivt in R). [Details](docs/findings/specialized-federal-sources.md#cross-source-planning-and-reproducible-code) |
| PMPRB (Patented Medicine Prices Review Board) | Not started | From the Notion canonical page: patented medicine prices, pharmaceutical expenditure and international price comparisons. Check machine-readable access first. The Health Canada Drug Product Database stays out of scope (decided 2026-09-24). |
| Competition Bureau Canada | Shipped | Shipped 2026-09-25: `modules/competition_bureau/` (`competition_bureau_search_mergers`) over both merger-review reports (2,554 reviews). Checked 2026-09-25: the merger-review reports are full HTML tables (about 830 reviews since Nov 2023, weekly; about 1,725 from 2015-2023) with parties, dates, NAICS and outcome; the Tribunal's decisions site refuses automated requests, and enforcement and market studies are PDFs. [Details](docs/findings/competition-bureau.md) |
| Canadian Grain Commission | Not started | From Notion: grain deliveries, exports, stocks, prices, quality, elevator data. |
| Agriculture and Agri-Food Canada (AAFC) | Not started | From Notion: commodity prices, livestock, crops, agricultural trade, geospatial data. Check what `ckan_*` (portal="federal") already reaches before a dedicated adaptor. |
| Financial Consumer Agency of Canada (FCAC) | Not started | From Notion: consumer financial products, banking fees, mortgages, financial wellbeing research. |
| Canadian Dairy Commission and provincial marketing boards | Not started | From Notion: regulated agricultural prices, quotas, production. A family of small adaptors rather than one dataset. |
| CAPP Statistics Handbook (Canadian Association of Petroleum Producers) | Investigated, deferred | Checked 2026-09-25: 76 Excel tables (reserves, production by field, value of producer sales from 1947, expenditures, demand), updated each December; industry copyright, use allowed with attribution. See `docs/findings/capp-statistics-handbook.md`. |
| CIPO patents via IP Horizons | Shipped | Shipped 2026-09-25: `modules/ised/ip_horizons/` (4 tools). Record queries: `ised_ip_horizons_get_patent` (one patent with owners, inventors, applicants, agents, optionally IPC classes) and `ised_ip_horizons_search_patents` (party name and … [Details](docs/findings/specialized-federal-sources.md#cipo-patents-via-ip-horizons) |
| ISED Business Number (BN) validation | Not started | From Notion: check whether the BN Web Validation Look-Up Tool has a public or programmatic endpoint, its authentication, permitted uses and fields. Corporations Canada search already ships as `ised_corporations_`. |
| OpenParliament committees | Not started | From Notion's legislation section: committees and legislative history beyond the shipped bills, votes and Hansard tools. Note the scope question below. |
| Clean Technology Data Strategy (NRCan, ISED, StatCan; Clean Growth Hub) | Partly covered | Checked 2026-09-24: its statistics are StatCan's Environmental and Clean Technology Products Economic Account (tables 36-10-0366, -0370, -0371, -0372, -0411, -0627 and more, via `wds_`) plus open.canada.ca datasets on clean-technology use … [Details](docs/findings/specialized-federal-sources.md#clean-technology-data-strategy-nrcan-ised-statcan-clean-growth-hub) |

**Scope (decided 2026-09-24):** parliamentary and regulatory data stay in
MapleStats (`gazette_`, `parliament_`, `senate_`); full statute text (Justice
Laws) stays out of scope. The Notion naming decision has been updated to match.

## Launch and distribution

From the Notion canonical page; none of these are done yet.

| Item | Status | Notes |
|---|---|---|
| Hosted MCP endpoint | Not started | Launch gate: a stable hosted server (Azure Container Apps recipe discussed 2026-09-24: one replica, Azure Files volume for the PUMF cache, bearer token). |
| Public website | Not started | Product, sources, connection instructions, examples, status. |
| Launch blog post "One MCP to Rule Them All" | Not started | Narrative drafted on the Notion page. |
| Cross-source demos | Not started | One substantive Canadian question answered across StatCan, BoC, CMHC and provincial data; `plan_query` is the entry point. |
| MCP registries | Not started | Submit once the hosted endpoint and docs exist. |
| PyPI package | Not started | Installable Python package linking to the hosted service. |
| Per-language clients | Not started | Lightweight R, Python and Julia clients over the hosted core; `reproduce_code` already generates per-language scripts. |
| Ecosystem outreach | Not started | cansim maintainers, MountainMath (CMHC, canivt), OSI Data Analyst Network, Edmonton Data Society, Vancouver group, NRCan (Torben), SFU Economics. |
