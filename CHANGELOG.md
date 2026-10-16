# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [semantic versioning](https://semver.org/) while it is in beta.

## [Unreleased]

### Removed

- `statcan/census_tables` (`statcan_census_tables_*`) and `statcan/census_profile_2016`
  (`statcan_census_profile_2016_*`): Statistics Canada's www12 host answers automated
  clients with a bot challenge, 503 errors or timeouts. The 2021 profile, the archive
  download links and WDS tables 17100122 and 17100123 (2016 indicators down to health
  regions) remain. The matching `reproduce_code` builder, planner steps and smoke tests
  went with them.

### Added

- `plan_query`: a `statcan_tables` topic for whole tables, bulk series and vector IDs. It is
  chosen by words such as "full table", a CSV or a vector near "StatCan", and "reconcile"
  near a workbook of vectors, or by a table number like 36-10-0222 or a vector ID like
  v41690973, and starts with `wds_get_full_table_download`. A question
  about reconciling a workbook of vector IDs against a published table used to get only
  provincial portals.
- `cra_charities` module: search CRA's annual List of charities by name, city, province
  or designation, look one up by business number, and list its directors and officers
  (open.canada.ca DataStore, Open Government Licence - Canada).

### Changed

- CI: a new `Docker images` workflow builds the server and chat images and checks that the
  server image starts and answers `/health`. Render deploys from those Dockerfiles, and no
  workflow built them before. CI also runs the chat demo's lint and tests (`chat/`).
- `search_tools` answers are about 38% smaller (a compact answer is 12 to 20 KB, by query): the
  Provenance schema that every tool's result carries is shown once as a short description
  instead of five full copies. Input schemas and the tools' own result schemas are unchanged.
- The server instructions and the docstrings of the WDS vector tools now say that vectors come
  back inline and suit a handful of series, and point to `wds_get_full_table_download` (a CSV
  link with a `VECTOR` column) for a whole table or hundreds of series.
- Discovery: `search_tools` now puts `wds_search_cubes` first for "consumer price index monthly"
  and "population estimates by province" (they led with a real-estate index and PUMF
  tabulation), and `bcgw_get_active_wildfires` ahead of the BC air-quality tool for
  "wildfires British Columbia". Docstring keywords only; the three cases are in
  `tests/test_english_discovery.py`.
- `search_tools` keeps the Provenance definition when another field still refers to it, instead
  of leaving a dangling `$ref`. The compact-answer test now compares sizes against the same
  tools' full schemas over several queries rather than a fixed byte limit.

### Fixed

- `plan_query`: the `statcan_tables` topic no longer fires on the disease or map sense of
  "vector". "Vector" and "vecteur" count only within 60 characters of a word that places them
  in a table (table, series, StatCan, CANSIM, workbook, ID, a v-number), so "tick vectors",
  "maladies transmises par les vecteurs" and "vector GIS data" get the usual `search_tools`
  fallback instead of a plan for StatCan vectors; "vector-borne", "vector control", "maladies
  à vecteur", "vector data", "vector file", "vector layer" and "vector map" never count.
- `plan_query`: "reconcile" and "rapprochement" count only within 60 characters of a vector, a
  workbook or a published table, so "reconciliation with First Nations: table of land claims"
  and "le rapprochement des partis selon les séries de sondages" no longer pick
  `statcan_tables`; "truth and reconciliation" and "bank reconciliation" never count.
- `plan_query`: "CSV", "bulk download", "bulk data" and "téléchargement en bloc" count only
  within 60 characters of a word that names StatCan (StatCan, Statistics Canada, CANSIM, WDS,
  a cube, a vector), so "CSV download of Toronto building permits" and "bulk data on Calgary
  property assessments" no longer get a plan for StatCan tables.
- `plan_query`: a table number must be a real StatCan one (subject 10 to 46 or 98, product
  type 10, sequence not a year), so dates such as 15-01-2024 or 10-10-2023 no longer match.
  New cues: a vector ID on its own ("v41690973", which also puts `wds_get_series_info` first),
  a bare productId next to the word "table" ("table 14100287", "table 3610022201"), and the
  French plurals "tableaux complets" and "télécharger les tableaux". `matched_terms` names the
  cue word ("reconcile"), not the whole stretch of the question around it, and the full-table
  step says that `product_id` is the table number.
- Discovery in French: "estimations de population par province" now starts with
  `wds_search_cubes`, as its English twin already did. The PUMF tabulation tool's French
  keywords still said "estimation de population"; they now say "total pondéré", matching the
  English "weighted total".
- Chat demo: the page can no longer be framed by another site (`frame-ancestors 'none'`,
  `X-Frame-Options: DENY`), and a `?q=` link sends its question by itself only when it comes
  from the website; from anywhere else it fills the box and waits for a click. Each question
  is a billed model call, so a page that embedded or linked the demo could otherwise spend
  its daily limit through its own visitors' browsers. A question that fails is put back in
  the box, so trying again does not mean retyping it.
