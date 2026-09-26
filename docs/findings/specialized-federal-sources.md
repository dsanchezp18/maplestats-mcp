# Census and specialized federal sources

Findings moved from [`ROADMAP.md`](../../ROADMAP.md) on 2026-09-25. Each section
records what was checked, against which live responses, and what the
module does about it. Dates are when a finding was confirmed; the
status in `ROADMAP.md` is the current one.

## Census (StatCan Census Program / Census Profile)

**Status:** Shipped.

Investigated and shipped 2026-09-20. The public Census Profile search tool
(www12.statcan.gc.ca/census-recensement/...) is a legacy server-rendered
ColdFusion (.cfm) app with no JSON API of its own -- confirmed live via
network-request inspection of both its search and profile-table pages, every
one a plain HTML GET. The real access path is a separate, genuinely
documented "2021 Census Profile Web Data Service" -- a standards-compliant
SDMX 2.1 REST API at
`api.statcan.gc.ca/census-recensement/profile/sdmx/rest/`, distinct from
`modules/statcan/sdmx` (a different host, www150.statcan.gc.ca, XML-only,
for generic table/vector data) and from `modules/statcan/wds`/`rdaas`.

New module `modules/statcan/census_profile/` (`statcan_census_profile_*`, 3
tools: search_geography, search_characteristic, get_data) covers 14
geography levels (provinces/territories, census
divisions/subdivisions/tracts, dissemination areas, forward sortation areas,
health/economic regions, federal electoral districts, population centres,
designated places, dissolved CSDs), each with its own geography codelist
(`CL_GEO_<suffix>`, confirmed live for every level), crossed against 2,631
named characteristics (`CL_CHARACTERISTIC`, shared across all levels) and
gender/statistic breakdowns.

Confirmed live end-to-end: Ontario's 2021 population (14,223,942) via
`get_data`, and geography name search for both a province and a census
subdivision (Toronto). Four real quirks handled:

1. `codelist`/`dataflow` metadata resources only return JSON via HTTP
   content negotiation (`Accept:
   application/vnd.sdmx.structure+json;version=1.0`) -- the documented
   `format=jsondata` query parameter only affects the `data` resource;
2. SDMX-JSON here is self-describing but positionally indexed -- a series
   key like "0:0:0:0:0" indexes into each dimension's own per-response
   `values` list, not a global codelist, and attributes (GEO_DESC, TOPIC,
   FLAG, CI_LOW/HIGH, RELEASE_DATE) decode the same positional way, in two
   different embedded-value shapes (coded `{id,name}` vs. plain scalar
   `{value}`) that the client handles generically;
3. the `data` resource is genuinely slow -- confirmed live and reproducible
   across multiple distinct queries at 45-48 seconds via a raw `curl`
   bypassing this client entirely, well past `shared/http.py`'s default
   30-second timeout, so `get_data` passes an explicit 60-second timeout;
4. French output is real and correct but is selected via an
   `Accept-Language` header, not a `lang`/`locale` query parameter
   (`lang=fr` is rejected outright with "Unknown query parameter", confirmed
   live) -- handled internally, so `lang: en\|fr` still works normally from
   the tool's perspective.

Also investigated per a direct request: CensusMapper (the API behind the R
`cancensus` package, referenced in this repository's own `R Code
Conventions.md`) is a third-party (not StatCan) wrapper that requires a free
registered API key for programmatic access -- a real friction point for a
zero-config MCP server that the official SDMX API above does not have. Its
main value-add over the official API is pre-built boundary geometries
(GeoJSON) and unified access to 1996-2021; cross-checking `cancensus`'s own
current source (`R/wds.R`) confirmed it hits this exact same official API
for 2021 data, and only falls back to the keyed CensusMapper API for earlier
years -- a genuine, independent validation of this module's approach.

That same cross-check surfaced one free improvement folded into this module:
the characteristic codelist response already carries a `parent` field for
hierarchical characteristics (e.g. "0 to 4 years" -> parent "0 to 14 years"
-> parent "Total - Age groups of the population"), confirmed live and now
exposed as `CharacteristicMatch.parent_code` at zero extra API cost -- this
was not previously captured. Earlier censuses were investigated as an
explicit follow-up and found to have no equivalent live query API at all:
the full Census Profile SDMX dataflow list contains only 2021-labelled
dataflows (confirmed by listing all 15 the API serves), and `cancensus`'s
own code confirms it needs a registered API key for any year before 2021.

Rather than adopt that key-gated dependency, new module
`modules/statcan/census_profile_archive/`
(`statcan_census_profile_archive_*`, 2 tools: list_geography_levels,
get_download_link) resolves each older year's own official, unauthenticated
bulk-download resolver instead: 2016 uses
`GetFile.cfm?Lang=E&FILETYPE={fmt}&GEONO={code}` (34 geography-level
groupings, confirmed live for the aggregate-dissemination-areas GEONO
despite a real quirk where that response's `Content-Type` header reads
`application/unknown` instead of `application/zip` --
`Content-Disposition`'s attachment filename is the reliable signal there,
not `Content-Type`); 2001/2006/2011 share one resolver,
`comp_download.cfm?CTLG={catalogue}&FMT={fmt}{level_code}`, with the same
query shape and only the catalogue number and available level codes
differing per year (14 levels for 2011, 5 each for 2006 and 2001 -- coverage
genuinely narrows going back in time, confirmed against each year's own
download page).

Live-verified end to end for all four years by actually streaming each
resolved URL and confirming a real file is served. IVT/XML formats for the
older years use a separate catalogue number and numeric scheme from CSV/TAB
(confirmed live) and are not covered -- CSV/TAB already cover the useful,
non-proprietary case. 1996 has no equivalent bulk-download page under the
`census-recensement/<year>/dp-pd/prof/...` URL scheme used by 2001-2016
(confirmed: 404) and was not further investigated.

PUMFs (Public Use Microdata Files) were not pursued in this pass -- they are
individual-record microdata files distributed separately from Census Profile
aggregates and would need their own investigation.

The public Census Profile search tool
(www12.statcan.gc.ca/census-recensement/...) is a legacy server-rendered
ColdFusion (.cfm) app with no JSON API of its own -- confirmed live via
network-request …

## StatCan catalogues, The Daily, Indicators, Delta File, and other documentation

**Status:** Shipped.

Investigated 2026-09-20 per a direct request. The Daily (StatCan's official
release bulletin, www150.statcan.gc.ca/n1/dai-quo/) has no JSON API behind
its own search/calendar pages -- confirmed live, plain server-rendered HTML
-- but StatCan publishes a genuine, documented, unauthenticated Atom feed
family for it at www150.statcan.gc.ca/eng/sc/rss: one feed per subject (30
subjects) plus an "all" feed, each carrying the last 100 days of releases.
New module `modules/statcan/daily/` (`statcan_daily_*`, 1 tool:
get_releases) covers this, confirmed live in both English and French (the fr
feed uses a `-fra.atom` suffix, confirmed live).

One real quirk handled: a feed entry's title/summary are XHTML divs that can
hold inline markup (e.g. a reference period wrapped in its own `<span>`
inside the title, confirmed live), so the client joins all text within the
div rather than only its direct text. Follow-up investigated the same day
per a direct question ("is there a way to get the full historical archive of
the Daily?"): yes -- the release-schedule calendar page
(`n1/dai-quo/cal3-eng.htm`) renders a much deeper history client-side, and
its raw (pre-JavaScript) HTML reveals the actual source via an inline
`eventsjson:` config pointing at
`n1/dai-quo/ssi/homepage/schedule-previous_releases-{eng,fra}.json` -- a
single JSON array, no pagination, confirmed live with 18,222 entries from
2012-03-14 onward (StatCan's own calendar UI separately claims "since April
2012," about three weeks later than the JSON's actual earliest entry).

Added `statcan_daily_search_archive` to the same module, filtering by
title/reference-period keyword and/or a date range; its own `date` field
carries an artificial time-of-day used only to order same-day entries, not a
real timestamp, so the client keeps only the date component. Investigated
further the same day per a direct request to go deeper on catalogues and
documentation. StatCan's individual Catalogue-number resolver (e.g.
catalogue number 11-621-M resolves via a `cgi-bin/IPS/display?cat_num=...`
redirect to a plain HTML landing page at `n1/en/catalogue/{cat_num}`,
confirmed live) has no structured/JSON metadata API of its own -- a Daily
feed entry already carries the resolved catalogue link directly when
relevant, so no separate single-document resolver tool was added.

The real find was StatCan's central "Reference resources" catalogue at
`www150.statcan.gc.ca/n1/en/type/reference` -- the actual home of
"Definitions, data sources and methods" (DSDM) content: 2,031 documents
(technical reference guides, survey documentation, geographic file
specifications), each with a catalogue number, category, description, and
release date, behind a faceted keyword/subject/survey search. It is a plain
Drupal 10 view with no JSON API, but genuinely scrapeable, so it was built:
new module `modules/statcan/reference/` (`statcan_reference_*`, 1 tool:
search_documents).

Two real quirks handled, both confirmed live and reproduced with a bare
`curl`:

1. the search view silently ignores its own `text`/`texte` query parameter
   -- rendering all 2,031 documents unfiltered -- unless the requesting
   session already visited the unparameterized base page first and carries
   the session cookie it sets; this client keeps a dedicated
   `httpx.AsyncClient` (not `shared/http.py`'s shared one) with
   `follow_redirects=True` and warms up each language's session once per
   process before its first real search.
2. The results page renders the same paginated list more than once: one
   combined section holding the actual requested page, immediately followed
   by several more sections that re-list the identical items grouped by
   category -- parsing the whole page naively returned 3x the requested
   `count` in testing (30 items back for a `count=10` request) before this
   was scoped to only the first section. French uses a different URL path
   (plural `type/references`) and a different query parameter name (`texte`,
   not `text`), both confirmed live. General StatCan/Canada.ca site search
   was also checked and is plain HTML with no JSON API of its own (the
   site-search form posts to a shared Government of Canada search results
   page, not a StatCan-specific endpoint) -- not pursued, since the
   Reference resources catalogue above already covers the
   documentation-discovery need directly. Investigated a fourth time per an
   explicit "we cannot leave any StatCan out" request: read StatCan's own
   official "Developers" hub (statcan.gc.ca/en/developers) directly rather
   than continuing to guess at what might exist, and it names its own
   complete API list -- closing four real, confirmed-live gaps this pass.
3. The "Analysis" catalogue (10,841+ analytical articles, "Stats in brief",
   journals and periodicals, at `n1/en/type/analysis`) turned out to be the
   exact same Drupal 10 search engine as Reference resources -- same
   session-cookie quirk, same duplicate-`<details>` quirk, same HTML
   structure, only the path (`analysis`/`analyses`) and query param differ
   -- so `modules/statcan/reference/` was generalized (a shared
   `_search(catalogue, ...)` internal helper, warm-up cache keyed by
   `(catalogue, lang)` instead of just `lang`) and a new
   `statcan_reference_search_analysis` tool added, at effectively zero new
   parsing code.
4. The 2016 Census Profile has its own genuinely separate, live,
   unauthenticated JSON REST API (CPR2016 for data, CR2016Geo for
   geography/DGUID lookup, at
   `www12.statcan.gc.ca/rest/census-recensement/`) -- distinct from the
   SDMX-based 2021 service and from `census_profile_archive`'s 2016
   bulk-download-only coverage, confirmed live end-to-end (Canada's 2016
   population, 35,151,728, matches the known published figure). New module
   `modules/statcan/census_profile_2016/` (2 tools: list_geographies,
   get_data) covers all 12 geography levels and 14 topics, with separate
   total/male/female values and suppression symbols preserved.
5. The Delta File (`www150.statcan.gc.ca/delta/{YYYYMMDD}.zip`, StatCan's
   own "preferred mechanism ... for large updates") is a deterministic daily
   bulk-update archive containing every table/vector data and metadata
   update released that business day; new module `modules/statcan/delta/` (1
   tool: get_file_link) resolves the URL for a given date and confirms
   existence via a HEAD request rather than downloading the file just to
   check -- files only exist for business days with a release, confirmed
   live (a Sunday 404s cleanly). This module keeps its own small httpx
   client with `http2=True` and `follow_redirects=True`, since the delta
   path 301-redirects to a canonical URL and `www150.statcan.gc.ca` needs
   HTTP/2 offered in the TLS handshake (the same host-level quirk
   `shared/http.py`'s own docstring documents for a different endpoint).
6. StatCan's official Indicators JSON feeds
   (`ind-all.json`/`ind-econ.json`/`ind-hp.json`, the same feeds powering My
   StatCan, StatCan's own home page, and The Daily's indicator widgets) are
   genuine, documented, unauthenticated current-value feeds for named
   indicators (population, CPI, GDP, trade, unemployment, etc.) with growth
   rates and a link back to the releasing Daily article; new module
   `modules/statcan/indicators/` (1 tool: get_indicators) covers all three
   curated datasets, confirmed live (2,362 indicators in "all"), resolving
   each entry's bilingual `{"en", "fr"}` fields to the requested language
   rather than exposing them raw.

Two more items from the same Developers page were checked and found to need
no new code: the 19 "Real-time data tables" (revision-history vintages for
key economic/social series) are ordinary StatCan tables with their own
productIds (e.g. `12-10-0165` for real-time merchandise trade), already
fully reachable through the existing `wds_`/`sdmx_` tools. The "Results and
documentation of surveys and statistical programs" A-Z directory
(`n1/en/type/surveys`, `n1/fr/type/enquetes`, ~899 surveys confirmed live,
active and inactive) was initially deferred as a genuinely different
alphabetical-directory shape (no `#ndm-results`, confirmed live) -- closed
in a later pass triggered by noticing its per-survey detail page
(`n1/en/surveys/{id}`) links to a "Related information" source at
`www23.statcan.gc.ca/imdb/`.

That turned out to be IMDB (Integrated Metadata Base), a genuinely separate,
older Perl-CGI system (`p2SV.pl` for English, `p2SV_f.pl` for French -- a
`lang=fr` query parameter has no effect, confirmed live) holding the actual
"Definitions, data sources and methods" content for every survey: status,
frequency, description, target population, sampling, data sources, data
accuracy, and subjects. Confirmed live that the directory's numeric ID is
exactly IMDB's own "Record number" for the same survey (id 5108 resolves to
"Aboriginal Children's Survey" on both systems), so the directory is the
correct way to discover IDs.

