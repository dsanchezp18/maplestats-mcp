# Roadmap

Source coverage plan for MapleData MCP. This is the authoritative list of
what the package will cover — scoped by Daniel on 2026-09-14, superseding
any narrower or broader source list implied elsewhere.

Current implementation snapshot (2026-09-19): shipped modules cover
Statistics Canada, the Bank of Canada, federal CKAN, IRCC Express Entry,
Environment and Climate Change Canada / MSC GeoMet, CMHC, Alberta,
British Columbia, Ontario, Quebec, Nova Scotia, New Brunswick,
Manitoba, Saskatchewan, Prince Edward Island, Newfoundland and Labrador,
the Northwest Territories, Yukon, Montreal, Toronto, Regina, Hamilton,
London, Kitchener, Windsor, Saskatoon, Victoria, Surrey, Calgary,
Edmonton, and Winnipeg (Laval and Gatineau are covered through the
existing Quebec CKAN module, not a dedicated one). The rows below are
the source-of-truth for remaining work; each row has its own status.

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
| IRCC Immigration | Shipped | Express Entry rounds of invitations (tools prefixed `ircc_`): draw history, CRS cutoffs, invitations issued, and candidate-pool CRS score distribution, from a static JSON feed at `canada.ca/content/dam/ircc/documents/json/ee_rounds_123_{en,fr}.json` -- confirmed live 2026-09-18 to be a different platform from CKAN, not an open.canada.ca dataset. Real quirks found and handled: the French feed's bytes are Windows-1252 despite a bare `application/json` content type with no charset (decoding as UTF-8 silently mangles accents instead of raising); numeric fields use a comma thousands separator in English vs. a literal space in French; and two rounds from 2018-05-30 are published as "91a"/"91b" instead of sequential numbers, so `draw_number` is a string, not an int. IRCC's other administrative series (permanent residents, study/work permits, asylum, citizenship) are ordinary CKAN datasets published by the `ircc` organization on open.canada.ca and are already reachable via the existing `ckan_search_datasets(fq="organization:ircc")` on the federal module -- no dedicated module needed for those. |
| Weather / Climate (Environment Canada MSC GeoMet) | Shipped | api.weather.gc.ca, MSC GeoMet-OGC-API (OGC API - Features): `eccc_*`, 4 generic tools (search/list/get collection, query items) covering all ~100 published collections — weather alerts, current surface observations (SWOB), city forecasts, AQHI, climate stations/daily/hourly/monthly/normals, hydrometric water level/flow, marine, and long-term climate extremes — rather than one bespoke tool per dataset. Verified live 2026-09-19: unknown property filters are silently ignored upstream (return zero rows, not an error) rather than validated, so the client checks filter/sortby/field names against each collection's own `/queryables` first; `datetime` filtering works on some collections (hydrometric-realtime) and returns HTTP 500 on others (weather-alerts) with no way to predict which from metadata; the server enforces no upper bound on `limit` even though some collections exceed 400K rows (hydrometric-realtime); `climate-stations`' LATITUDE/LONGITUDE properties are integers scaled by 1e7, not decimal degrees. |

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
| 1 | Socrata | Nova Scotia, New Brunswick | Shipped 2026-09-18: `socrata_ns_*`/`socrata_nb_*`, verified live against `api.us.socrata.com`'s catalog API, the per-domain Views API, and the SODA row-query API for both `data.novascotia.ca` and `gnb.socrata.com`. The same adaptor unlocked Calgary, Edmonton, and Winnipeg (all confirmed Socrata) once a municipal phase was scoped in — see the Municipal section below; shipped 2026-09-19. |
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
| Newfoundland and Labrador | Shipped | `opendata.gov.nl.ca`, custom HTML catalogue: local search/pagination over tabular and spatial listings, tag discovery, dataset metadata, and official CSV/XLS/TXT/KMZ/shapefile download links. Verified live against the tabular/spatial listings, date sorting, Explore tag cloud, dataset detail metadata/file table, and typed not-found behavior. The official GeoAtlas spatial surface remains separate. Portal content is English-only; the module preserves the Open Government Licence—Newfoundland and Labrador attribution and every source/detail/download URL. |
| Prince Edward Island | Shipped | data.princeedwardisland.ca, ArcGIS Hub: `arcgis_pe_*`, 3 tools, same shape as Manitoba's. At least one item's underlying service reports an empty `layers` list with its one queryable table at a non-zero id (2) — the default-layer-index resolution this adaptor added because of that applies here too. Verified against live responses. |