- Chat demo image: `chat/Dockerfile` installs from `chat/uv.lock` with `--locked`, as the
  server's image does, instead of resolving the newest versions at build time.
- Chat demo: a request that fails after a billed model call stays counted against the
  hourly and daily limits (only a failure before any call is refunded), and the failure
  log names the HTTP status.
- Logs: failed resource reads and prompt renders no longer log their arguments or
  tracebacks, as failed tool calls already did not.
- `reproduce_workbook`: the attribution line names the licence's own jurisdiction
  (Yukon, Newfoundland and Labrador, Northwest Territories and others), not only
  Canada, Alberta, British Columbia and Ontario.
- `reproduce_code`: a request body that is neither JSON nor form fields now gives no
  script, with a note, instead of a script that silently drops the body; a missing
  response field is an upstream error, not invalid input.
- `cra_charities`: each tool uses the newest list that has the table it reads, business
  numbers accept ASCII digits only, and a truncated directors list says so.
- Smoke scripts: an upstream outage skips only the checks after it, so earlier failures
  still fail the run.

## [0.3.0] - 2026-10-10

### Added

- Issue reporting: a `docs://report-issue` resource and server instructions
  for drafting a bug report when a tool misbehaves. The client shows the final
  text and files it only after the user approves that exact text.
- Prompts follow `lang`, with French bodies, and the eight `docs://` resources
  have French twins.
- Planner: a taxation topic (CRA T1, TFSA, GST/HST, charities) and routes for
  bc_environment, eccc_datamart, health_products and oeb.
- Earthquakes: each result carries a `lookup_id` (the UTC minute the service
  accepts as `eventid`).
- Website: "See it in action" section linking a chat demo, and Claude and
  ChatGPT custom-connector steps on the Connect page.
- Website: touch icon, favicon fallback and web manifest; sitemap `lastmod`.
- Website: a privacy page. Server error logs keep only the exception type, not
  tool arguments or error text.
- Security policy, code of conduct and this changelog. Dependabot keeps the
  pinned actions, Docker base image and Python dependencies current.

### Changed

- Website: moved to <https://maplestats.danielstats.io/>. The old GitHub Pages
  address redirects there, and the hosted server accepts browser calls from
  the new domain only (plus localhost).
- Website: the FAQ's "last updated" date and the About page's "checked in"
  month come from the build date.
- StatCan census notes point `census_tables` users to the 2021 profile.

### Fixed

- Hosted server: rate limits read `X-Forwarded-For` from the right
  (`MAPLE_TRUSTED_PROXY_HOPS`) and apply before the token check; timed-out
  calls count in `/stats`.
- Upstream XML is parsed with defusedxml (Borealis, StatCan Daily, WFS,
  electricity). Bulk downloads and unpacked ZIP members are capped at the
  cache size, and failed unpacking raises typed errors and cleans up.
- Earthquakes: catalogue ids are refused with a message naming the accepted
  minute form. EPCOR: `as_of` is the newest day with a value. Transit: exo's
  moved GTFS feeds.

## [0.2.0] - 2026-10-04

### Added

- 358 tools in 69 modules.

### Changed

- French throughout: errors, notes, provenance, limits and licences of every
  module, the planner's plans and `reproduce_code`'s notes, and the French
  website pages.
- Search: more French function words as stop words, with a parity test for
  the in-page search.
- README: current tool and module counts, every module in the coverage table.
- FAQ: sources not built or removed, and new sources' reuse conditions.

## [0.1.1] - 2026-09-28

### Added

- Case-study pages ("Demos") and release notes on the website.
- Issue templates for bug reports and source requests.
- Registry and listing badges (PyPI, MCP Registry, Smithery, Glama, M8ven).

### Changed

- Near-duplicate Statistics Canada, RDaaS, Bank of Canada and CKAN tools
  merged.
- The three visible tools' descriptions sharpened; English tool discovery
  tested against 98 realistic questions.
- Bank of Canada list tools accept `limit` without a query.

### Fixed

- CDC price CSV with French headers is accepted; an empty Edmonton Police
  Service load-date table now raises a clear "reload in progress" error.

## [0.1.0] - 2026-09-27

First public release: one MCP server for Canadian open data, with
`plan_query`, `search_tools` and `call_tool` in front of every module,
published to PyPI and the MCP Registry.

### Added

- Statistics Canada, Bank of Canada, CMHC, federal agency, provincial,
  territorial and municipal modules, and the CKAN, ArcGIS Hub and Socrata
  portal modules.
- Read-only annotations on every tool.
- PMPRB and Parliamentary Budget Officer modules.
- The bilingual website, generated from the running server.

### Fixed

- Statistics Canada WDS observation release times are read as Eastern time.

[Unreleased]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/dsanchezp18/maplestats-mcp/releases/tag/v0.1.0