New module `modules/statcan/surveys/` (2 tools: search_surveys,
get_survey_metadata) covers both; the survey directory listing needs the
same session-cookie warm-up as Reference/Analysis, while IMDB itself needs
none. Full methodology sections are linked via `detail_url` rather than
parsed, since they are long prose better read directly than flattened into
fields. One real quirk caught by the live smoke test: an unknown survey ID
redirects through StatCan's own dedicated error page
(`.../error-erreur/stc_srvmsg404.html`), which itself answers HTTP 500 due
to a broken redirect chain on their end (302 -> 301 -> 500, reproduced
identically with a raw curl) -- this is IMDB's deterministic "no such
survey" signal, not a generic failure, and had to be special-cased (matched
on the final redirected URL) to surface as NotFound rather than
UpstreamError.

2026-09-25: `statcan_reference_get_document_formats` (a catalogue number's
HTML/PDF links) was removed, since the server serves data, not documents;
PUMF downloads come from `statcan_pumf_list_files`. The Daily (StatCan's
official release bulletin, www150.statcan.gc.ca/n1/dai-quo/) has no JSON API
behind its own search/calendar pages -- confirmed live, plain
server-rendered HTML -- but …

## NRCan National Burned Area Composite (NBAC)

**Status:** Shipped.

Investigated and shipped 2026-09-20 in response to a direct request (BC
wildfire polygons/dates/adjusted burned area, 2017-2024, for a
school-district-level analysis). Confirmed live this is served by the
Canadian Wildland Fire Information System's GeoServer instance
(cwfis.cfs.nrcan.gc.ca/geoserver, layer `public:nbac`) via standard OGC WFS
2.0 -- the first WFS-platform source in this codebase, so a new
`shared/wfs.py` adaptor was built rather than forcing it into the
ArcGIS/CKAN/Socrata/Opendatasoft shape.