## Territorial (all 3)

| Territory | Status | Portal (reference) |
|---|---|---|
| Northwest Territories | Shipped | opendata.gov.nt.ca, CKAN Action API: `ckan_nt_*`, 8 tools. English-only. Small catalogue (341 datasets). |
| Yukon | Shipped | open.yukon.ca, CKAN Action API: `ckan_yt_*`, 8 tools. English-only (site UI is bilingual-chrome only; dataset content is not). 3,841 datasets. |
| Nunavut | Blocked | Investigated 2026-09-19: no dedicated open-data portal exists (`opendata.gov.nu.ca`/`data.gov.nu.ca` don't resolve). The Government of Nunavut's own site (`gov.nu.ca`), including its Nunavut Bureau of Statistics/economic-data pages, sits behind a bot-detection interstitial that did not clear even after 15s in a real rendered browser, and returns HTTP 403 to a plain HTTP client — genuinely blocking automated access, not just a slow load. Re-investigate only if a dedicated portal is later launched or the bot-check is confirmed to allow a properly-identified client through. |

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
| Calgary | Shipped | data.calgary.ca, Socrata (SODA): `socrata_calgary_`, 5 tools, same shape as Nova Scotia/New Brunswick's. English-only. 413 datasets confirmed live. |
| Edmonton | Shipped | data.edmonton.ca, Socrata (SODA): `socrata_edmonton_`, 5 tools, same shape. English-only. 1,421 datasets confirmed live — the largest Socrata catalogue this server covers. |
| Ottawa | Not CKAN | open.ottawa.ca — migrated off CKAN to ArcGIS Hub (per the city's own 2023/24 announcement). |
| Winnipeg | Shipped | data.winnipeg.ca, Socrata (SODA): `socrata_winnipeg_`, 5 tools, same shape. English-only. 235 datasets confirmed live. |
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
module, no dedicated module needed). Shipped 2026-09-19: Calgary,
Edmonton, and Winnipeg, reusing the existing `shared/socrata.py`
adaptor built for Nova Scotia/New Brunswick — see their rows above.
Vancouver, Ottawa, and the smaller municipalities/regions below remain
their own rows, not yet shipped.

Open item: every city from the original example list (Hamilton,
London, Kitchener, Windsor, Regina, Saskatoon, Victoria, Surrey,
Laval, Gatineau, Calgary, Edmonton, Winnipeg) is now shipped or
covered. Inventory further major cities not yet checked (e.g. Quebec
City, Longueuil, Burnaby, Richmond, Vaughan, Kelowna, Sherbrooke,
Trois-Rivières, St. John's, Barrie, Guelph, Kingston) and add each
once a real portal is confirmed.

## Census and specialized federal agencies

Sources beyond the core five federal modules and beyond generic
CKAN/portal coverage — each needs its own adaptor design.

| Agency / source | Status | Notes |
|---|---|---|
| Census (StatCan Census Program / Census Profile) | Not started | Distinct from generic StatCan table access — needs its own discovery layer (geography, profile variables, PUMFs). |
| CMHC | Shipped | Housing Market Information Portal (HMIP, www03.cmhc-schl.gc.ca/hmip-pimh), a legacy ASP.NET MVC/Kendo UI portal with no JSON API: `cmhc_*`, 4 tools (list categories, get table options, list provinces, get table data) covering Rental Market Survey vacancy rates/rents, new housing starts/completions, secondary rental market, seniors' rental housing, and population/core-housing-need indicators, for Canada and by province, as a time series or current cross-tab. No hardcoded table catalogue — categories and their valid breakdowns are discovered live from HMIP's own navigation, and each table's `TableId` is resolved live from an embedded JSON blob rather than a hand-built lookup (an improvement over the reference `mountainMath/cmhc` R package, read as the "existing community access pattern" this row asked to investigate, which hardcodes its entire table registry by hand). Verified live 2026-09-19: an unresolvable category/geography/TableId returns HTTP 500 with an ASP.NET error page, not a clean 404; the CSV export is cp1252 (Windows-1252) encoded, not UTF-8 or strict latin-1 (confirmed against a real em-dash byte, correcting the reference package's own "latin1" comment); a cell can hold a suppressed ("**") or not-applicable ("++") marker instead of a number; `lang` genuinely changes category names (not just prose) since HMIP's `/en/`/`/fr/` categories are different strings per language; only Canada/province-level geography is covered — no live CMA/city-level discovery endpoint was found despite several attempts. The separate `www.cmhc-schl.gc.ca` "Data Tables" Sitecore document catalogue is now also shipped (added 2026-09-19) as `cmhc_dt_*`, 3 more tools (list tables, get table detail, resolve a download link) covering Rental Market Survey and Household Characteristics official per-edition Excel publications (72 tables confirmed live across the two categories; Canadian Housing Survey tables are not yet mapped). Discovery reads geography/edition options and a table's default download link directly from static HTML (Sitecore item GUIDs, a different id scheme from HMIP's small integers); resolving any historical edition's download link uses the site's own resolver API (`api/Sitecore/PubsAndReports/GetFileDetails`), found via live network-request inspection of the rendered page rather than documentation — confirmed live this was necessary: guessing a filename from the current pattern works for recent editions but fails for at least one older one whose filename omits a suffix later editions have.

Audited 2026-09-19 against the reference `mountainMath/cmhc` R package's own source (not just its docs) and found/fixed a **critical CSV-parsing bug**: the earlier parser assumed every table's CSV export doubles each value column with a trailing quality-flag column (`header[1::2]`) — true for statistically-sampled Rental Market Survey tables, but a census-style administrative table (Starts and Completions Survey, which counts every issued permit rather than sampling) has no flag columns at all, and the blind pairing silently misaligned and corrupted every value from the second column onward (confirmed live against a real Starts-by-CMA table: Barrie's "Row" starts read as 0 with flag "60" instead of the correct 60 with no flag). Replaced with a per-column header walk that only pairs a value column with a flag when the following header cell is genuinely empty. Also fixed two related parsing gaps found the same way: values ≥1,000 use a thousands-comma inside a quoted CSV field (`"1,013"`) which `float()` rejects unless stripped, and a bare `"-"` is CMHC's own notation for a real, counted zero, not a suppressed value — both confirmed against the reference package's own `parse_numeric()` helper and re-verified live. Also added `"n/a"` to the suppressed-value tokens (`"**"`/`"++"`) on the same cross-check. Added a genuine capability gap the audit surfaced: `cmhc_get_table_data` now accepts an optional `filters` dict (e.g. `{"dwelling_type_desc_en": "Row"}`, `{"season": "April"}`), validated against and passed through to HMIP's own `AppliedFilters[i].Key`/`.Value` POST params — confirmed live these genuinely change returned values (national rental vacancy rate for "Row" dwellings differs from "Apartment" for the same period), a capability the reference R package exposes but this module previously did not. |
| CRTC | Not started | Telecommunications/broadcasting market data: plan prices, subscribers, revenues, broadband, competition indicators. |
| CER (Canada Energy Regulator) | Not started | Oil, gas, NGL/LNG, pipeline, energy trade/export/price/infrastructure data. |
| CRA (Canada Revenue Agency) | Not started | T1/T2 tax statistics, tax-filer aggregates, benefits, charities, other administrative tax datasets. |
| ISED (Innovation, Science and Economic Development Canada) | Not started | Spectrum/radio licensing, broadband/connectivity, corporations, insolvencies, business datasets. |
| OSFI (Office of the Superintendent of Financial Institutions) | Not started | Banks, insurers, federally regulated pension plans, regulatory/balance-sheet statistics. |
| Transport Canada + CTA (Canadian Transportation Agency) | Not started | Aviation, rail, transport regulatory data, complaints, accessibility, infrastructure. |
| Elections Canada | Not started | Election results, candidates, political financing/contributions, polling divisions, electoral geography. |
| CanadaBuys (PSPC procurement) | Not started | Tenders, procurement notices, contract awards, procurement metadata. |
