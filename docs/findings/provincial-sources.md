# Provincial sources

Findings moved from [`ROADMAP.md`](../ROADMAP.md) on 2026-09-25. Each section
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

Shipped 2026-09-18: `arcgis_hub_*` (`portal="mb"`)/`arcgis_hub_*`
(`portal="sk"`)/`arcgis_hub_*` (`portal="pe"`), verified live against all
three portals' Hub Search API v3
(`/api/search/v1/collections/dataset/items`), the classic ArcGIS …

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

catalogue.data.gov.bc.ca, CKAN Action API: `ckan_*` (`portal="bc"`), 10
tools (search, dataset/org/resource/license detail, tags, groups, and --
added 2026-09-20 -- `ckan_datastore_search` for row-level queries against a
DataStore-active …

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
does not expose useful groups in the tested catalogue. **Alberta has no DataStore.** When `datastore_search` was added (2026-09-20),
every DataStore-active resource returned HTTP 500. Checked again on
2026-10-02: none of the 37,487 packages has `datastore_active` set, so the
resources are file-only and `ckan_datastore_search` cannot read them. The
tool still surfaces the portal's errors as `UpstreamError`.
A second, genuinely separate Alberta
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

## Sequence 3: Newfoundland and Labrador custom portal

Adaptor for Newfoundland and Labrador.

The provincial open-data catalogue has its own page-based interface and
downloadable tabular/spatial files. Map its live endpoints separately after
the two reusable adaptors are working; do not force it into CKAN or Socrata.
This is now the next provincial implementation.

## Prince Edward Island

**Status:** Shipped.

data.princeedwardisland.ca, ArcGIS Hub: `arcgis_hub_*` (`portal="pe"`), 3
tools, same shape as Manitoba's. At least one item's underlying service
reports an empty `layers` list with its one queryable table at a non-zero id
(2) — the default-layer-index resolution this adaptor added because of that
applies here too.

## Institut de la statistique du Québec (ISQ)

**Status:** Shipped.

Checked 2026-09-26 and shipped the same day as `modules/isq/`
(`isq_search_tables`, `isq_get_table`).

Données Québec carries only 7 ISQ datasets (organization `isq`), all
geography. ISQ's statistics are on statistique.quebec.ca, a Next.js site
whose pages embed their record in `__NEXT_DATA__`. The BDSO data bank
(bdso.gouv.qc.ca) closed on 2025-12-18 and ISQ's own tables moved to that
site.

- **Catalogue.** `sitemap.xml` lists 7,078 detailed-table pages
  (`/fr|en/produit/tableau/<slug>`, 3,538 English), plus 12,489 files,
  1,238 publications and 2,864 subject documents. Slugs are the titles,
  so search matches their words. The site's own search is Google CSE.
- **Static tables** (7 of 12 sampled): the page JSON holds the table as
  HTML (`html`) and an Excel file name (`excel`, served under
  `/<lang>/fichier/`).
- **Dynamic tables** (5 of 12 sampled): the page script reads them from
  the engine that powered BDSO, now under
  `statistique.quebec.ca/pls/ken/ken411_data_explt_v2.*`, by table number:
  `p_retrn_titre`, `p_retrn_header` (JSON column tree and field list),
  `p_retrn_data` (all rows as `;`-separated CSV; 26 of 26 sampled tables
  returned everything in one response in 0.3 to 1.3 s, largest 1.4 MB),
  `p_retrn_note_html` (notes and sources) and `p_retrn_signe` (the legend
  of conventional signs). `robots.txt` disallows `/pls/ken/`; the project
  owner decided to read it anyway, on demand, one table per request, at
  one request per second, never crawled.
- **Values** are French-formatted (`1 015,1` with a normal, no-break or
  narrow no-break space); flags sit in a paired `_sign` column (r, p, e,
  x, F, and survey precision marks like `a`, `*`, `(+)`). Some cells hold
  HTML. Column headers nest (`Moins de 1 verre / (%)`); untitled label
  columns are `de_coln`, `de_detl`, `de_group` and `mesr`.
- **Uniqueness.** Of 26 sampled dynamic tables, about 18 are ISQ's own
  sources (Québec youth health survey, care experience survey, the
  culture and communications observatory, Conseil des arts et des
  lettres, ISQ investment and R&D surveys, disposable income by MRC),
  most others are ISQ tabulations of StatCan microdata for Québec, and 2
  (population estimates, CPI) duplicate StatCan tables.

## Provincial and territorial statistics agencies

Checked live on 2026-09-30 (ISQ is already shipped, Alberta Treasury Board and
Finance is `ab_economic`).

| Agency | What it publishes | Reachable now | Verdict |
|---|---|---|---|
| BC Stats | `bc-stats` on BC CKAN: 99 datasets, CSV and XLSX, about half with DataStore; OGL-BC | Yes, `ckan_*` (`portal="bc"`) | Covered. Gap: XLSX-only tables (LFS, GDP, tourism, population projections) have no DataStore. |
| Saskatchewan Bureau of Statistics | XLSX and PDF on `publications.saskatchewan.ca` (Provincial Economic Accounts, Labour Force Statistics, Monthly Statistical Review) | No | **Not built (2026-10-01)**: Crown copyright with non-commercial reproduction only, no open licence; see the section below. |
| Manitoba Bureau of Statistics | Only the Economic Dashboard CSV (`gov.mb.ca/finance/economicdashboard/_asset/api/first_layer.csv`): 22 latest values, mostly StatCan | No | Small; the site's robots.txt disallows ClaudeBot and anthropic-ai. Not built. |
| Ontario Ministry of Finance | HTML tables on ontario.ca (quarterly demographics); datasets on data.ontario.ca | `ckan_*` (`portal="on"`) | data.ontario.ca answered HTTP 429 (Azure WAF) on four attempts from one IP: re-test the shipped `portal="on"` client. |
| Nova Scotia Finance | Daily Stats commentary and chart images, no data files; Socrata copies archived in 2020 | Partly | Skip. |
| New Brunswick Finance | gnb.ca | Socrata (`portal="nb"`) | Blocked by a Cloudflare challenge. |
| PEI Statistics Bureau | princeedwardisland.ca | Almost nothing in the Hub | Blocked by a Radware bot challenge. |
| NL Statistics Agency | stats.gov.nl.ca: 18 topic pages, about 160 XLSX and XLS files (labour, CPI, population, GDP, trade), monthly updates; copyright grant for public use | No (`nl_opendata` is a different site) | **Build candidate**: no robots.txt, unblocked, no overlap. |
| Yukon Bureau of Statistics | Ten clean CSV datasets on open.yukon.ca (population by age and sex, rent and vacancy, building permits, fuel prices), OGL-Yukon | `ckan_*` (`portal="yt"`) for search and links, no row reader | **Build candidate** as a row reader; `open.yukon.ca/robots.txt` disallows `/api/` and sets Crawl-Delay 10. yukon.ca is blocked. |
| NWT Bureau of Statistics | statsnwt.ca XLSX and PDF with irregular layouts | CKAN links only | Later. |
| Nunavut Bureau of Statistics | gov.nu.ca | No | Blocked (Cloudflare), contents unverified. |

### Status after the 2026-09-30 build

NL Statistics Agency (`modules/nl_stats/`) and the Yukon Bureau of Statistics
(`modules/yukon_stats/`) are shipped. Smoke tests: NL lists 160 files in 15
topics and reads both an .xlsx and a legacy .xls (the quarterly population
sheet starts at 1971, 530,854 for N.L.); Yukon lists 176 tables in ten
datasets and returns Whitehorse's population (34,368 in September 2025) and
the territory's median rent ($1,340, first quarter 2025). Quirks: NL layouts
vary (title rows, units rows, years across columns), so headers are guessed;
several NL rows repeat one file under different titles; Yukon's population CSV
is 53 MB because a footnote repeats on every row, so `footnotes` is dropped;
Yukon community names carry suffixes (`Whitehorse - City`).

Ontario re-test: `data.ontario.ca` answered HTTP 429 to every request from the development machine for part of 2026-09-30, including the home page and a plain `package_list`, with both a browser User-Agent and `maplestats-mcp`; the project client failed the same way (`UpstreamUnavailable`). A fetch from outside that network succeeded at the same time, so the block was on the address. It cleared later the same day: the live smoke test for `portal="on"` passed. If it returns, it is the site's WAF, not the client.

### Saskatchewan Bureau of Statistics: not built (2026-10-01)

Re-checked live. The Bureau's page
`saskatchewan.ca/government/government-data/bureau-of-statistics/economic-reports-and-statistics`
lists the current Provincial Economic Accounts (2024 edition, PDF, and a
tables file) as `publications.saskatchewan.ca/api/v1/products/86383/formats/<id>/download`;
the format ids change each issue. `publications.saskatchewan.ca` is an
Angular app with a JSON API (`/api/v1/products/86383` answers) and its
`/robots.txt` is a 404, so a build would be technically possible. The terms
are the obstacle:

- `saskatchewan.ca/copyright`: "Materials on this website are owned by the
  Government of Saskatchewan and protected by Crown copyright." Materials
  "may be reproduced for non-commercial purposes", reproduced accurately and
  not as an official version; "Reproduction of any materials for commercial
  purposes requires the advance written permission of the Government of
  Saskatchewan."
- `saskatchewan.ca/terms-of-use` (last modified 2025-12-31): do not "access
  them using a method other than in the manner, and with the interface, we
  provide"; content is "subject to copyright protection".
- No open-government licence is named on the Bureau page or the Publications
  Centre. The Centre's own copyright page is a client-side route with no
  text in the served bundle.

A publicly hosted server cannot restrict its users to non-commercial use,
and the terms grant no permission for automated reuse, so nothing was built.
Revisit only with written permission from the Bureau or a published open
licence. Labour force and CPI tables on the same page repeat StatCan.

## Provincial general election results

**Status:** Shipped 2026-10-01 for Quebec, Alberta and British Columbia as
`modules/elections_provincial/` (3 tools), with Saskatchewan added 2026-10-02 (see
the Saskatchewan section below); Ontario not built (terms of use).
Each source's terms and robots rules were read before any data was requested.

| Province | Source | Terms (wording) | Decision |
|---|---|---|---|
| Quebec | `donnees.electionsquebec.qc.ca/production/provincial/resultats/archives/gen<date>/resultats.json`, the files the result pages read (found in `historiqueResultatsGen.js`); 14 general elections, 1973-10-29 to 2022-10-03 | https://www.electionsquebec.qc.ca/notre-institution/conditions-dutilisation/: "Vous pouvez télécharger et reproduire tout élément de notre site Web à des fins non lucratives. Dans ce contexte, aucune autorisation n'est requise et c'est gratuit. Vous devez cependant mentionner la source et notre droit d'auteur (©)." Other uses need written permission. `robots.txt` on www: `Crawl-delay: 10`; the data host answers 403 to `/robots.txt` and `/production/` | Built; paced at one request per 10 seconds, cached a day, attribution on every response. Non-profit use only. |
| Alberta | `officialresults.elections.ab.ca/orResultsPGE.cfm?EventId=N` (all divisions) and `orWinningCandidates.cfm?EventId=N`; events 12 (2008), 21 (2012), 31 (2015), 60 (2019), 101 (2023) | https://www.elections.ab.ca/terms-conditions/ ("Terms of Use - Non-Commercial or Educational Reproduction"): may be reproduced "without charge or further permission" if the materials are not modified, users exercise due diligence, Elections Alberta is identified as the source, and the reproduction is not represented as an official version. Commercial reproduction of multiple copies is prohibited. No robots.txt (404) | Built; attribution and a "not an official version" statement on every response; non-commercial use only. Per-division pages name every candidate (87 requests per election) and are not read. |
| British Columbia | BC Data Catalogue dataset `provincial-voting-results` (two CSVs: by voting area 2005-2020, 30 MB, Windows-1252; by voting place from 2022, 1.6 MB, UTF-8) | Elections BC Open Data Licence (https://www.elections.bc.ca/docs/EBC-Open-Data-Licence.pdf): "a worldwide, royalty-free, perpetual, non-exclusive licence to use the Information, including for commercial purposes"; attribution "Contains information licenced under the Elections BC Open Data Licence". `elections.bc.ca/robots.txt` is `User-agent: * Disallow: /`, so only the catalogue's download URLs are used (its robots.txt disallows `/api/` and asks for a 10 second crawl delay) | Built; resource URLs are fixed, not found through the CKAN API. |
| Ontario | `results.elections.on.ca` Election Explorer (`/api/election-explorer/candidates`, POST, returns every candidate with party, votes and winner flag, 1867 onward) and its CSV download | https://www.elections.on.ca/en/terms-of-use.html: users must not "use software, devices, scripts, robots or any other means or processes (including crawlers, browser plugins and add-ons or any other technology) to scrape the sites or services or otherwise copy data from the sites or services"; content "may not be copied, downloaded, reproduced, republished ... except for personal use, without the prior written consent of Elections Ontario". `robots.txt` on www.elections.on.ca allows everything, but the terms cover "any other websites owned by Elections Ontario" | Not built. data.ontario.ca has no provincial general election dataset (one search hit, municipal election results). |

How the files read:

- Quebec: `circonscriptions[]` with `nbElecteurInscrit`, `nbVoteValide`, `nbVoteRejete`,
  `tauxParticipation` and `candidats[]` (name, party abbreviation, votes, share), sorted by
  votes; `statistiques.partisPolitiques[]` gives party names. No winner flag, so the top
  candidate is the elected one. Files before 2014 lack candidate and party ids.
- Alberta: unbalanced upper-case HTML (unclosed cells, bare `&`), read with regular
  expressions. A cell can hold several numbers when independents ran in one division
  (Fort McMurray-Wood Buffalo 2023: 625 and 331), so each becomes its own row. A party with
  no candidate cannot be told from zero votes, so zero cells are dropped.
- British Columbia: one row per candidate and voting opportunity; summing `VOTES_CONSIDERED`
  for `VOTE_CATEGORY = Valid` by district, candidate and party gives the district totals, and
  `Rejected` rows give rejected ballots. The by-voting-area file's byte order mark survives a
  Windows-1252 decode as three characters and has to be removed. By-elections are in both
  files and are skipped.

Smoke test (`scripts/smoke_test_elections_provincial.py`, run 2026-10-01): winners equal
seats for all 25 elections (Quebec 110, 122 or 125; Alberta 83 in 2008 and 87 after; BC 79,
85, 85, 87, 87, 93), party seats add up, and the newest election of each province matches
known results (Quebec 2022 CAQ 90, PLQ 21, QS 11, PQ 3; Alberta 2023 UCP 49, NDP 38; BC 2024
NDP 47, Conservative 44, Green 2).

### Saskatchewan (added 2026-10-02)

**Source.** Elections Saskatchewan (the Chief Electoral Officer's office, a
legislative office, not part of the provincial government's saskatchewan.ca
site). `elections.sk.ca/reports-data/election-results/` links one
poll-by-poll file per general election on `cdn.elections.sk.ca`: CSV for 2024
(`/upload/2024-GE-POLL-BY-POLL-RESULTS-v1.0.csv`), 2020
(`.../2020-GE-POLL-BY-POLL-RESULTS-v2.0.csv`) and 2016
(`/reports/2016 GE Poll by Poll Results.csv`), and an Excel workbook for 2011
(`/upload/statementofvotes-2011-pollresults.xlsx`, one sheet per
constituency). Earlier elections (1905 to 2007) are PDFs only. The ten
by-elections since 2014 each have a CSV; they are not read. The results of the
2024 election are also on `results.election.sk.ca`, which did not answer.

**Terms: none found.** Read before any data was requested, on 2026-10-02:

- `elections.sk.ca/robots.txt` and the CDN's `/robots.txt` return 404 (the CDN
  answers an Azure XML error), so there is no crawl rule.
- The footer links are Accessibility, Privacy policy, Legislation and News
  releases, and the only text is "Copyright (c) 2025 Elections Saskatchewan".
  `/terms-of-use`, `/copyright` and `/privacy` are 404s; the Privacy policy
  page covers personal information, cookies and Google Analytics only; the
  Legislation, FAQ, Links, Media and Accessibility pages and the results page
  itself carry no licence, reuse or scraping wording.
- No open-data licence is named, and the data is not on the provincial open
  data portal (`publications.saskatchewan.ca`'s Crown copyright and
  non-commercial reproduction terms, which ruled out the Bureau of Statistics,
  belong to saskatchewan.ca and are not stated on elections.sk.ca).

Nothing prohibits automated access, but nothing licenses reuse either. The
project owner accepted that risk; it is recorded in the module docstring, in the
module notes and on every Saskatchewan response (`provenance.limits`).

**How the files read.** Header spellings differ by year (`Row Order` and `Row
Ordering`, `Poll Name` and `PollName`, `Rejected` and `RejectedBallots`, `BPSK`
and `BP`) and are matched with spaces removed. The 2024 and 2016 files are
Windows-1252, the 2020 file is UTF-8 with a byte order mark. The 2024 file
writes "Last, First", the others "First Last". Vote counts and registered voters
carry a thousands comma in the 2020 file (`"1,489"`); blank means zero.
Candidate names repeat on every poll row. Registered voters repeat across split
polls (`2 A/B`), so electors and turnout are not given. The 2011 workbook has a
header row starting `Poll`, candidate names, party codes on the next row, poll
rows, then a `Totals` row of formulas (summed here from the poll rows), and one
sheet is named `Sasktoon Nutana`. A party column with no candidate and no votes
in a constituency is skipped.

**Smoke test** (`scripts/smoke_test_elections_provincial.py sk`, run
2026-10-02): winners equal seats in all four (61, 61, 61, 58), and seats by
party match the legislature: Saskatchewan Party 34 and NDP 27 (2024), 48 and 13
(2020), 51 and 10 (2016), 49 and 9 (2011). Valid votes: 466,930, 441,736,
433,030 and 398,486; Saskatchewan Party shares 52.3%, 61.1%, 62.5% and 64.2%.

## British Columbia lobbyists registry (Office of the Registrar of Lobbyists)

**Status:** Shipped 2026-10-02 as `modules/bc_lobbyists/` (5 tools:
`bc_lobbyists_search_registrations`, `bc_lobbyists_get_registration`,
`bc_lobbyists_search_activity_reports`, `bc_lobbyists_summarize_activity`,
`bc_lobbyists_list_codes`).

**Access and licence (checked live 2026-10-02).** `robots.txt` on
lobbyistsregistrar.bc.ca disallows only `/sitemap/`. The open data page
(`/the-registry/open-data/`) links two zips and two XLSX data dictionaries, all
at `/app/secure/orl/lrs/do/mssDtstRprt?file=...` (a plain GET answers 200
`application/octet-stream`; the session cookie is not needed):
`ORL_Registration_Data.zip` (28 MB, 16 CSVs, 260 MB unpacked, members dated
2026-09-20), `ORL_LAR_Data.zip` (5.5 MB, 5 CSVs, 39 MB unpacked),
`ORL_data_dictionary_registrations.xlsx` and `ORL_data_dictionary_LARs.xlsx`.
Updated monthly. Licence: Open Data Licence for the Office of the Registrar of
Lobbyists for British Columbia, version 1.0 (PDF under `/media/1285/`): worldwide,
royalty-free, perpetual, non-exclusive, commercial use included (terms 2 and 3);
attribution required, "Contains information licensed under the Open Data Licence
for the Office of the Registrar of Lobbyists for British Columbia." when the ORL
names none (term 4); term 6(a) grants no right to Personal Information (FOIPPA
Schedule 1). Nothing forbids automated access, so it is built; every result
carries the attribution.

**Personal Information.** FOIPPA's definition excludes "contact information"
(name, position or title, business address and telephone of a person in a business
capacity), so lobbyist, designated filer and office-holder names with titles and
organizations are kept: they are what a lobbying registry is for. Dropped, and
never read from the zip: street addresses (consultants often file from home:
`FILER_ADDRESS`, `FIRM_ADDRESS`, `CLIENT_ORG_ADDRESS`), telephone numbers,
political, sponsorship and recall contribution flags, `Registration_Gifts`
(named office holders with values), `Registration_PublicOffice` (a lobbyist's
earlier career), POH and exemption-decision fields, code-of-conduct rows,
beneficiaries (affiliate and coalition members, with addresses, may be people),
government funding, and the legacy `Registration_Target_Contacts` (94 MB) and
`Registration_Target_Agencies` (50 MB) files. A test builds zips holding all of
these and checks none reaches any result. Reading names and titles as contact information is a
judgement call; it is stated in the module docstring and
every result's `omitted` field.

**How the data reads.** UTF-8 with a byte order mark; absent values are the text
`null` (LAR_SPOH `BRANCH` is sometimes empty instead). Registrations are
versioned: 26,925 REG_IDs are versions, chained by `PREVIOUS_VERSION_REG_ID`;
the ones nobody names as a predecessor are the 6,661 current registrations
(1,265 active, 5,396 ended; a superseded version always has an end date). The
third number of `REG_NUM` counts versions, and the earliest start in a chain is
when the registration began. Lobbyists sit in separate consultant and in-house
files (98,791 in-house rows), topics repeat once per detail id, and ministries
are a comma-separated id list resolved through `BC_Public_Agencies` (409 entries).
Activity reports start 2020-05-04: 75,083 `LAR_Primary` rows are 49,586 reports
(one row per in-house lobbyist), 110,334 office-holder rows; the original of an
amended report is no longer in the file. `REG_TYPE` holds `Cons` or `Org` although
the dictionary says 1 and 3. "Member(s) of the BC Legislative Assembly" is a
ministry-level agency with the member named. The 2020 Act's subject matters (SM-xx,
56) and intended outcomes (BC-01 to BC-07, plus legacy IO-01 to IO-06) are the same
in both zips.

**Smoke test** (`scripts/smoke_test_bc_lobbyists.py`, run 2026-10-02, both zips
about 25 s): 469 active Health registrations (308 in-house, 161 consultant); BC
Dental Association is registration 9997-443-56; 1,187 activity reports naming the
Health ministry since 2025-01-01; the Member(s) of the Legislative Assembly (11,771
reports), Office of the Premier (4,929) and Health (3,838) are the most-named
agencies; Deputy Minister appears in 13,767 reports.