`nrcan_nbac_query_fires`, 1 tool, filters with a standard CQL expression
against NBAC's own fields (e.g. `admin_area = 'BC' AND year >= 2017 AND year
<= 2024`, confirmed live: exactly 3,066 matching BC fire records). Two real
quirks handled: every WFS error (a malformed `CQL_FILTER`, an unknown layer)
answers HTTP 400 with an OGC XML `ExceptionReport`, not JSON, regardless of
the requested `outputFormat` -- `shared/wfs.py` parses the XML to surface a
real message instead of failing to decode it as JSON; and NBAC's date fields
(`hs_sdate`, `ag_sdate`, `capdate`, etc.) carry a trailing literal "Z" on a
plain calendar date (e.g. "2024-08-12Z"), which `date.fromisoformat` rejects
unless stripped first.

`include_geometry` defaults to false (NBAC's full polygon shapefile export
exceeds 1GB) and reprojects to plain lat/lon (EPSG:4326) when a caller does
request geometry, using WFS's own `propertyName`/`srsName` parameters rather
than a client-side filter.

## ISED Office of the Superintendent of Bankruptcy (individual bankruptcy records)

**Status:** Blocked.

Investigated 2026-09-20 per a direct request: the OSB's Bankruptcy and
Insolvency Records Search (ised-isde.canada.ca) requires an account and
charges a minimum $8 per search, confirmed via its own documentation --
paywalled and authentication-gated, not open data, and this project will not
automate account creation or payment. See the ISED row above for the free,
open, aggregate insolvency statistics that remain available instead.

Investigated 2026-09-20 per a direct request: the OSB's Bankruptcy and
Insolvency Records Search (ised-isde.canada.ca) requires an account and
charges a minimum $8 per search, confirmed via its own documentation --
paywalled and …

## Health Canada (public health CKAN data)

**Status:** Shipped (via `ckan_*`).

Investigated 2026-09-21 to correct an over-broad reading of this roadmap's
federal-scope note (see the Federal section intro above). Confirmed live
`hc-sc` publishes 2,983 datasets on the federal CKAN catalogue, already
reachable via `ckan_search_datasets(fq="organization:hc-sc")` -- same
pattern as CRTC/CRA/OSFI/Elections Canada. Spot-checked live: recent titles
skew public-health-surveillance rather than individual medical records --
airborne radionuclide monitoring, cannabis compliance/enforcement and
inspection data, new-psychoactive-substance and illicit-drug-landscape
reports (ketamine, benzodiazepines, medetomidine/xylazine trend analyses),
ice-arena air quality studies, a bilingual labelling lexicon, pesticide
product information.

The narrower exclusion this roadmap's Federal section still means stands:
Health Canada's Drug Product Database, the per-record recalls/safety-alerts
lookup tool, and the nutrient file are record-lookup-shaped products outside
CKAN's dataset model (and, per the original 2026-09-14 scoping call, out of
scope regardless) -- not a reason to treat the rest of `hc-sc`'s CKAN
catalogue as unavailable. PHAC (`phac-aspc`, 761 datasets) is reachable the
same way and was not investigated further in this pass. (The
recalls/safety-alerts site was later shipped as `recalls_*` on 2026-09-26;
see [its section](#government-of-canada-recalls-and-safety-alerts).)

## PHAC Health Infobase

**Status:** Shipped.

Checked and shipped 2026-09-26 as `modules/phac_infobase/`
(`phac_infobase_list_datasets`, `phac_infobase_describe_dataset`,
`phac_infobase_query`).

The site lists its 211 products in `/src/json/articles.json`. Each of
the 130 non-blog product pages and its local scripts was fetched and
searched for `.csv`, `.json` and `.zip` references (mostly `d3.csv(...)`
calls and "Download data" links). The module reads a curated catalogue
of 55 files with stable names, 9 of them also in French: respiratory
viruses (RVDSS laboratory detections, FluWatch+ outbreaks, FluWatchers,
severe outcomes, SPRINT-KIDS, CNISP sentinel hospitals), wastewater
(weekly, daily, latest trends), opioid and stimulant harms, supervised
consumption sites, CSUS, CPADS and CSADS survey indicators, tobacco
sales, measles, mpox, tuberculosis, emerging respiratory pathogens,
enteric outbreaks, notifiable diseases 1924-2016, hepatitis C treatment,
vaccine adverse events, cancer statistics, Health of People in Canada,
the risk factor atlas, the 2018 CCDI, PASS and congenital anomalies
snapshots, positive mental health, and archived COVID-19 cases, testing,
hospital capacity and vaccination (last updated 2023-2024).

Overlap with `ckan_*`: open.canada.ca lists 68 resources on
health-infobase.canada.ca. Of the catalogued files, only the COVID-19
download, hospital capacity and vaccination coverage files, the COVID-19
wastewater archive, the 2018 snapshots, the opioid ZIPs and the
notifiable disease extract are there. The current respiratory,
wastewater, measles, mpox, tuberculosis, CNISP, vaccine safety and
substance use survey files are not.

Quirks, all covered by mocked tests:

- A missing file answers HTTP 302 to `/404.html` (HTTP 200 HTML), never 404.
- Encodings: UTF-8 with and without a BOM; Windows-1252 for the French
  opioid ZIP, the 2018 snapshots and the enteric outbreak list; DOS code
  page 850 for the French congenital anomalies file.
- Suppression and missing markers: `Suppr.` and `n/a` (opioid harms),
  `n.d.` (its French file), `X` (vaccine safety), `N/A`, `-` and `>=99`
  (COVID-19). They are returned as published and listed with their meaning.
- French 2018 snapshots use decimal commas (`12,2`); other French files
  use points.
- Headers: an empty first column of R row numbers (tuberculosis),
  hundreds of empty trailing columns (the French positive mental health
  file is 16 MB because of them), a misspelled `Mesure_Spéficique` in
  the French opioid file, accents in ZIP member names
  (`DonnéesMéfaitsSubstances.csv`) and `Copy of HoPiC 2025_...` member
  names in the Health of People in Canada ZIP.
- Periods: week-ending dates, `2026 Q1`, `2026 (Jan to Mar)`,
  `2015-2018`, school and survey years (`2024-2025`).
- Dashboards publish one-line "update date" files; the HTTP
  Last-Modified header carries the same information and is used instead.

The site also has a documented API (`/api/`, quick-start page in beta)
over four databases: `opioids`, `cnisp-vri`, `wastewater` and `CYPC`.
`/api/<db>` returns the table list and `updatedAt`, and
`/api/<db>/table/<table>` returns a whole table as JSON (nulls for empty
cells). Only the small CNISP viral respiratory infection tables are read
this way. The CYPC cancer tables are 140-230 MB and the opioid table 36
MB (the 178 KB ZIPs carry the dashboard's data in English and French),
so they are not used. The API
also exposes a free-form SQL route and a cache-reset route; the module
uses neither.

Dashboards with no downloadable data:

- Canadian Chronic Disease Surveillance System data tool: ASP.NET
  WebForms postbacks rendered with JSCharting; open.canada.ca has only
  its case definitions (XLSX).
- The current CCDI, perinatal health indicators, positive mental health,
  suicide surveillance indicator framework, health inequalities and
  congenital anomalies data tools: the same platform. CCDI, PASS,
  positive mental health and congenital anomalies have 2018-2019
  snapshots under `/open/` (catalogued).
- STBBI surveillance dashboard: HTML tables only.
- Notifiable Diseases Online (diseases.canada.ca/notifiable): data to
  2023 is embedded in its page scripts (`ndc_ppd_en.min.js`, about 490
  KB) and the CSV is built in the browser. The 1924-2016 CNDSS extract on
  health.canada.ca is the latest file (catalogued).
- Drug Analysis Service and CIPARS: date-stamped file names
  (`YearlyCounts_20260105.csv`, `Figure_1_CIPARS_R_Combine_12_02_2025.csv`)
  that change with each update; not catalogued. CIPARS ZIP downloads were
  not checked.
- `/oral-health/` answered HTTP 403.

Three catalogued files carry a year in their name and will move with the
next release (`TB_incidence_by_PT_2015-2024.csv`,
`reformatted_data_2025.csv`, `HoPiC-data-2026.zip`); the live smoke test
reports them as NotFound when that happens. Many other interactive
reports load small figure CSVs (perinatal trends, cold injuries, PTSD,
AMR) that could be added as catalogue entries.

Checked values: apparent opioid toxicity deaths in Canada in 2023 are
8,083 in the 2026-09-22 file; tuberculosis incidence in Nunavut in 2024
is 87.5 per 100,000 (36 cases); the measles file of 2026-09-21 counts 311
cases in Alberta this year.

Terms: Health Infobase pages link the Canada.ca terms and conditions;
the files also listed on open.canada.ca carry the Open Government
Licence - Canada.

## ESDC (Employment and Social Development Canada)

**Status:** Shipped (via `ckan_*`).

Investigated 2026-09-21 for the same reason as the Health Canada row above.
Confirmed live `esdc-edsc` publishes 266 datasets on the federal CKAN
catalogue, already reachable via
`ckan_search_datasets(fq="organization:esdc-edsc")`. Spot-checked live: Job
Postings Advertised on Canada's National Job Bank Website, Canada Education
Savings Grant (CESG) beneficiary/payment statistics by province and Forward
Sortation Area, RESP contribution/withdrawal statistics by Forward Sortation
Area, historical minimum wage rates, Old Age Security (OAS) benefit-amount
tables, Canada Pension Plan (CPP) benefit counts by place of residence and
type, and Temporary Foreign Worker Program (TFWP) Labour Market Impact
Assessment statistics including a Negative-LMIA employers list back to 2014.

None of the TFWP/CPP/CESG resources checked are DataStore-active (bulk
CSV/XLSX/XLS only, confirmed live across the full quarterly TFWP series), so
`ckan_get_dataset` remains the access path for these, same as ISED's and
CRA's other bulk statistical exports.

## CMHC

**Status:** Shipped.

Housing Market Information Portal (HMIP, www03.cmhc-schl.gc.ca/hmip-pimh), a
legacy ASP.NET MVC/Kendo UI portal with no JSON API: `cmhc_*`, 4 tools (list
categories, get table options, list provinces, get table data) covering
Rental Market Survey vacancy rates/rents, new housing starts/completions,
secondary rental market, seniors' rental housing, and
population/core-housing-need indicators, for Canada and by province, as a
time series or current cross-tab.

No hardcoded table catalogue — categories and their valid breakdowns are
discovered live from HMIP's own navigation, and each table's `TableId` is
resolved live from an embedded JSON blob rather than a hand-built lookup (an
improvement over the reference `mountainMath/cmhc` R package, read as the
"existing community access pattern" this row asked to investigate, which
hardcodes its entire table registry by hand). Verified live 2026-09-19: an
unresolvable category/geography/TableId returns HTTP 500 with an ASP.NET
error page, not a clean 404; the CSV export is cp1252 (Windows-1252)
encoded, not UTF-8 or strict latin-1 (confirmed against a real em-dash byte,
correcting the reference package's own "latin1" comment); a cell can hold a
suppressed ("**") or not-applicable ("++") marker instead of a number;
`lang` genuinely changes category names (not just prose) since HMIP's
`/en/`/`/fr/` categories are different strings per language; only
Canada/province-level geography is covered — no live CMA/city-level
discovery endpoint was found despite several attempts.

The separate `www.cmhc-schl.gc.ca` "Data Tables" Sitecore document catalogue
is now also shipped (added 2026-09-19) as `cmhc_dt_*`, 3 more tools (list
tables, get table detail, resolve a download link) covering Rental Market
Survey and Household Characteristics official per-edition Excel publications
(72 tables confirmed live across the two categories; Canadian Housing Survey
tables are not yet mapped). Discovery reads geography/edition options and a
table's default download link directly from static HTML (Sitecore item
GUIDs, a different id scheme from HMIP's small integers); resolving any
historical edition's download link uses the site's own resolver API
(`api/Sitecore/PubsAndReports/GetFileDetails`), found via live
network-request inspection of the rendered page rather than documentation —
confirmed live this was necessary: guessing a filename from the current
pattern works for recent editions but fails for at least one older one whose
filename omits a suffix later editions have.

Audited 2026-09-19 against the reference `mountainMath/cmhc` R package's own
source (not just its docs) and found/fixed a **critical CSV-parsing bug**:
the earlier parser assumed every table's CSV export doubles each value
column with a trailing quality-flag column (`header[1::2]`) — true for
statistically-sampled Rental Market Survey tables, but a census-style
administrative table (Starts and Completions Survey, which counts every
issued permit rather than sampling) has no flag columns at all, and the
blind pairing silently misaligned and corrupted every value from the second
column onward (confirmed live against a real Starts-by-CMA table: Barrie's
"Row" starts read as 0 with flag "60" instead of the correct 60 with no
flag).

Replaced with a per-column header walk that only pairs a value column with a
flag when the following header cell is genuinely empty. Also fixed two
related parsing gaps found the same way: values ≥1,000 use a thousands-comma
inside a quoted CSV field (`"1,013"`) which `float()` rejects unless
stripped, and a bare `"-"` is CMHC's own notation for a real, counted zero,
not a suppressed value — both confirmed against the reference package's own
`parse_numeric()` helper and re-verified live.

Also added `"n/a"` to the suppressed-value tokens (`"**"`/`"++"`) on the
same cross-check. Added a genuine capability gap the audit surfaced:
`cmhc_get_table_data` now accepts an optional `filters` dict (e.g.
`{"dwelling_type_desc_en": "Row"}`, `{"season": "April"}`), validated
against and passed through to HMIP's own `AppliedFilters[i].Key`/`.Value`
POST params — confirmed live these genuinely change returned values
(national rental vacancy rate for "Row" dwellings differs from "Apartment"
for the same period), a capability the reference R package exposes but this
module previously did not. |

## CRTC

**Status:** Shipped (via `ckan_*`).

Investigated 2026-09-19: CRTC's Communications Monitoring Report data
(telecom/broadcasting sector revenue and subscriber counts, wholesale/retail
pricing, mobile and broadband availability) is not a separate platform -- it
is already published as 95 ordinary datasets under the `crtc` organization
on the existing federal open.canada.ca CKAN catalogue, confirmed live
end-to-end through this codebase's own `ckan_federal` client (not just a raw
API check): `search_datasets(fq="organization:crtc")` returns real packages
(e.g. "Telecommunications Sector – CMR", "Current Trends in Communications
Industry, Quarterly Results – CMR") each carrying genuine downloadable
CSV/XLSX/DOCX/PDF resources under an Open Government Licence.

No dedicated module needed -- same pattern as IRCC's non-Express-Entry
datasets, already documented above. (A dataset title appearing to contain a
corrupted character while debugging this was a false alarm: `ord()` on the
in-memory string confirmed the correct codepoint U+2013 -- the apparent
corruption was this session's Windows cp1252 terminal failing to print an en
dash, not a real decoding bug in the client or the source data.)
Cross-checked directly against crtc.gc.ca/eng/industr/stats.htm (the CRTC's
own "Surveys and statistics" landing page): its own "Find a CRTC dataset on
Open Data" link points straight at `search.open.canada.ca` filtered to CRTC,
confirming the CRTC itself treats that CKAN catalogue as canonical for
public data -- not a gap this session found by accident.

That page also links to several HTML report pages hosted on crtc.gc.ca
itself (Broadcasting financial summaries at `/eng/industr/fin.htm`,
Aggregate annual returns at `/eng/industr/ann.htm`, Video-on-demand
aggregate statistical data at `/eng/industr/video.htm`, Production reports
by large ownership groups, annual/monthly broadcasting reports) that are not
mirrored on CKAN -- but crtc.gc.ca itself sits behind a Cloudflare Turnstile
challenge that re-triggers on every navigation and did not reliably clear
even in an interactive, real-browser session (it passed once, then
re-blocked the very next page load) -- the same "genuinely blocking
automated access" category as gov.nu.ca (see the Nunavut row above), not a
source a deployed client could hit reliably.

Not pursued further for that reason.

Investigated 2026-09-19: CRTC's Communications Monitoring Report data
(telecom/broadcasting sector revenue and subscriber counts, wholesale/retail
pricing, mobile and broadband availability) is not a separate platform -- it
is already …

## CER (Canada Energy Regulator)

**Status:** Shipped.

Shipped 2026-09-23: `modules/cer/` (2 tools). The CER has no query API; it
publishes bilingual CSVs under cer-rec.gc.ca/open/ and /ouvert/, catalogued
as open.canada.ca's `cer-rec` organization (84 datasets).
`cer_list_datasets` finds datasets through the federal CKAN client and
returns their CSV URLs in the requested language; `cer_query_file` reads any
CER CSV with exact column filters, a Date/Year range, column selection and
most-recent-N rows (pipeline throughput and capacity, exports, tolls,
incidents, refinery runs, Energy Future).

Quirks: French files are Windows-1252 while English ones are UTF-8 with a
BOM; some headers carry trailing spaces; a mistyped path returns HTTP 200
with an HTML page; legacy neb-one.gc.ca links 301 to cer-rec.gc.ca.

## CRA (Canada Revenue Agency)

**Status:** Shipped (via `ckan_*` + new `ckan_datastore_search`).

Investigated 2026-09-20, then investigated again in more depth after an
initial pass under-scoped this row: CRA's tax-filer statistics (333 datasets
under the `cra-arc` organization -- T1/T2 filing compliance, GST/HST
statistics, Canada Child Benefits, TFSA statistics, trust statistics, annual
lists of registered charities back to 2010) are ordinary datasets reachable
via `ckan_search_datasets(fq="organization:cra-arc")`, as first found. The
deeper pass found something the first one missed: several of these datasets
carry **DataStore-active** resources -- confirmed live that the "2024 List
of charities" package alone has 19 such resources, including a 569,000+ row
charity directors/officers table, genuinely queryable row-by-row (not just
downloadable as one CSV) via CKAN's own `datastore_search` action.

This capability did not exist anywhere in this codebase before this session
-- no CKAN module here, federal or provincial, had a
`datastore_search`-backed tool, only a `datastore_active` metadata flag on
some of them. Added `ckan_datastore_search` to the federal module
(`ckan_federal/{schemas,client,tools}.py`, plus a `datastore_active` field
now on every `ResourceInfo`) so a caller can filter a charity's directors by
business number directly, confirmed live end-to-end.

Two real quirks handled: `filters` (exact-match, JSON-encoded) works at any
resource size, but this deployment rejects full-text `q` search with HTTP
409 for a resource over 100,000 rows (`shared/ckan.py`'s existing
non-404-4xx-is-InvalidInput mapping already covers this, no new
error-handling code needed); and the server silently caps `limit` at 32,000
rather than erroring on a larger request (confirmed live against a 569k-row
resource), so `DATASTORE_ROWS_MAX` is set far below that for the same
agent-facing-compactness reason `SEARCH_ROWS_MAX` already was.

Also confirmed live that CRA's own GST/HST "Confirm a GST/HST account
number" registry and Charities Listing search UI are separate,
publicly-billed/agreement-gated verification services (CRA's own
documentation directs API access requests to a business-enquiries phone
line, not a public endpoint) -- out of scope as a result, distinct from the
open dataset-level data covered above. Re-investigated 2026-09-21 per a
direct "there has got to be more" request, checking every lead the first two
passes might have missed.

Confirmed dead ends first, so they are not re-investigated again: the old
`cra-arc.api.canada.ca` "GC API Store" subdomain referenced in third-party
documentation no longer resolves at all (DNS failure, confirmed live with a
direct fetch) -- consistent with StatCan's own developers page statement,
already recorded on this roadmap under the Census/specialized-agencies
StatCan row, that the original GC API Store "closed permanently at 12:00 EDT
on September 29th, 2023"; its replacement
`api.canada.ca`/`dev.api.canada.ca` also fail to resolve.

One genuine new capability was found: CRA's public registry of digital
economy businesses (cross-border digital products/services, platform-based
short-term accommodation) registered for the simplified GST/HST is disclosed
under the Excise Tax Act at a plain canada.ca URL, confirmed live to NOT be
a CKAN dataset (a `package_search` for its own title/topic under `cra-arc`
returns nothing). Confirmed live the entire registry (2,347 rows the day
this was built, refreshed at least daily per the page's own "updated on"
date) is server-rendered in one plain unauthenticated GET -- diffed the raw
response body against the live, JS-paginated DOM to confirm the jQuery
DataTables widget only paginates what is *displayed*, not what is fetched.

New module `modules/cra_digital_economy_registry/`
(`cra_digital_economy_registry_search`, 1 tool) covers it: legal name, trade
name, business number, and registration/de-registration dates, filterable by
name or business number. One real quirk handled: an absent trade name or
de-registration date is marked with a WET-BOEW `<span
class="wb-inv">-</span>` screen-reader-only placeholder rather than an empty
cell, parsed to `None` here. A second, more consequential quirk: this ~470KB
page reliably fails with an HTTP/2 `RemoteProtocolError` (`StreamReset ...
remote_reset:True`) over `shared/http.py`'s shared `http2=True` client --
reproduced consistently across repeated attempts, not a one-off -- while a
plain `curl --http1.1` and a standalone `httpx.AsyncClient(http2=False)`
both fetch the identical URL cleanly; this is the mirror image of the ALPN
quirk AGENTS.md documents for StatCan (which *needs* HTTP/2 offered), so
this module keeps its own dedicated `http2=False` client with its own retry
wrapper rather than touching the shared client's StatCan-motivated setting.

Note for future verification: after roughly a dozen manual fetches of this
exact URL within one session (browser, curl, and repeated client test runs
while building this module), the page began consistently timing out even
under the http2=False fix and the added retry wrapper, while a fresh,
isolated fetch earlier in the same session succeeded in ~2 seconds with the
full 2,347-row payload -- consistent with canada.ca throttling/delaying a
client that has hit the same page many times in quick succession, not a
defect in the http2=False fix itself (which was confirmed working before the
throttling pattern set in).

Re-verify end-to-end after a cooldown period before relying on this module
in a fresh session. Everything else re-checked came back confirming the
existing coverage rather than finding a gap: CRA's full statistical-report
hub (canada.ca's "Income Statistics and GST/HST Statistics" page -- T1 Final
Statistics, ITSA, ITSTB, T1 filing compliance, TFSA, CCB, CWB, DTC, GST/HST
credit, T2 Corporate, Trust statistics, hard-to-reach-populations
participation) is entirely published on CKAN under `cra-arc`, spot-checked
live for "T2 Corporate Statistics" specifically.

Investigated 2026-09-20, then investigated again in more depth after an
initial pass under-scoped this row: CRA's tax-filer statistics (333 datasets
under the `cra-arc` organization -- T1/T2 filing compliance, GST/HST
statistics, Canada …

## Proactive Disclosure (government-wide)

**Status:** Shipped (via `ckan_*` + `ckan_datastore_search`).

Requested directly 2026-09-20. Government of Canada proactive-disclosure
publications (contracts over $10,000, travel and hospitality expenses,
grants and contributions, position reclassifications, departmental audit
committees, briefing notes, question period notes, acts of founded
wrongdoing, use of administrative aircraft) are published per-department as
~219 ordinary datasets on the federal CKAN catalogue -- confirmed live via
`ckan_search_datasets("proactive disclosure contracts")`.

The public-facing aggregator UI at `search.open.canada.ca/contracts/`
(linked from Canada.ca's own "Proactive disclosure" page) is a
server-rendered HTML search with no distinct JSON API behind it (confirmed
by inspecting its network requests: a search reissues the same page with
`?search_text=...` query parameters, no XHR call) -- not a source to build a
client against. Instead, most of the individual proactive-disclosure
datasets checked have **DataStore-active** resources (Contracts, Position
Reclassification, Hospitality Expenses, Travel Expenses, Grants and
Contributions, Departmental Audit Committees, Question Period Notes, Acts of
Founded Wrongdoing, Use of Administrative Aircraft, Briefing Note Titles,
Annual Travel/Hospitality Expenditures -- confirmed live across 11 of the
first 15 matches), so the new `ckan_datastore_search` tool (see the CRA row
above) already covers filtering these by department, vendor, amount, date,
or any other real column, not just downloading a per-department CSV.

Government of Canada proactive-disclosure publications (contracts over
$10,000, travel and hospitality expenses, grants and contributions, position
reclassifications, departmental audit committees, briefing …

## ISED (Innovation, Science and Economic Development Canada)

**Status:** Shipped.

Three modules, split like CMHC's dual-platform pattern
(`modules/ised/{corporations,spectrum,cipo}/`):

1. Corporations Canada's federal corporation lookup API
   (`ised_corporations_*`, 1 tool) -- a single-record lookup by numeric
   corporation id or 9-digit business number, confirmed live against
   `ised-isde.canada.ca/cc/lgcy/api/corporations/<id>.json` (the officially
   documented `www.ic.gc.ca` host now 301-redirects here). Two real quirks
   handled: an unmatched id/business number still answers HTTP 200 with a
   two-string-element error body instead of a 404, and the upstream's own
   address field is genuinely spelled `adresses`, not `addresses`. There is
   no documented search-by-name endpoint.
2. The Spectrum Management System's licence site data (`ised_spectrum_*`, 1
   tool) -- a single Esri-hosted ArcGIS FeatureServer with ~840,000 wireless
   spectrum licence records (licensee, service, frequencies, tower
   location/height, antenna specs), refreshed monthly, confirmed live; this
   reuses `shared/arcgis.py`'s existing generic `query_layer` function
   directly against one fixed known service url, with no Hub Search
   catalogue involved, since there is exactly one dataset here.
3. The Canadian Trademarks Database (CIPO)'s search API (`ised_cipo_*`, 1
   tool), added 2026-09-20 per a direct request to investigate CIPO:
   `ised_cipo_search_trademarks` searches over 2 million trademark records
   by owner name, mark text, goods/services text, application/registration
   number, Nice classification, or Vienna design code, confirmed live
   against `ised-isde.canada.ca/cipo/trademark-search/srch`.

This endpoint is not documented as a public API anywhere -- found by
intercepting the search UI's own `fetch`/`XHR` calls with an in-page hook,
not from any published spec -- but reproduces cleanly outside the browser as
a plain unauthenticated JSON POST (no session cookie, CSRF token, or API key
needed). Two real quirks confirmed live: `searchfield1` accepts only the
exact internal dropdown codes (`all`, `tm`, `ownname`, `wares`, `services`,
`appnum`, `regnum`, `intrnlRegNum`, `nice_for_search`, `viennaCode`, etc. --
any other value returns HTTP 500 with no detail body, not a 400); and there
is no pagination at all -- `start`, `startRow`, `offset`, `page`, and
`pageNum` were each tried live and silently ignored (identical response
every time), so `max_return` (capped at 500 here) only controls how many
top-ranked matches come back in one call, with results beyond that count
genuinely unreachable through this endpoint.

The full trademark register is separately also available as bulk "IP
Horizons" CSV/TXT exports -- confirmed live as the "Trademark Data" CKAN
dataset (`4bf74760-7ae7-4c83-ace8-b84a3b9aea8d`, 29 zipped resources hosted
on `opic-cipo.ca`, covering applications filed 1865-08-16 to 2023-08-16 as
of the 2024-08-20 refresh) under the same `ic` organization, alongside
sibling "Patent data" and "Industrial Design Data" datasets -- none of these
bulk exports are DataStore-active, so
`ckan_get_dataset`/`ckan_search_datasets` (already shipped) are the only
access path for them, exactly like ISED's other bulk statistical datasets
below; no new module needed for bulk download.

ISED's bulk statistical datasets (Financial Performance Data, historical
insolvency statistics, a bulk CSV export of the federal-corporations
register) are separately already ordinary CKAN datasets under the `ic`
organization (97 datasets, confirmed live), reachable via
`ckan_search_datasets(fq="organization:ic")` -- checked specifically for
DataStore-active resources during the deeper CRA-driven pass and found none
among them, so bulk download via `ckan_get_dataset` remains the only access
path for these particular ones, not `ckan_datastore_search`.

A further, related capability was investigated and found genuinely out of
scope: ISED's Office of the Superintendent of Bankruptcy runs a separate
*individual*-debtor Bankruptcy and Insolvency Records Search
(`ised-isde.canada.ca`) that requires an account and charges a minimum $8
per search -- confirmed live via its own documentation, not assumed -- a
paywalled, authentication-gated service this project will not automate (no
account creation, no payment).

ISED's free, open, *aggregate* insolvency statistics (monthly/annual
bankruptcy and receivership counts by NAICS industry or Forward Sortation
Area) remain covered above via the `ic` organization's CKAN datasets.
Re-checked 2026-09-21 per a direct "check again" request. Found and
confirmed one more account-gated capability, correctly out of scope for the
same reason as OSB above: ISED's own "Director information now available on
API store" article describes a *second*, separate access path for
Corporations Canada beyond the free `ised_corporations_*` endpoint already
shipped -- an actual list of a corporation's directors (names), reachable
only through the Government of Canada's "API Store," which requires "login
or create an account." Confirmed live the free unauthenticated endpoint
already shipped does NOT carry director names -- a real lookup against
corporation id 1007 returns `directorLimits` (a min/max count only, e.g.

`{"minimum": 3, "maximum": 30}`), not a director list -- so this is a
genuine, distinct capability, not already covered under a different name.
Also confirmed the "API Store" itself is dead: `cra-arc.api.canada.ca`,
`api.canada.ca`, and `dev.api.canada.ca` all fail DNS resolution outright
(see the CRA row above for the same dead-platform finding), consistent with
the "closed permanently ... September 29th, 2023" GC API Store shutdown
StatCan's own developers page documents -- so even setting the
account-creation exclusion aside, there is currently no live host to reach
for this capability regardless.

Three modules, split like CMHC's dual-platform pattern
(`modules/ised/{corporations,spectrum,cipo}/`): (1) Corporations Canada's
federal corporation lookup API (`ised_corporations_*`, 1 tool) -- a
single-record lookup by numeric …

## Government of Canada `open-data` GitHub org / `ckanext-canada` / `ckanext-recombinant`

**Status:** Investigated, no capability change.

Investigated 2026-09-20 per a direct request to check the federal open-data
GitHub presence for anything not already covered. `github.com/open-data`
hosts Canada's custom CKAN extensions, `ckanext-canada` and
`ckanext-recombinant`. `ckanext-canada` registers a
`canada_datastore_search` action that chains/overrides the stock
`datastore_search` specifically to enforce the 100,000-row full-text-search
cap this codebase had already discovered empirically and documented on the
CRA row above -- reading its source confirmed that limit is deliberate
upstream policy, not a bug this client needs to work around further.

`ckanext-recombinant` defines a
`recombinant_show`/`recombinant_package_show`/`recombinant_resource_show`/`recombinant_datastore_search`
family of actions for the ~19 standardized Proactive Disclosure table types
(`contracts`, `grants`, `travelq`, `travela`, `hospitalityq`,
`reclassification`, `wrongdoing`, `ati`, `briefingt`, `qpnotes`,
`inventory`, `consultations`, `service`, `dac`, `nap5`, `nap6`,
`experiment`, `adminaircraft`, `aistrategy`, and more).

These actions are genuinely registered and callable on the live
`open.canada.ca` API (confirmed via direct `POST` requests, not just reading
the source), but every (dataset_type, owner_org) combination tried returned
no match, and `package_search?fq=type:contracts` (querying by the
recombinant package type directly) returned 0 results -- confirming these
per-department recombinant-typed packages exist only on an internal,
non-public "Registry" system that feeds the public portal, not on
`open.canada.ca` itself.

No capability gap results from this: the Proactive Disclosure row above
already covers the same data (Contracts, Travel, Hospitality, Grants,
Reclassification, Wrongdoing, etc.) through the ordinary per-department CKAN
datasets and `ckan_datastore_search`, which is the only path that is
actually publicly reachable.

## OSFI (Office of the Superintendent of Financial Institutions)

**Status:** Shipped (via `ckan_*` + new `ckan_datastore_search`).

Investigated 2026-09-20, then investigated again in more depth alongside
CRA: OSFI's regulated-entity data (36 datasets under the `osfi-bsif`
organization -- "Banks", "Trust companies", "Loan companies", "Foreign bank
branches", "Life insurance companies", and more) is reachable via
`ckan_search_datasets(fq="organization:osfi-bsif")`, as first found; the
"Banks" dataset alone has 14 resources including a data dictionary and a
step-by-step API-usage guide.

The deeper pass confirmed live what that guide was actually pointing at:
several of these resources are genuinely **DataStore-active** and queryable
with the new `ckan_datastore_search` tool (see the CRA row above for what
that unlocked codebase-wide) -- confirmed live against the Banks dataset's
M4 Consolidated Balance Sheet resource, returning real regulatory-return
line items (calendar year/month, industry group, return title, data-point
address and label, measure value) filterable by any of those fields, not
just a downloadable CSV.

This is the "regulatory/balance-sheet statistics" this row originally called
for, now genuinely queryable rather than only bulk-downloadable. Re-checked
2026-09-21 per a direct "check again" request. Confirmed one thing correctly
stays out of scope: `osfi.beyond2020.com` ("Detailed Historical OSFI Data,"
insurance-company filings 2000-present in Beyond 20/20 format) is free but
requires self-registration/account creation, confirmed live by its own page
copy ("you must self register to gain access to the site") -- the same
account-creation exclusion already applied to the ISED/OSB
bankruptcy-records row below, and its own banner states it is being retired
("Effective June 10, 2026, this website will be retired," still live as of
this re-check).

Confirmed the "Who we regulate" register (~400 financial institutions
updated monthly, ~1,200 private pension plans updated daily, per OSFI's own
copy) is not a gap either: it is the `Who we regulate` package already among
the 36 `osfi-bsif` datasets counted above, confirmed live to carry four
DataStore-active CSV resources (financial institutions and private pension
plans, in both English and French) -- already reachable via the existing
`ckan_datastore_search`, nothing new needed.

OSFI's own "Modernizing how we collect data from institutions" page names a
forthcoming **Regulatory Data Hub (RDH)**, stated to go live "late fall
2026" (after this re-check) -- noted here as a future watch item, not yet a
live source to investigate.

Investigated 2026-09-20, then investigated again in more depth alongside
CRA: OSFI's regulated-entity data (36 datasets under the `osfi-bsif`
organization -- "Banks", "Trust companies", "Loan companies", "Foreign bank
branches", "Life …

## Transport Canada + CTA (Canadian Transportation Agency)

**Status:** Shipped (recalls).

Shipped 2026-09-23: `modules/tc_recalls/` (2 tools) on Transport Canada's
Motor Vehicle Safety Recalls Database API
(data.tc.gc.ca/v1.3/api/{eng,fra}/vehicle-recall-database): search by make,
model and model-year range, and a bilingual recall summary with affected
vehicles. Quirks: 25 rows by default, oldest first, with `limit` and 1-based
`page`; search columns are labelled in the request language, so rows are
read by position; no match is an empty ResultSet, not a 404.

Transport Canada's other data (NCDB collisions, aviation, rail) and the
CTA's are ordinary open.canada.ca datasets reachable through `ckan_*`
(portal="federal").

Shipped 2026-09-23: `modules/tc_recalls/` (2 tools) on Transport Canada's
Motor Vehicle Safety Recalls Database API
(data.tc.gc.ca/v1.3/api/{eng,fra}/vehicle-recall-database): search by make,
model and model-year range, and a bilingual …

## Government of Canada Recalls and Safety Alerts

**Status:** Shipped.

Shipped 2026-09-26: `modules/recalls/` with `recalls_search`,
`recalls_summarize` and `recalls_get`, covering recalls-rappels.canada.ca
(Health Canada drugs, natural health products, medical devices, consumer
products and cannabis; CFIA food; Transport Canada vehicle notices).
Health Canada's Drug Product Database stays out of scope.

Access paths checked live 2026-09-26:

- **Open-data dump (chosen).** The federal CKAN dataset "Recalls and
  Safety Alerts" (d38de914-c94c-429b-8ab1-8776c31643e3, `hc-sc`) links one
  JSON and one CSV file per language under
  recalls-rappels.canada.ca/sites/default/files/opendata-donneesouvertes/:
  `HCRSAMOpenData.json` (about 15.7 MB) and `SCRSAMDonneesOuvertes.json`
  (about 20.8 MB), not gzip-compressed, regenerated daily (Last-Modified
  around 02:19 UTC). Each holds the same 34,131 NIDs, 1991 to date,
  14,444 of them archived. English keys: NID, Title, URL, Organization,
  Product, Issue, "What you should do", Category, "Recall class",
  "Last updated", Archived; the French file uses Titre, Produit,
  Problème, "Ce que vous devriez faire", Catégorie, "Classe de rappel",
  "Dernière mise à jour", Archivé.
- **Recall pages.** `/{lang}/node/{nid}` answers 302 to the notice's page,
  404 for an unknown id. Current pages expose Drupal fields with the same
  class names in both languages (product, issue type, full category path,
  hazard type, recall date, distribution, companies, agency id such as
  the Transport Canada recall number, affected products table). Notices
  migrated from the old site use a legacy layout: a `<dl>` header and free
  HTML. A notice untranslated into French is served at /fr/ in English.
- **Not used.** The site's search (`/en/search/site`) is HTML and shows
  only non-archived notices: its total (19,690) and per-year facets match
  the dump's non-archived rows by "Last updated" year, so the dump is a
  superset. The old healthycanadians.gc.ca `recall-alert-rappel-avis/api/`
  JSON API still answers but stops at October 2021. The RSS feeds carry
  only the last few notices per feed. Older CFIA-only CKAN datasets
  (Class I recalls 2018-2021) are narrower and remain reachable through
  `ckan_*`.

Quirks handled: over 22,000 titles have leading or trailing spaces;
Product is null on 18,762 rows; Last updated is null on 2,717 Transport
Canada rows; "What you should do" is flattened HTML with `&nbsp;` and run-on
paragraphs; zero-width spaces in some titles; recall class is "" or "--"
when absent and can be a range ("Type I - Type II"); a few URLs point to
the other language's page. The dump's Organization is a publishing unit
(nine values, such as "Medical devices" or "Communications and Public
Affairs Branch"), so agency is derived from it. The dump has no top-level
product type, so `product_types` is derived from the unit and category
leaves; for non-archived notices it matched the site's facet counts
within 1% (vehicle 9,895 vs 9,889, health products 6,283 vs 6,285,
consumer products 2,256 vs 2,244, food 1,263 vs 1,272). Cannabis counts
as a consumer product, as on the site. Dates in search and counts are
last-updated dates; recall and first-published dates exist only on the
page.

## Elections Canada

**Status:** Shipped (via `ckan_*` + new `elections_financial_returns` module).

Investigated and shipped 2026-09-21. Elections Canada publishes 54 datasets
under the `elections` organization (`organization_autocomplete` confirmed
the real org slug is `elections`, not `elections-canada`) on the existing
federal CKAN catalogue, reachable via
`ckan_search_datasets(fq="organization:elections")` -- no dedicated module
needed for these, same pattern as CRTC/CRA/OSFI above. This already covers
poll-by-poll official voting results, turnout, electoral boundary files
(FED/polling division/advance polling district, 2003-2025), and bulk
donor-contribution exports back to 1993.

Confirmed live several of these have **DataStore-active** resources: the
42nd-44th general elections' "Official Voting Results" packages each expose
8-11 of their 13 tables (electors/turnout/valid-votes/riding-level
results/candidate lists/returning officers) as genuinely queryable rows via
the existing `ckan_datastore_search`, not just downloadable CSVs (confirmed
live against Table 11 "Voting results by electoral district" for the 44th
GE, 338 rows).

One real quirk: CKAN's DataStore truncates a field id at some length limit
when the source CSV header itself is bilingual and long, e.g. "Percentage of
Rejected Ballots /Pourcentage des bulletins rejet" -- a pre-existing
DataStore behavior, not something specific to this dataset. The donor-level
"Contribution to ... political entities" datasets are bulk-CSV-only
(`datastore_active: false` on every resource, confirmed live), so
`ckan_get_dataset` remains the only path for those, same as ISED's bulk
statistical exports.

Separately investigated Elections Canada's own Political Financing portal
(`www.elections.ca/WPAPPS/WPF/`) -- a distinct, non-CKAN platform not
discoverable from open.canada.ca at all -- which turned out to hold
something CKAN does not: each candidate's full official campaign financial
return (13 line-item statements: declaration, contributions received, loans,
expenses, transfers, bank reconciliation), not just the summary tables
above. New module `modules/elections_financial_returns/` (3 tools:
`list_elections`, `search_candidates`, `get_financial_return_part`), scoped
to the "Candidates" political entity only -- the portal's other four entity
types (leadership/nomination contestants, registered associations/parties)
use a visibly different search-form shape (confirmed live: selecting
"Registered parties" skips the election-period picker entirely and asks for
Annual/Quarterly/General-election-expenses returns instead), not mapped in
this pass.

This is a legacy, session-bound ASP.NET MVC app with no documented API,
reverse-engineered from live network-request inspection (both in-browser and
with a raw `curl` cookie jar, confirmed independent of any browser-specific
behavior): a candidate search POST and a "select candidates" POST together
produce a server-side `queryId`, which a `CC/Download?...&downloadFormat=3`
GET then resolves to genuine, well-formed JSON for any of the 13 report
parts -- confirmed live end-to-end for a real PEI candidate across three
parts (Declaration, Statement of Expenses with 193 real transaction rows,
Bank Reconciliation).

Four real quirks handled:

1. a bare POST with no prior GET on the exact same URL silently returns the
   empty search form rather than erroring -- this deployment needs a warm-up
   GET first to establish its session cookie, the same category of quirk
   already documented for `modules/statcan/reference/`;
2. the "select candidates" POST's 302 redirect carries the `queryId`, but
   the `Download` endpoint only serves data after that redirect's own
   `DetailedReport` target has been fetched with a GET at least once --
   confirmed live that skipping this step redirects `Download` back to the
   search form even with a struct-valid `queryId`;
3. the downloaded JSON's row-data key genuinely varies by part --
   `DETAIL_DATA` alone, `GROUP_DATA`+`DETAIL_DATA`+`TOTAL_DATA`, or
   `SUMMARY_DATA` plus two more arrays for the bank-reconciliation part --
   confirmed live across five parts, so the response schema keeps every
   list-valued key present rather than assuming one fixed shape;
4. `returnStatus=2` ("Data as amended") actually serves Elections Canada's
   own *reviewed* data, confirmed live by its `RETURN_STATUS` field reading
   `Data_as_reviewed_by_Elections_Canada` even for a candidate with no filed
   amendment -- not literally "has this candidate amended their return." The
   4 "Select Time Period" Canada Elections Act windows and the "Candidates"
   report-type list are hardcoded (fixed legislative/portal vocabulary,
   confirmed live), while the election/by-election list is discovered live
   via `list_elections` since new by-elections are added over time (a
   2026-04-13 by-election was already listed as upcoming when this was
   built).

Elections Canada publishes 54 datasets under the `elections` organization
(`organization_autocomplete` confirmed the real org slug is `elections`, not
`elections-canada`) on the existing federal CKAN …

## CanadaBuys (PSPC procurement)

**Status:** Shipped.

`modules/canadabuys/` (3 tools): `canadabuys_search_tenders` (open or
today's new tender notices, filter by keyword, category, region, buyer),
`canadabuys_search_awards` (award notices per fiscal year 2022-2023 onward,
filter by supplier, buyer, category), `canadabuys_get_notice` (full notice
by reference number). Built 2026-09-22 on the daily open-data CSVs under
`canadabuys.canada.ca/opendata/pub/` (listed as resources of the
open.canada.ca "CanadaBuys tender notices"/"award notices" packages, not
DataStore-active), downloaded and filtered in-process with a 4h cache.

Quirks confirmed live: UTF-8 BOM, bilingual `-eng`/`-fra` column pairs,
`*A`/`*B` multi-value cells, HTML in descriptions, `totalContractValue` of
`0.00` meaning not reported (returned as None), and the "open" file still
listing some tenders whose closing date has passed (sorted first by soonest
closing). Extended the same day with `canadabuys_search_contracts` (contract
history per fiscal year back to 2009-2010, plus the partial "2009-jan-Mar"
file; up to 113MB per year, so only needed columns are cached and past years
are kept 24h; one row per amendment upstream, merged here into one record
per contract with original amount, total value and amendment count) and
`canadabuys_list_bulk_files` (links, sizes and dates for the whole-history
and pre-CanadaBuys legacy files, 57MB to 833MB each, too large to query per
call).

Legacy (pre-2023) contract rows carry titles shaped "SUPPLIER
(reference~amendment)" and often lack award dates; amendments made in a
different fiscal year sit in that year's file, so an original amount can be
missing.

`modules/canadabuys/` (3 tools): `canadabuys_search_tenders` (open or
today's new tender notices, filter by keyword, category, region, buyer),
`canadabuys_search_awards` (award notices per fiscal year 2022-2023 onward,
filter by supplier …

## House of Commons (OpenParliament.ca)

**Status:** Shipped.

Shipped 2026-09-24: `modules/openparliament/` (7 `parliament_` tools) over
api.openparliament.ca, an unofficial JSON API by OpenParliament.ca/Open
North that re-publishes LEGISinfo, House votes, Hansard and committee
evidence (no official Parliament JSON API covers all four). Bill and MP
search filter locally because the API ignores `q` and matches `name=` only
exactly; list endpoints page at 500 via `next_url`; unknown objects answer
404 with an HTML page; debate paths drop leading zeros
(`/debates/2026/9/3/`).

Every response notes the source is unofficial. Added 2026-09-24:
`parliament_search_hansard`, full-text search over debates and committee
evidence, read from openparliament.ca/search (HTML, 15 hits per page)
because the JSON API ignores `q` on /speeches/.

Shipped 2026-09-24: `modules/openparliament/` (7 `parliament_` tools) over
api.openparliament.ca, an unofficial JSON API by OpenParliament.ca/Open
North that re-publishes LEGISinfo, House votes, Hansard and committee
evidence (no official …

## OpenParliament committees

**Status:** Shipped.

Shipped 2026-09-26 in the existing `modules/openparliament/` (no new
module): `parliament_list_committees`, `parliament_get_committee`,
`parliament_search_committee_meetings` and
`parliament_get_committee_meeting`, over the same api.openparliament.ca
JSON API, headers (`Accept: application/json`, `API-Version: v1`) and rate
limiter as the other `parliament_` tools.

Verified live 2026-09-26:

- `/committees/` returns the current session's 30 top-level committees
  by default (20 per page unless `limit` is set) and takes `session`.
  Subcommittees never appear in it, only in a committee's
  `subcommittees`. Committee data starts with session 39-1 (2006); an
  earlier or unknown session returns an empty list rather than 404, so
  the tool raises NotFound for it.
- `/committees/<slug>/` gives bilingual `name` and `short_name`,
  `parent_url`, `subcommittees` (paths) and `sessions` (session,
  House acronym such as FINA, ourcommons.ca `source_url`).
- `/committees/meetings/` filters on `committee` (slug or path),
  `session`, `date`, `date__gte`, `date__lte` and `in_camera`, newest
  first. It silently ignores `has_evidence` and `ordering`, and an
  unknown committee returns an empty list, so the tool checks the
  committee's detail page when a committee filter matches nothing. List
  rows carry no `session`; it is read from the meeting URL. Meetings on
  notice appear with future dates and `has_evidence` false.
- `/committees/<slug>/<session>/<number>/` adds start and end times and
  ourcommons.ca minutes, notice and webcast links (`webcast_url` null
  for in camera meetings). An unknown meeting returns 404 (HTML).
- A meeting's transcript is `/speeches/?document=<meeting path>`, in
  spoken order, typically 50 to 300 speeches; in camera meetings return
  none. An unknown document path returns HTTP 400 "Invalid meeting URL"
  as text/plain. `/speeches/` ignores `committee=`, and
  `document__startswith` returns 400, so there is no committee-wide
  speech search in the JSON API (full-text search over committee
  evidence stays with `parliament_search_hansard`).
- Witnesses have no `politician_url`. Their first attribution is
  "Name (Title, Organization)", later ones the bare name; the English
  form sometimes puts an honorific in the name ("National Chief ...")
  where the French form puts it in the role. House officers ("The Clerk
  of the Committee (...)", "Some hon. members") also lack
  `politician_url` and are excluded from the witness list.
- Committee studies exist only as HTML pages on openparliament.ca
  (`/committees/activities/<id>/`, 404 on the API host), so they are
  not exposed.

## Senate of Canada votes

**Status:** Shipped.

Shipped 2026-09-24: `modules/senate/` (2 tools) parsing sencanada.ca's vote
pages, since the Senate publishes no votes API: `senate_list_votes` (a
session's votes from 42-1 on, with totals, related bill and result; EN and
FR pages) and `senate_get_vote` (each senator's group, province and
Yea/Nay/Abstention, read from the column marked `data-order="aaa"`).
Per-vote totals are counted from the senator table and matched the list
page's totals when checked live.

Shipped 2026-09-24: `modules/senate/` (2 tools) parsing sencanada.ca's vote
pages, since the Senate publishes no votes API: `senate_list_votes` (a
session's votes from 42-1 on, with totals, related bill and result; EN and
FR pages) and …

## GC InfoBase (Treasury Board, government spending and results)

**Status:** Shipped.

Shipped 2026-09-23: `modules/gc_infobase/` (2 tools) over the official "GC
InfoBase - Open Datasets" package on open.canada.ca (52 bilingual CSVs:
Estimates, Public Accounts by vote/standard object/transfer payment, planned
and actual spending and FTEs by program, results indicators, federal
organizations). Files are addressed by resource id; `gc_infobase_query`
filters by organization substring, fiscal year (matched on start year across
the files' "2011-12"/"2020-2021"/"FY 2011-12" spellings) and exact column
values.

The InfoBase web app's GraphQL API was checked and not used: introspection
is disabled and its URL embeds the deployment hash. Downloads 302-redirect
to signed Azure blob URLs; `shared/csv_files.py` (now shared with `cer`)
follows https redirects.

Shipped 2026-09-23: `modules/gc_infobase/` (2 tools) over the official "GC
InfoBase - Open Datasets" package on open.canada.ca (52 bilingual CSVs:
Estimates, Public Accounts by vote/standard object/transfer payment, planned
and actual …

## Canada Gazette (regulatory notices)

**Status:** Shipped.

Shipped 2026-09-23: `modules/gazette/` (3 tools). Issues come from the
official RSS feeds (`/rss/p1-eng.xml`, 435 issues; `/rss/p2-eng.xml`, 232;
no Part III feed); `gazette_get_issue` parses an issue's index page into
notices with section, organization and act (Part I) or SOR/SI instruments
(Part II); `gazette_get_notice` extracts one notice's text, from its anchor
to the next anchored heading on Part I section pages, or the whole
instrument page for Part II.

English and French use the same paths with `-eng`/`-fra`.

Issues come from the official RSS feeds (`/rss/p1-eng.xml`, 435 issues;
`/rss/p2-eng.xml`, 232; no Part III feed); `gazette_get_issue` parses an
issue's index page into notices with …

## CIHI (Canadian Institute for Health Information)

**Status:** Shipped.

Shipped 2026-09-23: `modules/cihi/` (3 tools). CIHI retired Your Health
System and the Health Indicators Interactive Tool (the old URLs now redirect
to a "Modernizing how we deliver data" page) in favour of the Indicator
Library, whose interactive tables are embedded Qlik Sense (websocket engine,
not a usable API). Each of ~196 indicator pages links an XLSX data table in
English and French (~2 MB, via `<link hreflang>`), which this module parses
with openpyxl: `cihi_search_indicators` (crawls the library's 10 pages,
cached 7 days), `cihi_get_indicator` (description, data updated,
availability, frequency, topics), `cihi_get_indicator_data` (place substring
and exact column filters).

The all-indicators XLSX (~98 MB, at Excel's row limit) is not used. Adds the
`openpyxl` dependency.

CIHI retired Your Health System and the Health Indicators Interactive Tool
(the old URLs now redirect to a "Modernizing how we deliver data" page) in
favour of the Indicator Library, whose …

## NRCan energy use (Office of Energy Efficiency, National Energy Use Database)

**Status:** Shipped.

Shipped 2026-09-23: `modules/nrcan_energy_use/` (3 tools) over
oee.nrcan.gc.ca, which has no JSON API: product list (11 survey editions:
SHEU 2019/2015 and by CMA, multi-unit residential 2018, SCIEU
2019/2014/2009, arenas 2014, ICE 2000-2020, appliance shipments 2021; plus
51 Comprehensive Energy Use Database sector/jurisdiction menus discovered
from its list page), table listing per product, and any table parsed from
HTML in English or French (same `showTable.cfm` parameters under both
roots).

Quirks: HTML parsers decode `&sect` in `&sector=` to `§`; survey tables
follow each value with an A/M/U quality letter, captured with the legend in
`notes`.

Shipped 2026-09-23: `modules/nrcan_energy_use/` (3 tools) over
oee.nrcan.gc.ca, which has no JSON API: product list (11 survey editions:
SHEU 2019/2015 and by CMA, multi-unit residential 2018, SCIEU
2019/2014/2009, arenas 2014, ICE …

## NRCan geospatial (geo.ca geolocation, CanVec, geospatial catalogue)

**Status:** Shipped.

Shipped 2026-09-23: `modules/nrcan_geo/` (2 tools). `nrcan_geo_locate` uses
the Geolocator (geolocator.api.geo.ca; the old geogratis geolocation URL now
redirects and answers HTTP 500) for places, addresses, postal codes and
FSAs. `nrcan_geo_search_names` uses the Canadian Geographical Names Database
API (text, province, feature type, point radius, bbox) with feature-type
terms from its bilingual code list; malformed parameters answer a Tomcat
HTML 404, mapped to InvalidInput.

CanVec and other NRCan datasets remain reachable through `ckan_*`
(portal="federal"); NRCan energy-use data is `nrcan_energy_use_` (row
above).

## Earthquakes Canada (NRCan)

**Status:** Shipped.

Shipped 2026-09-24: `modules/earthquakes/` (1 tool, `earthquakes_search`) on
the FDSN event web service
(earthquakescanada.nrcan.gc.ca/fdsnws/event/1/query, `format=text`): date
range (default last 30 days, up to ~5 years), magnitude, point radius (km,
converted to degrees) or bbox, or one event by ID; newest first. Built from
the FDSN standard because the host was blocked from the build environment:
columns are read by header name, and no-match HTTP 204/404 is treated as
empty.

Still to confirm live: that NRCan honours `format=text`, the exact header,
and its no-data status.

Shipped 2026-09-24: `modules/earthquakes/` (1 tool, `earthquakes_search`) on
the FDSN event web service
(earthquakescanada.nrcan.gc.ca/fdsnws/event/1/query, `format=text`): date
range (default last 30 days, up to ~5 years), magnitude …

## DFO (Fisheries and Oceans Canada) tides and water levels

**Status:** Shipped.

Shipped 2026-09-23: `modules/dfo_iwls/` (3 tools) on the IWLS API
(api-iwls.dfo-mpo.gc.ca): station search over ~1,575 stations, station
detail with datum offsets, and `wlp-hilo`/`wlp`/`wlo` series. Quirks
confirmed live: windows are capped at 7 days (HTTP 400 beyond), `resolution`
accepts ONE_MINUTE/FIVE_MINUTES/FIFTEEN_MINUTES/SIXTY_MINUTES only, and
sending any resolution with `wlp-hilo` silently returns `[]`, so it is
dropped for that series. DFO's 920 other datasets stay on `ckan_*`
(portal="federal").

## Alberta Economic Dashboard

**Status:** Shipped.

Shipped 2026-09-23, reworked the same day around the dashboard's published
API: `modules/ab_economic/` (5 tools). `ab_economic_list_indicators` (49 key
indicators in 11 topics, update times, page URLs) and
`ab_economic_get_indicator_series` read each indicator page's "API Keys"
section, the Government of Alberta's published
`api.economicdata.alberta.ca/data?table=...` links, as named series with
table + filters; `ab_economic_get_data` fetches those rows (date range, most
recent N).

`ab_economic_list_tables`/`ab_economic_get_table_fields` cover the other
~260 tables through the chart-editor routes. Quirks: 45 of 49 indicator
pages use the kebab-case indicator name as their slug; `indicator-info`
misspells `indicaorName`; unfiltered tables reach ~13 MB, so rows are
trimmed client-side. English-only.

## StatCan public use microdata files (PUMFs)

**Status:** Shipped.

Shipped 2026-09-24: `statcan_pumf_` (5 tools): search, ZIP listings,
codebooks read by HTTP range request (LFS CSV, Stata, SPSS, SAS formats;
EN/FR) and `statcan_pumf_tabulate` (weighted totals, shares and means with
DuckDB, disk cache). Standard errors from each guide's documented method for
the 2021 Census (random groups, divisor 35; reproduces the guide's examples
exactly), EICS 2024 and CSWC 2024-2025 (1,000 bootstrap weights, divisor
1,000). SHS documents no PUMF variance method, so no SE.

See docs/pumf-beyond2020-scope.md.

## Census data tables 2006-2016 (Beyond 20/20)

**Status:** Shipped.

Checked 2026-09-25: StatCan has retired the 2011 Census tabulations (index
and downloads redirect to its page-not-found notice; 2011 NHS, 2006 and 2016
still work), so the tools point to the Borealis copies (27 datasets,
`borealis_search_ivt`); the theme crawl now runs 4 pages at a time with a
retry and skips (and names) a theme that never answers, after a parallel
burst made a 2006 search fail. Shipped 2026-09-24: `statcan_census_tables_`
(2 tools) over 869 tables (2016, 2011, 2011 NHS, 2006) with CSV, SDMX and
IVT links; IVT-only tables get a canivt (mountainMath) R snippet. 2021
tables are NDM tables via `wds_`.

Investigated 2026-09-25: outside StatCan, IVT files sit on Borealis (the
Canadian Dataverse): 3,347 .ivt files (~26 GB) in 108 datasets, 3,324
downloadable without a login, mostly StatCan data deposited by university
libraries (historical censuses 1665-1871, Census of Population 1996-2021
tabulations, Census of Agriculture 2001, Labour Force Historical Review
1997-2008, Canadian Business Patterns and Counts, justice surveys, HART
housing). Shipped `modules/borealis/` (`borealis_search_ivt`): dataset-title
search (file search does not index dataset titles), each dataset's .ivt
files, any CSV twin in the same dataset, and a canivt R snippet.

Open: Python IVT port only if demand appears.

Checked 2026-09-25: StatCan has retired the 2011 Census tabulations (index
and downloads redirect to its page-not-found notice; 2011 NHS, 2006 and 2016
still work), so the tools point to the Borealis copies (27 datasets …

## Cross-source planning and reproducible code

**Status:** Shipped.

Shipped 2026-09-24: `plan_query` (always visible; topic and place routing
across agencies) and `reproduce_code` (R, Python, Stata and Julia scripts
that fetch and clean the same data; cansim and canivt in R). Reworked
2026-09-25 after an audit of every tool found ~45 of 102 calls got no script
and ~35 got one that dropped the tool's filters, misread the format or sent
GET to a POST endpoint: the tool now runs once while `shared/http.py`
records its upstream requests (every parameter, POST body, Accept header),
the data request is replayed to find its format and rows, tools that filter
a downloaded file (CanadaBuys, CER, GC InfoBase, CIHI, IRCC, StatCan
indicators, IP Horizons patents) get the same filters in the script, and
scripts follow the house layout (header, numbered sections, packages in
setup).

Stata's JSON and filter steps run in its built-in Python, rewritten to
one-line statements because Stata 18 compiles `python:` blocks line by line.
Generated scripts were executed in R 4.5, Python and Stata 18; Julia is
generated but not run here. No script is returned, with the reason, for
browser-session forms (Elections Canada) and prose pages.

## CIPO patents via IP Horizons

**Status:** Shipped.

Shipped 2026-09-25: `modules/ised/ip_horizons/` (4 tools). Record queries:
`ised_ip_horizons_get_patent` (one patent with owners, inventors,
applicants, agents, optionally IPC classes) and
`ised_ip_horizons_search_patents` (party name and type, IPC
subclass/group/subgroup, title EN/FR, filing-date range; newest first with a
total count). They download only the tables and number ranges a query needs,
convert them to Parquet with DuckDB, and cache them
(`MAPLE_IP_HORIZONS_CACHE_DIR`, cap `MAPLE_IP_HORIZONS_CACHE_MAX_GB`,
default 3): main 65 MB and party 136 MB per upper-range file; the IPC upper
file unzips to 2.6 GB of CSV and becomes 67 MB of Parquet. opic-cipo.ca is
fetched over HTTP/1.1 because a large HTTP/2 download broke off mid-stream.

Every trademark link open.canada.ca lists answered 404 on 2026-09-25, but
CIPO's server holds a newer, unlisted 2024-11-20 release with all 19
trademark tables; `ised_ip_horizons_list_files` adds it
(`constants.UNLISTED_RELEASES`). We will not contact CIPO; the module
reads the unlisted release as long as CIPO serves it.
Catalogue tools: `ised_ip_horizons_list_files` (every bulk file of the three
packages, with table, patent-number range and release read from the download
URL, since CKAN names and formats are wrong for several files; newest
release per table by default) and `ised_ip_horizons_get_dictionary` (patent
and industrial design XLSX dictionaries; none exists for trademarks).
opic-cipo.ca omits its RapidSSL intermediate certificate, so the module
bundles it (expires 2027-11-02).

Checked 2026-09-24: IP Horizons (CIPO's quarterly researcher datasets for
patents, trademarks and industrial designs, CSV/TXT; weekly XML) is
published on open.canada.ca as "Patent data", "Trademark Data" and
"Industrial Design Data", so `ckan_*` (portal="federal") already finds and
downloads it, and `plan_query` routes IP questions there. Open: abstracts,
claims and disclosures (full text, several GB) are not queryable; industrial
design records are listed but not queryable.

IP Horizons does not cover PMPRB or Business Number validation (separate
rows).

Record queries: `ised_ip_horizons_get_patent` (one patent with owners,
inventors, applicants, agents, optionally IPC classes) and
`ised_ip_horizons_search_patents` (party name and …

## Clean Technology Data Strategy (NRCan, ISED, StatCan; Clean Growth Hub)

**Status:** Partly covered.

Checked 2026-09-24: its statistics are StatCan's Environmental and Clean
Technology Products Economic Account (tables 36-10-0366, -0370, -0371,
-0372, -0411, -0627 and more, via `wds_`) plus open.canada.ca datasets on
clean-technology use and adoption (via `ckan_*`); `plan_query` has a
clean-technology topic. Investigated 2026-09-25, no adaptor needed: every
CTDS dashboard on the Clean Growth Hub embeds a StatCan data visualization
over tables `wds_` already reaches (e.g. 36-10-0632, -0645, -0681); federal
clean-technology investment 2016-2024 (57 programs, 22 organizations) is
published only as an HTML summary and a PDF infographic, so
`ised/clean_growth` (`ised_clean_growth_get_federal_investment`, shipped
2026-09-25) reads that page's three tables and headline prose into numbers
(EN/FR) and points to the proactive-disclosure grants and contributions
DataStore (1.3 million records) the projects were identified from; the
closest machine-readable data is TBS's Horizontal Innovation and Clean
Technology Review tables (2007-2016 CSVs on open.canada.ca, via `ckan_*`);
NRCan's cleantech-companies page is one small HTML table (2,470 companies by
industry and province, June 2025) plus Power BI, and the 2025 Cleantech
Industry Survey is a PDF plus Power BI.

Program-level investment data is not published; we will not request it.

Checked 2026-09-24: its statistics are StatCan's Environmental and Clean
Technology Products Economic Account (tables 36-10-0366, -0370, -0371,
-0372, -0411, -0627 and more, via `wds_`) plus open.canada.ca datasets on
clean-technology use …

## Competition Bureau Canada

**Status:** Shipped.

Shipped 2026-09-25: `modules/competition_bureau/`
(`competition_bureau_search_mergers`) over both merger-review reports (2,554
reviews). Checked 2026-09-25: the merger-review reports are full HTML tables
(about 830 reviews since Nov 2023, weekly; about 1,725 from 2015-2023) with
parties, dates, NAICS and outcome; the Tribunal's decisions site refuses
automated requests, and enforcement and market studies are PDFs.
[Details](docs/findings/competition-bureau.md)

## CAPP Statistics Handbook (Canadian Association of Petroleum Producers)

**Status:** Investigated, deferred.

Checked 2026-09-25: 76 Excel tables (reserves, production by field, value of
producer sales from 1947, expenditures, demand), updated each December;
industry copyright, use allowed with attribution. See
`docs/findings/capp-statistics-handbook.md`.

## Office of the Commissioner of Lobbying (Registry of Lobbyists)

**Status:** Blocked.

Checked 2026-09-25. Two datasets under `ocl-cal` on the federal CKAN
catalogue, both updated weekly (licence `ca-odla-aldg`, the
Commissioner's own open data licence agreement, not the OGL): "Lobbying
Registrations" and "Monthly Communication Reports". Each is one bilingual
zip of CSVs plus an XLSX data dictionary. Neither is DataStore-active.

The zips live on lobbycanada.gc.ca, which answers HTTP 403 with a
Cloudflare challenge page to automated requests (with or without a browser
user agent), and so does the guest search of the registry. The catalogue
metadata is reachable through `ckan_*`, but the data files are not.
Revisit if the files move to open.canada.ca storage or the challenge is
lifted.

## Job Bank labour market information (ESDC)

**Status:** Covered (via `ckan_*`).

Checked 2026-09-25. Three ESDC datasets on the federal CKAN catalogue:

- **Wages** (`adad580f-...`): one CSV per year, 2018 to 2025, all
  DataStore-active. The 2025 file has 44,376 rows: NOC 2021 occupation by
  province and economic region, with low, quartile, median, average and
  high wages, data source, reference period, annual-wage flag and share
  of employees with non-wage benefits. Wages are strings in the
  DataStore.
- **Job Postings Advertised on Canada's National Job Bank Website**
  (`ea639e28-...`): monthly CSVs (English and French), 88 resources;
  English months are DataStore-active only sometimes (August and June
  2026 yes, July and May no). August 2026 has 53,799 postings with NOC,
  NAICS, location, vacancy count, salary range, hours and benefit flags.
- **3-Year Employment Outlooks** (`b0e112e9-...`): 28 CSV/XLSX files, from
  2013-2015 to 2025-2027 (NOC 2021), none DataStore-active.

`ckan_datastore_search` already queries Wages and the active posting
months; the rest are bulk downloads via `ckan_get_dataset`. A dedicated
module would add little beyond typed wage columns and picking the
DataStore-active month, so none was built.

## IRCC monthly updates (permanent and temporary residents, asylum)

**Status:** Shipped.

Checked 2026-09-25 and shipped 2026-09-26 as `modules/ircc/monthly/`
(`ircc_monthly_list_tables`, `ircc_monthly_describe_table`,
`ircc_monthly_query`).

IRCC publishes 12 "Monthly IRCC Updates" datasets on the federal CKAN
catalogue. Their organization is `cic`, not `ircc`: `organization:ircc`
matches nothing, and the server's routing hints said `ircc` until this
check. The 12 datasets list 96 CSV resources, 67 of them in current
(non-archived) datasets: permanent residents, French-speaking permanent
residents, Express Entry admissions and invited candidates, study
permit holders (including by designated learning institution), TFWP,
IMP and post-graduation work permit holders, temporary-to-permanent
transitions, asylum claimants, and the archived Syrian, Afghan and
resettled refugee series. None is DataStore-active.

The files are served from
`www.ircc.canada.ca/opendata-donneesouvertes/data/ODP-*.csv` without a
challenge. What all 96 turned out to need:

- 94 are tab-separated despite the extension; two archived files
  (`ODP-Afghan-AgeGroup`, `ODP-Syrian_Refugees-Admissions-SkillLevel`)
  are comma-separated and repeat every column as `Copy of <name>`.
- Long format: time columns (`EN_YEAR`, `EN_QUARTER`, `EN_MONTH` as
  `Jan`...`Dec`), then dimensions as English/French column pairs, then
  `TOTAL`. Express Entry candidate tables and secondary-migration
  asylum data are yearly only; the archived refugee tables have no time
  at all; asylum by office type has a month but no quarter. In the
  study permit DLI files `TOTAL` comes right after the time columns and
  the institution-name column has no French pair (one header spells it
  `INSTITUION`).
- Monthly coverage is January 2015 to July 2026 on the day checked.
  Rows are not in time order.
- Counts are rounded to multiples of 5; `--` marks a suppressed count
  (1 to 4). No file has an aggregate "Total" row, so summing does not
  double count.
- `ODP-PR-FRE_SP_IMMCAT.csv` has no header row at all; the tool reports
  it as unreadable instead of guessing column names.
- The largest files are about 30 MB (`ODP-PR-PT_NOC4`, 181,340 rows;
  `ODP-TR-Work-IMP-PT_NOC4`, 159,335 rows).

Reconciliation: summing `ODP-PR-PT_IMMCAT` over all provinces and
categories gives 470,745 permanent residents for 2023 and 482,570 for
2024, against IRCC's published 471,771 and 483,640 (within 0.3%; the
gap is rounding and suppression). The live smoke test checks the 2024
figure.

What was built: a catalogue read live from open.canada.ca (cached a
day), a describe tool listing each table's dimension keys, values and
first and last period, and a query tool that filters by dimension
(English or French values), bounds years, and sums to month, quarter or
year over the dimensions kept in `group_by`, reporting how many
suppressed cells each total contains. `reproduce_code` rebuilds the
file download and filters and notes that the tool's summing is not
repeated in the script.

## CRA individual tax statistics and benefit statistics

**Status:** Covered (via `ckan_*`).

Checked 2026-09-25. Individual Income Tax Return Statistics (formerly T1
Final Statistics) appear as one dataset per tax year, 2011 to 2022, each
with 7 to 143 resources: per-table CSVs (general statement by province,
returns by income class, age and sex) plus PDFs and explanatory notes.
File names and table numbering change between editions (`t01ca.csv`,
`table1.csv`, `tbl1_ac.csv`), so a cross-year series needs a lookup table
per edition. CRA also publishes benefit statistics by forward sortation
area (Canada Child Benefit by benefit year, Canada Carbon Rebate
recipients). None is DataStore-active; `ckan_get_dataset` gives the
files. A dedicated module would only be worth it to harmonize T1 tables
across editions.

## Parliamentary Budget Officer

**Status:** Shipped.

Checked 2026-09-25 and 2026-09-26; shipped 2026-09-26 as `modules/pbo/`
(`pbo_search_publications`, `pbo_get_publication`).

There is no data portal (`/en/data` is 404), but the website reads a
public JSON API at `https://99bank.pbo-dpb.ca/distribution/1/` (also
served as `rest-393962616e6b.pbo-dpb.ca`), found in the site's scripts:

