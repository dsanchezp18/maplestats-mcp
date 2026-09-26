# Provincial sources

Findings moved from [`ROADMAP.md`](../../ROADMAP.md) on 2026-09-25. Each section
records what was checked, against which live responses, and what the
module does about it. Dates are when a finding was confirmed; the
status in `ROADMAP.md` is the current one.

## Sequence 1: Socrata

Adaptor for Nova Scotia, New Brunswick.

Shipped 2026-09-18: `socrata_*` (`portal="ns"`)/`socrata_*` (`portal="nb"`),
verified live against `api.us.socrata.com`'s catalog API, the per-domain
Views API, and the SODA row-query API for both `data.novascotia.ca` and
`gnb.socrata.com`. The same adaptor unlocked Calgary, Edmonton, and Winnipeg
(all confirmed Socrata) once a municipal phase was scoped in — see the
Municipal section below; shipped 2026-09-19.

## Sequence 2: ArcGIS Hub / ArcGIS REST

Adaptor for Manitoba, Saskatchewan, Prince Edward Island.

Shipped 2026-09-18: `arcgis_hub_*` (`portal="mb"`)/`arcgis_hub_*`
(`portal="sk"`)/`arcgis_hub_*` (`portal="pe"`), verified live against all
three portals' Hub Search API v3
(`/api/search/v1/collections/dataset/items`), the classic ArcGIS REST
FeatureServer/MapServer query API, and the `/api/download/v1` export API.
Two real quirks only found by calling every function against all three
portals live (not caught by mocked tests alone): a catalogue item's
`properties.url` is sometimes the bare service root and sometimes already a
specific layer endpoint, and the default layer/table id to query is not
always 0 — Saskatchewan services can live on a government domain
(`gis.saskatchewan.ca`) rather than `*.arcgis.com`, and a PEI item's service
reported its one queryable table at id 2 with an empty `layers` list.

This adaptor also creates a path for many municipal and specialized
geographic portals (see the Municipal section below).

## British Columbia

**Status:** Shipped.

catalogue.data.gov.bc.ca, CKAN Action API: `ckan_*` (`portal="bc"`), 10
tools (search, dataset/org/resource/license detail, tags, groups, and --
added 2026-09-20 -- `ckan_datastore_search` for row-level queries against a
DataStore-active resource, mirroring the same addition to `ckan_federal`).
Confirmed live this unlocks BC's Foundation Skills Assessment district-level
results (DISTRICT_NAME, GRADE, FSA_SKILL_CODE, SCHOOL_YEAR, AVG_SCORE),
filterable directly rather than only downloadable as one bulk file per
school-year range.

English-only. BC Geographic Warehouse (WFS) is now also shipped, per a
direct 2026-09-22 request (prompted by a competitive-coverage check against
a third-party MCP server, `mcp-canada` from reyemtech): new module
`modules/bcgw/` (`bcgw_*`, 3 tools -- `get_active_wildfires`,
`get_mining_tenure`, and a generic `query_layer` for any BCGW layer by
type_name) confirmed live against `openmaps.gov.bc.ca/geo/pub/wfs`, a
GeoServer WFS 2.0 deployment (the `shared/wfs.py` adaptor built for NRCan's
NBAC applies unchanged, confirmed live -- no new adaptor needed).

A layer's type_name is discoverable from an existing `ckan_*`
(`portal="bc"`) package: a WFS/WMS-queryable dataset carries a resource
whose URL embeds the type_name right after `openmaps.gov.bc.ca/geo/pub/`.
Two real quirks found and fixed during live verification, not just assumed
from the NBAC precedent:

1. this GeoServer instance answers HTTP 400 ("Cannot do natural order
   without a primary key") whenever a request would genuinely page (more
   rows match than the requested count) with no explicit `sortBy` --
   reproduced live against the mining tenure layer (1,312 real Teck Highland
   Valley Copper claims) after the wildfire layer's own smaller result set
   masked the same bug -- fixed by defaulting `sortBy` to `OBJECTID` (BCGW's
   standard ArcSDE row identifier, confirmed present on every layer checked)
   across all three tools unless a caller overrides it;