- `/publications`: 863 publications, newest first, a fixed 15 per page
  (`per_page` and `limit` are ignored), Laravel `meta` with `total` and
  `last_page`. `types=ES,NT` filters by type code, `tags=<id>` by tag.
  Types seen: RP report, NT note, LEG legislative costing note (185),
  ES cost estimate, OA additional analysis, LIBARC archived (2008-2021).
- `/publications/<id>`: the full record, with bilingual titles and
  abstract, the website link, the PDF (`artifacts.main.<lang>.public`)
  and `pboml_document`, a base64 YAML data URL in PBO's own markup
  (PBOML 1.0.0).
- `/search?query=`: a list of `{type, score, payload}` across content
  types; the module keeps `Publication` ones.
- `/tags` (153 series and topics), `/news-releases` (93) and
  `/information-requests` (1,121 requests PBO sent to departments, with
  dates, status and summaries; not exposed yet).

PBOML slices are `heading`, `markdown`, `svg` (charts, no data), `table`
(`variables` maps column ids to bilingual labels; `content` rows hold
numbers or `{en, fr}` text), `html` (a table per language, used by the
Economic and Fiscal Outlook) and `kvlist` (key/value lists; `print_only`
ones are author credits and are skipped). Of 42 sampled publications, 21
had tables: legislative costing notes since 2021 and most reports since
2025. Archived and pre-2021 reports have no PBOML and return only their
PDF link.

Checked values: RP-2627-002-S (Economic and Fiscal Outlook 2026) gives
real GDP growth of 1.7% for 2025 and 1.1% for 2026 in its first table;
ES-2627-002-M (motion M-24) gives the proposed bracket rates of 34%,
35% and 36% above $500,000.

Terms: PBO materials may be used and reproduced for personal and
non-commercial use without permission, unaltered and with attribution;
commercial use needs permission. The tools pass tables through as
published and say so in their provenance.

The interactive tools (Federal Employment Tracking Tool and others) load
static JSON with build-hashed names; they are not covered.

## StatCan terms: SDMX, CORD, NDM

**Status:** Reference note.

Also clarified per a direct question ("SDMX, CORD, NDM") what three
recurring terms actually refer to, since all three appear throughout this
project's StatCan work without ever being named directly: SDMX (Statistical
Data and Metadata eXchange) is the ISO standard protocol already fully
covered by both `modules/statcan/sdmx` (generic tables, XML) and
`modules/statcan/census_profile` (2021 census, JSON) -- no separate coverage
needed. CODR (Common Output Data Repository, confirmed via the DGUID
reference document's own text) is StatCan's internal name for the data
warehouse behind ordinary tables -- WDS/SDMX are already the public
interface to it, not a separate API. "NDM" is the CSS/module namespace
(`ndm-results`, `ndm-item`, `block-ndm-plugins`, `ndm-surveys-az`) seen
across every Reference/Analysis/Data/surveys page built against this pass.

Investigated further per a follow-up request ("NDM, investigate more"):
StatCan's own public consultation pages from 2013-2014 use the URL slug
pattern `ndm-nmd-*` (French `nmd-ndm-*`), explicitly titled "New
Dissemination Model" (e.g.
`statcan.gc.ca/en/consultation/2013/ndm-nmd-nt-eng` "New Dissemination Model
– Navigation and Tables"), and the methodology publication "Statistics:
Power from Data!" (catalogue 11-634-X, chapter 4.1, "Disseminating data
through the website") independently corroborates this in prose, describing a
2012-2015 initiative to build "a new, single, mandatory output database ...
that provides a common and consistent interface for all data products" and
to modernize website navigation, taxonomy, and table structure -- exactly
the surface (catalogue/navigation pages, not the data warehouse itself)
where the `ndm-*` CSS classes appear.

This is a credible, StatCan-sourced expansion (New Dissemination Model) for
the namespace, though not a direct confirmation that today's Drupal 10
classes are literally named after that specific 2012-era project rather than
reusing its name by convention. A separate, weaker usage exists in
third-party packages (`cansim`, `statcanR`), which informally gloss "NDM" as
"New Data Model" when referring to the post-2018 CANSIM-replacement
table-numbering scheme (e.g.

`17-10-0016-01`) -- a StatCan-unconfirmed community inference about the
table-ID system, distinct from the website CSS namespace, and not conflated
with it here. Investigated a fifth time per a direct question ("catalogues,
PDFs, articles, documentation, all that?"): confirmed every
Reference/Analysis search result's catalogue number resolves to a real,
plain (no session-cookie quirk needed) detail page at
`n1/en/catalogue/{number}` listing that document's actual downloadable files
-- HTML and PDF, each a direct link, confirmed live.

Added `statcan_reference_get_document_formats` to the same module. One real
quirk found and handled: a series-level catalogue number's page (e.g.
"16-511-X") has no formats of its own -- it instead lists that series'
editions, each with its own catalogue number -- and the two page shapes are
structurally identical (same link+date row layout), distinguished only by
the table's own header text ("Format" vs "Titles"/"Titres"); an earlier
version of this parser that assumed every such table was a formats table
silently mislabelled 8 edition titles as "formats" for "16-511-X" before
this was caught via the live smoke test and fixed.

A second quirk: catalogue-number normalization is itself inconsistent --
"16-511-X" resolves with its dashes intact, but "46-28-0001202600100004"
only resolves with dashes/spaces stripped (confirmed live, both directions)
-- so the tool tries the number exactly as given first, then stripped,
before raising NotFound. Investigated a sixth time per a direct request to
check for PUMF (Public Use Microdata Files) access. Confirmed live that PUMF
data files themselves are directly downloadable with no authentication at
all: a real Census PUMF ZIP
(`n1/pub/98m0001x/2023001/cen21_ind_98m0001x_part_rec21.zip`, ~173 MB)
answers HTTP 200 with `Content-Type: application/zip` on a bare
unauthenticated request.

The open question was discoverability, not access. Reference resources only
indexes PUMF *user-guide* documentation (category "Surveys and statistical
programs – Documentation"), not the PUMF products themselves; the actual
product listings (category "Public use microdata") turned out to live in a
third catalogue on the same Drupal engine, "Data" (`n1/en/type/data`, French
`n1/fr/type/donnees`, both confirmed live, 13,342+ items) -- identical
structure and quirks to Reference/Analysis, so `CATALOGUE_CONFIG` was
extended with a third entry and a `statcan_reference_search_data` tool added
at effectively zero new parsing code, the same generalization pattern used
for Analysis.

Confirmed live: searching "Public Use Microdata Files" there returns 144
results, including real PUMF catalogue numbers (71M0001X for the Labour
Force Survey, 98M0001X for the Census) alongside ordinary table PIDs already
reachable via WDS/SDMX. A PUMF's own catalogue-number page (via the existing
`get_document_formats`) resolves one HTML link, which itself leads one hop
further to a bespoke, per-product static page (e.g.
`n1/pub/98m0001x/index-eng.htm`, listing every Census PUMF edition from
1991-2021) that is a genuinely different page shape from the Drupal engine
-- not parsed generically here, left as a link for the caller to follow, the
same design choice already used for the editions case.

Investigated a seventh time with a final "leave nothing out" exhaustiveness
pass: re-checked StatCan's GitHub org (205 repos, internal platform tooling,
nothing exposing a new public API), Trade Data Online (confirmed an ISED
product built on StatCan source data, not StatCan's own; StatCan's own
equivalent, Canadian International Merchandise Trade, has no live API
either), the Postal Code Conversion File (confirmed licensed/restricted, no
free programmatic access), My StatCan (confirmed a pure email-subscription
layer over The Daily, no separate API), the Business Register (confirmed
confidential under the Statistics Act, aggregate-only), and Research Data
Centres/Real Time Remote Access (confirmed security-screened microdata-lab
access, no API) -- all correctly out of scope, nothing new.