2. `propertyName` narrows fields but not exactly to the requested list --
   this instance always adds back each layer's own identifying field(s)
   (e.g.

`FIRE_NUMBER`/`FIRE_YEAR`) plus the `sortBy` field on top of what was asked
for, confirmed live and harmless here since every parser reads named fields
and ignores the rest. `bcgw_get_active_wildfires` confirmed live against 2
real "Out of Control" BC fires burning as of 2026-09-22.

## Quebec

**Status:** Shipped.

donneesquebec.ca (API at `/recherche/api/3/action/`), CKAN Action API:
`ckan_*` (`portal="qc"`), 9 tools (added `ckan_datastore_search` 2026-09-20,
confirmed live against a real-time weather-station-observations resource).
French-only — `lang` is a documented no-op. Investigated 2026-09-22 per a
direct request to check MSSS (Ministère de la Santé et des Services sociaux)
health data specifically, prompted by the same `mcp-canada`
competitive-coverage check as the BC/Alberta rows above: both MSSS datasets
that check named (hourly ER wait times/stretcher occupancy, and
health-installation capacity/services by region) are confirmed live to be
ordinary DataStore-active CKAN resources under donneesquebec.ca, already
reachable via the existing `ckan_datastore_search` — no new module needed,
same pattern as CRA/OSFI/Elections Canada. "Fichier horaire des données de
la situation à l'urgence" (120 installations, confirmed live updated
2026-09-22 at 10:45, fields include `Nombre_de_civieres_occupees`,
`Nombre_de_patients_sur_civiere_plus_de_24_heures`/`_48_heures`) covers ER
stretcher occupancy and long-wait counts by hospital, genuinely hourly per
its own `Mise_a_jour` timestamp. "Répartition des capacités et des services
par installation" (87,479 rows, confirmed live, `rss_etablissement` for
health-region filtering and
`mct_capacite_service_installation`/`nom_installation` for
service/installation-type filtering) covers installation capacity and
authorized services -- a close but not identical match to the
CLSC/CHSGS/CHSLD/CHPSY typology a third-party tool description had claimed;
MSSS's own field uses a different service-type code scheme, confirmed live
rather than assumed to match.

## Alberta

**Status:** Shipped.

open.alberta.ca, CKAN Action API: `ckan_*` (`portal="ab"`), 8 tools (added
`ckan_datastore_search` 2026-09-20). Dataset, organization, resource,
license, and tag responses were verified against live responses; the portal
does not expose useful groups in the tested catalogue. **Real portal-side
bug found while adding datastore_search**: every DataStore-active resource
tried (the `datastore_active` flag itself is correctly `true`) returns HTTP
500 "Internal Server Error" from `datastore_search`, confirmed across
multiple unrelated resources and with a plain `curl` outside this client too
— a genuine backend issue on Alberta's own deployment, not a bug here.

The tool is still shipped and correctly surfaces this as `UpstreamError`
(verified by the live smoke test) rather than silently failing; re-test if
Alberta's DataStore is ever fixed. A second, genuinely separate Alberta
platform is now also shipped, per the same 2026-09-22 competitive-coverage
request as the BC row above: the Alberta Energy Regulator's statistical
reports (`www.aer.ca`, not open.alberta.ca -- a different agency, different
platform).

New module `modules/aer/` (`aer_*`, 3 tools: `get_well_licences_daily`,
`get_well_licence_archive_link`, `get_production_volumes_link`) covers ST1
(well licences issued, daily report text plus monthly/yearly archive ZIP
links) and ST3 (monthly production-volume/price XLSX links for butane,
ethane, gas, NGL, oil, propane, sulphur, and oil prices). One real
correction made during this build, confirmed by reading AER's own live
"Statistical Reports" index across all 4 pages rather than trusting a
third-party claim: ST39 is "Alberta Mineable Oil Sands Plant Statistics,"
not pipeline statistics as commonly claimed elsewhere (including by the
`mcp-canada` server whose coverage prompted this row) -- the closest real
pipeline-related reports are ST96 (Pipeline Approval and Disposition Daily
List) and ST100 (Pipeline Construction Notification List), neither pursued
in this pass, so no pipeline-statistics tool was built rather than shipping
one against the wrong report.