One genuine new surface was found: `geo.statcan.gc.ca/geo_wa/rest/services`,
a live Esri ArcGIS REST (Map/Feature Service) census-geography API -- the
first genuinely queryable (attribute- and spatially-filterable) StatCan
geography service in this codebase, distinct from every static bulk
boundary-file download already covered. Confirmed live: top-level folders
are years 2019-2025 (nothing older is served here); a census year (2021
confirmed) publishes a full suite of ~10 services (Cartographic/Digital
boundary files, Agricultural/Population ecumene boundary files, Road Network
File, each in English and French), each service one MapServer with one layer
per geography level (15 layers confirmed for 2021's Cartographic boundary
files: PR/CD/CSD/CMA/ER/FED/CCS/PC/DPL/ADA/CT/DA/DB/FSA/CAR); an intercensal
year publishes a much smaller set (CSD-level updates and the Road Network
File only, confirmed for 2019-2020, 2022-2025) -- this genuinely varies year
to year and is not hardcoded.

New module `modules/statcan/geo/` (3 tools: list_services, get_layer_detail,
query_layer) and a new shared adaptor `shared/arcgis.py` (this is the first
ArcGIS REST-platform source in this codebase; `shared/wfs.py` covers OGC WFS
2.0 instead, a different protocol used by NRCan's NBAC). Two real quirks
handled, both confirmed live:

1. every error -- an unknown year/service/layer, a malformed `where` clause
   -- comes back as HTTP 200 with a JSON `{"error": {"code", "message"}}`
   body, not a non-2xx status, so `shared/arcgis.py` inspects the decoded
   body on every call rather than relying on `raise_for_status()`;
2. this specific host is intermittently unreliable at the node level --
   roughly one in three to five otherwise-identical requests to the exact
   same URL returns a genuine transient HTTP 500 ("Application Error" or
   "This web adaptor is not configured with an ArcGIS Enterprise
   component"), reproduced repeatedly by simply retrying the same URL
   seconds later, consistent with a load-balanced backend where some nodes
   are unhealthy -- `shared/http.py`'s existing 3-attempt
   exponential-backoff retry (already used by every module) is sufficient
   mitigation and no second retry layer was added.

`query_layer` reprojects geometry from the service's native EPSG:3347
(Statistics Canada Lambert) to WGS84 lat/lon (EPSG:4326) by default when
geometry is requested (off by default -- polygon boundaries can be large),
and surfaces each layer's own `maxRecordCount` cap (6000 confirmed for
2021's Cartographic boundary layers) via an `exceeded_transfer_limit` flag
so a caller knows to page with `result_offset` rather than assuming a query
returned everything.

Investigated an eighth and final time per an explicit "last round" request,
closing the exhaustive multi-pass StatCan audit. Checked and confirmed
correctly out of scope: GeoSearch's National Address Register API is dead
(StatCan's own developers page states the GC API Store it depended on
"closed permanently at 12:00 EDT on September 29th, 2023," leaving NAR as a
static per-province PUMF CSV, catalogue 46-26-0002, not a live
address-to-DGUID lookup); StatCan's website chatbot is an in-house 2026
Census FAQ tool with no data API; legacy CANSIM table/vector IDs are already
fully covered by WDS's own `cansimId` field on cube metadata (the static
concordance CSV at `statcan.gc.ca/en/developers/concordance` is a one-time
June 2018 snapshot of the same mapping, not a new capability); a final
developers-hub and Departmental Plan sweep surfaced nothing not already
shipped.

One genuine new surface was found and shipped: StatCan's own SDG Data Hub
(`www144.statcan.gc.ca/sdg-odd/`) links to two separate "Open SDG" platform
sites -- the Canadian Indicator Framework (86 indicators) and the Global
Indicator Framework (251 indicators, Canada's reporting against the UN's own
indicator set) -- each a static site hosted on GitHub Pages, not a
StatCan-run API host. Confirmed live that both sites embed their real data
API base URL directly in their own page JavaScript
(`opensdg.remoteDataBaseUrl`) rather than publishing it as documentation,
resolving to a shared third GitHub Pages host
(`sdg-data-canada-odd-donnees.github.io`) under two different repo-path
prefixes; a discovery index at `{base}/{lang}/meta/all.json` lists every
indicator's metadata, `{base}/{lang}/meta/{code}.json` and
`{base}/{lang}/data/{code}.json` resolve one indicator's metadata and
observations respectively, all free and unauthenticated.

New module `modules/statcan/sdg/` (3 tools: search_indicators,
get_indicator_metadata, get_indicator_data). One real quirk handled: the two
frameworks use genuinely different metadata field names for the same
concepts, confirmed live -- the Canadian framework's
`sdg_goal`/`national_indicator_description`/`published` versus the Global
framework's `SDG_GOAL`/`STAT_CONC_DEF` with no `published` field at all --
normalized to the fields both frameworks share (`goal_number`,
`target_number`, `indicator_name`, `reporting_status`) plus a description
that tries the Canadian field name first, then the Global one.

Errors here are standard HTTP 404s (a plain static-file host), unlike every
other quirky embedded-error StatCan API in this module. With this addition,
StatCan's public programmatic surface is considered exhaustively covered by
this project. Investigated a ninth time, specifically to check whether other
StatCan thematic "hub" microsites follow the same pattern the SDG Data Hub
turned out to (a presentation layer over a genuinely separate,
freely-accessible backing data API): checked the Quality of Life
Hub/Framework, the Gender, Diversity and Inclusion Statistics Hub, the CPI
Inflation/Personal Inflation Calculator, and several housing dashboards
(Census Program Data Viewer, Rural Canada Housing Profiles, New Housing
Price Index dashboard).

All of these embed either a Power BI report (`dv-vd.cloud.statcan.ca`,
requiring a session-scoped Azure AD token issued server-side, not something
an external client can legitimately call) or an R Shiny application
(`dv-vd.shinyapps.io`, a stateful websocket-driven reactive session,
confirmed live via its shiny-server-client/sockjs assets) -- StatCan's
standard internal presentation layer over WDS-sourced tables (the Inflation
Calculator's math almost certainly runs against CPI table 18-10-0004-01,
already covered), not a new data-access route.

Unlike the SDG hub's Open SDG GitHub Pages platform, none of these expose a
discoverable public REST/JSON surface -- confirmed no new capability. |