Two more real quirks confirmed live:

1. ST1's daily `.TXT` files answer with an HTML page carrying a client-side
   `<meta http-equiv="refresh">` to `static.aer.ca`, not a real HTTP
   redirect -- `httpx` does not follow this even with
   `follow_redirects=True`, so the client goes straight to `static.aer.ca`;
   ST3's `.xlsx` files and ST1's `.zip` archives, by contrast, answer with a
   genuine HTTP 303 to the same host, confirmed live, so those are left to
   redirect-following;
2. the archive-ZIP URL path prefix genuinely changes at the 2023/2024
   boundary (`/prd/data/well-lic/` for 2024 onward, `/data/well-lic/` with
   no "prd" segment for 2023 and earlier), confirmed by reading the real
   links on AER's own archive page rather than guessed.

Content parsing stops at link-resolution for ST3's `.xlsx` files (confirmed
existence via HEAD, not parsed) -- this project has no pinned XLSX-parsing
dependency, matching `modules/cmhc/data_tables/`'s own precedent of not
adding one for a single module's convenience. A Tableau-hosted "Well Licence
List for all of Alberta" full-inventory CSV was investigated and not
pursued: it repeatedly failed to respond within 15-45 seconds across both a
browser fetch and a bare `curl`, confirmed live, consistent with an
on-demand-rendered Tableau export rather than a static file.

All three shipped tools confirmed live end-to-end 2026-09-22 (a real ST1
Tuesday report parsed to 2026-09-15, a real 2023 archive link resolving to
the pre-"prd" path, and a real ST3 Oil link with a live last-modified date).

## Manitoba

**Status:** Shipped.

geoportal.gov.mb.ca (Data MB), ArcGIS Hub: `arcgis_hub_*` (`portal="mb"`), 3
tools (dataset search, item detail with download links, direct
FeatureServer/MapServer row queries). Content is bilingual within each field
(not split by language) — `lang` is a documented no-op. Verified against
live Hub Search API v3, ArcGIS REST query, and `/api/download/v1` responses.

## Saskatchewan

**Status:** Shipped.

geohub.saskatchewan.ca (Saskatchewan GeoHub), ArcGIS Hub: `arcgis_hub_*`
(`portal="sk"`), 3 tools, same shape as Manitoba's. Some items'
FeatureServer/MapServer services live on a government domain
(`gis.saskatchewan.ca`) rather than `*.arcgis.com` — the shared client
checks for `/rest/services/` in the URL, not an `arcgis.com` domain, because
of this. Verified against live responses.

## New Brunswick

**Status:** Shipped.

gnb.socrata.com, Socrata (SODA): `socrata_*` (`portal="nb"`), 5 tools
(catalogue search, dataset detail, categories, tags, direct SoQL row
queries). Content is bilingual within each field (English/French together)
rather than split fields — `lang` is a documented no-op. GeoNB map services
remain a separate, not-yet-built spatial surface. Verified against live
discovery/Views/SODA responses.

## Newfoundland and Labrador

**Status:** Shipped.

`opendata.gov.nl.ca`, custom HTML catalogue: local search/pagination over
tabular and spatial listings, tag discovery, dataset metadata, and official
CSV/XLS/TXT/KMZ/shapefile download links. Verified live against the
tabular/spatial listings, date sorting, Explore tag cloud, dataset detail
metadata/file table, and typed not-found behavior. The official GeoAtlas
spatial surface remains separate. Portal content is English-only; the module
preserves the Open Government Licence—Newfoundland and Labrador attribution
and every source/detail/download URL.
