# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [semantic versioning](https://semver.org/) while it is in beta.

## [Unreleased]

### Added

- A circuit breaker per upstream host (`shared/breaker.py`). After 5 failures in a row
  within 5 minutes (timeouts, connection errors, 5xx answers, Cloudflare challenges) a host
  is paused for 60 seconds: its tools fail at once with `UpstreamUnavailable`, in English or
  French, naming the host and when to try again, instead of each caller waiting out another
  timeout. After the cooldown one request goes through as a probe and an answer closes the
  breaker. A call and its retries (`shared/http.py`, `shared/retrying.py` and the modules'
  own retry loops) count as one failure, and 4xx answers never count. Settings:
  `MAPLE_BREAKER` (`0` turns it off), `MAPLE_BREAKER_FAILURES`,
  `MAPLE_BREAKER_WINDOW_SECONDS`, `MAPLE_BREAKER_COOLDOWN_SECONDS`.
- `docs://status`, a bilingual resource listing the hosts paused now and when each is
  tried again.
- `/stats` adds `latency_ms` (each tool's p50 and p95 over its last 500 calls) and
  `upstreams` (the breaker settings, and per host its error counts by kind, refused
  requests, times opened and current state). Still in memory, with no arguments and no
  client addresses; the FAQ and privacy page say so.
- A breaking-change check on the tool surface: `tests/test_tool_surface.py` compares
  `tool_catalogue.json` with its version at the merge base with `origin/main` and fails while a
  breaking change (tool or parameter removed or renamed, type narrowed, required parameter
  added, output field removed) names a tool this Unreleased section does not mention.
  `uv run python scripts/check_tool_surface.py` prints the breaking, additive and other changes.
  CI now checks out the full history for it.
- A weekly `Newest FastMCP` workflow that runs pyright and the test suite against the newest
  `fastmcp`, past the `<4.2` cap, and reports a failure in its run summary without blocking
  merges.

### Changed

- The server imports a module's code only when one of its tools is first called. `tools/list`
  and `search_tools` now read `tool_catalogue.json`, a generated listing of every tool (name,
  title, docstring, schemas, annotations), so importing the server took 5.8 s instead of 20.4 s
  in interleaved runs on 2026-10-23 (Windows, Python 3.12). The first call into a module pays its
  import once (1.5 s for `boc`, 3.2 s for `statcan/wds` in the same runs); later calls are
  unchanged. Listings, search results and the discovery benchmark's scores are identical. Without
  the catalogue file, or for a module it does not list, the server loads modules at startup as
  before. Regenerate it with `uv run python scripts/build_tool_catalogue.py`;
  `tests/test_tool_catalogue.py` fails while it is stale.
- Website: the Connect page's hosting table now lists `MAPLE_CLIENT_IP_HEADER`,
  `MAPLE_TRUSTED_PROXY_HOPS`, `MAPLE_DUCKDB_MEMORY_LIMIT`, `MAPLE_DELTA_MAX_SCAN_MB`,
  `MAPLE_DELTA_MAX_SCAN_SECONDS` and `MAPLE_DELTA_INDEX_DIR`, which the README already
  documented, and a test fails when a setting in `config.py` is missing from it.

## [0.4.1] - 2026-10-20

### Removed

- Smithery publishing: the release workflow's `smithery` job, `scripts/build_smithery_bundle.py`,
  the pinned CLI in `.github/smithery/`, and the Smithery badge in the README and site.
  Smithery answered the 0.4.0 publish with HTTP 403 ("Updating servers has been removed")
  and shuts down its API and CLI on 2026-10-31.

### Fixed

- `bc_env_list_streamflow_gauges` and `bc_env_get_streamflow` with `parameter="stage"`:
  `Stage.csv` now carries 2- to 15-minute readings and grows about 1.3 MB a day (29.7 MB on
  2026-10-20), so the 64 MB cap set in 0.4.0 would run out by mid-November. The gauge list
  now streams the file and keeps one row per station, and past 64 MB a single gauge is read
  by range; with no `start`, that range read covers the last 14 days first and says so in
  the notes.
- `nrcan_nbac_query_fires` with `include_geometry=true`: a GeoJSON answer over the 20 MB
  response cap (the five largest 2023 BC fires are 33 MB) now returns the fires without
  geometry, counted in `geometry_omitted`, instead of an error.
- Range reads (transit GTFS feeds, zip members, sorted archives): a 200 answer to a range
  request from a host that advertises `Accept-Ranges: bytes` is retried twice after 3 s.
  RTC Québec's CDN answered one such request in full on 2026-10-19 and honoured it later.
- `cwfis_get_forecast`: once the fire season ends the SCRIBE forecast layer is empty
  (2026-10-20), and every station name answered "No forecast station name contains ...".
  An empty layer now gets its own message pointing to `cwfis_get_fire_danger`.
- The Cloudflare-challenge error named Statistics Canada for every host, including
  Alberta's economic dashboard, in both languages; it now says the publisher.
- Live smoke tests: `smoke_test_arcgis_hub` rechecks only its failing portals after a
  minute (a full pass takes 15 minutes, so the workflow's whole-script rerun ran out of
  time), the smoke job timeout is 40 minutes, `smoke_test_ab_economic` skips on a GitHub
  runner that Cloudflare challenges, as `smoke_test_modules` already did, and
  `smoke_test_bc_environment` reads a current stage series.

## [0.4.0] - 2026-10-20

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

- `MAPLE_DUCKDB_MEMORY_LIMIT` limits DuckDB's memory for queries over downloaded files, and
  `MAPLE_CLIENT_IP_HEADER` (such as `CF-Connecting-IP`) keys the per-client rate limit on the
  caller's own address behind Cloudflare. The hosted instance sets both, and allows 8
  concurrent requests (was 4).
- `fastmcp` is capped below 4.2, because the server uses internals of 4.1.
- The README, FAQ and Connect page say the first request to the hosted server after a quiet
  spell can take up to a minute.
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
- The server's Docker image is built on `python:3.14-slim` (it was `python:3.12-slim`), pinned
  by digest. The package classifiers list Python 3.14, and CI tests it.
- Website: the home page's "See it in action" section is a question box, a plain GET form to
  the chat demo that works without JavaScript, beside four example questions and the demo's
  caveats, instead of a stack of example rows.
- Website: the privacy page also covers the chat demo (questions go to a third-party language
  model provider, Anthropic by default) and the website itself (GitHub Pages). The FAQ says the
  server does not write tool arguments down and that HTTP access logs can include the network
  address.
- Website: pages count visits with GoatCounter (page, referrer, browser, operating system, screen
  size and country as aggregate counts; no cookies, no IP address stored), in a GoatCounter site
  shared with other hostnames, so every path starts with the host. The privacy page and the FAQ
  say so; the MCP server and the chat demo are not counted.

### Fixed

- Live smoke fixes: `boc_get_group` accepts Valet's renamed `groupDetail` key; the BC
  Environment hydrometric files may be up to 64 MB (`Stage.csv` reached 29 MB); a TLS
  verification failure on PHAC's host is reported as such instead of as a timeout.
- Caller-facing typed errors (about 70, across fcac, nfd, IP Horizons, provincial elections,
  health products, CMHC data tables, the reproduce builders and the shared Cloudflare
  challenge) now follow `lang="fr"`. A LODE download that answers 404 raises `NotFound`, and
  its redirects get the shared host check.
- A server started with `uvicorn maplestats_mcp.asgi:app` (no `MAPLE_TRANSPORT`) counts as
  HTTP, so `reproduce_workbook` no longer writes to the server's own disk and the export tools
  describe themselves as hosted.
- Idle MCP sessions on the hosted server are dropped after 5 minutes instead of 30.
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
  the box, so trying again does not mean retyping it. Every website page now states its
  referrer policy (`strict-origin-when-cross-origin`), so the demo can tell a visitor came
  from the website without relying on a host header or browser default, and a test checks
  that the origin the demo trusts is the website's.
- Chat demo image: `chat/Dockerfile` installs from `chat/uv.lock` with `--locked`, as the
  server's image does, instead of resolving the newest versions at build time. It now uses
  the server image's base, `python:3.14-slim` pinned by digest, instead of an unpinned
  `python:3.12-slim`, and Dependabot bumps both digests in one pull request.
- `plan_query`: a vector ID beside the word "vector" ("vector v41690973") counts as one
  `statcan_tables` cue, not two; the ID counted once as itself and again as the word's
  neighbour.
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
- Downloads stop at their byte cap instead of reading the whole file first and rejecting
  it afterwards: `csv_files` (CER, GC InfoBase, CDC, election results), `remote_zip` (a
  host that stops honouring `Range` no longer makes the server buffer a multi-gigabyte
  archive), and the file readers in bc_lobbyists, recalls, cgc, ircc_monthly, nfd,
  finance_canada, phac_infobase, elections_provincial, cfia, ised_clean_growth, isq,
  nl_stats, cihi, pmra, nrcan_minerals and pmprb. A central directory larger than 64 MB
  is refused.
- A page whose expected content is missing is now an upstream error instead of an empty
  result cached as a success: `cmhc_list_categories` and `cmhc_list_provinces` (24 h),
  CIHI's indicator library (7 days), NL Stats topic pages (6 h), and an Earthquakes
  Canada 404 (which read as "no earthquakes").
- `statcan_surveys_get_survey_metadata`: a 5xx answer is no longer cached for a day.
- `sdmx_get_structure` and `sdmx_get_key_for_dimension`: when the SDMX structure document
  is empty and the dimensions are rebuilt from WDS, every member is read (paged at 2,000),
  not the first 100; a geography or NAICS dimension with more than 100 members used to be
  silently truncated and its OR key incomplete.
- `plan_query`: the French word for gold ("or") no longer matches the English conjunction
  and sends questions to the minerals tools; "yield" and "dollar" alone no longer put the
  Bank of Canada first for "canola yield" or "a million dollar question"; duplicate plural
  terms no longer double-count a topic; "minéraux critiques" and "tps/tvh" match again;
  "London, England" and "Victoria, Australia" are out of scope instead of Ontario or BC.
- `electricity` (Hydro-Québec): the recent-generation and trade queries share the 5-minute
  cache again; the cutoff time was written to the second into the cache key.
- `boc`: a Valet payload missing `seriesDetails`, `groupDetails` or a date column is an
  upstream error naming the field, not a `KeyError`.
- `oeb_get_dataset_file`: a numeric `file` position counts within the chosen release; "0"
  and positions past the end are invalid input. Zero-padded codes stay strings.
- `reproduce_code("reproduce_workbook", ...)` is invalid input and no longer writes a
  workbook as a side effect; `reproduce_workbook` writes header cells as text, so a series
  name starting with "=" cannot become a formula; the Julia POST body is escaped once, so
  a "$" in it yields valid JSON.
- Typed errors where a bare exception or the wrong class escaped: PUMF tabulation
  (DuckDB errors, a missing replicate id variable, cache eviction on Windows), Delta CSV
  rows, CIMT province codes, WDS failed-envelope links and code sets, SDMX 400/403,
  AER daily well licences (a 404 was "did not respond"), DriveBC protocol errors,
  Health Canada non-JSON answers, BC election results, Borealis searches (Solr operators
  in the query are now literal, a 400 is invalid input), CKAN organization lists,
  ECCC coverage 406/409 answers, Competition Bureau weekly rows, CRA charities null
  totals, NRCan Geonames bounding boxes (validated before the request), the arcgis_hub
  download-format probe, and IRCC monthly totals (an unreadable cell is counted and
  noted instead of failing the table).
- French: `transit` stop-time errors, the `_example` template's `lang`, and the CMHC,
  Finance Canada and ISED clean-growth number parsers (a French decimal comma was read
  as a thousands separator or the reverse). Notes in `ab_opendata`, `bc_environment`,
  `bc_lobbyists`, `boc`, `crea`, `eccc_datamart`, `represent` and `transit` now agree in
  gender and number ("lectures limitées") and address the reader as "vous" ("Ne supposez pas",
  "vérifiez"); `bc_lobbyists` says "lobbyisme", and the locked-data message names Statistique
  Canada, not StatCan.
- Website: the home page's chat card no longer widens past its column on phones, and its
  example questions open the chat demo with the question asked instead of doing nothing. The
  chat page asks a `?q=` question on arrival, scrolls to the start of an answer, shows a focus
  ring, and explains a non-JSON gateway error while the host wakes instead of printing a JSON
  parse error.
- `/stats`: `reproduce_code` and `reproduce_workbook` call the server again in-process, and
  that inner call counted as a second call by the caller; it no longer does.
- A response that does not fit a tool's model is an upstream error ("the source answered in a
  shape this tool does not expect"), no longer reported as invalid arguments, and the error
  does not echo the values.
- Retries read `Retry-After` as whole seconds or an HTTP date, the same as the rate-limit
  handling; a header made of non-ASCII digits (such as "²") no longer raises.
- `MAPLE_TRANSPORT` accepts only `stdio` or `http` and `MAPLE_PORT` must be an integer;
  a typo used to start an HTTP server while the client waited on stdin, or bind 8000
  while the health check probed the typo. Other numeric variables warn once when ignored.
- `uvicorn maplestats_mcp.asgi:app` now applies the `MAPLE_REQUIRE_AUTH` refusal and the
  external-bind warning, which only `python -m maplestats_mcp` did before.
- `maplestats-mcp --version` prints the version, as SECURITY.md asks reporters to run.
- A subdomain wildcard in `MAPLE_ALLOWED_ORIGINS` matches an origin with a port.
- CI runs the tests that execute the generated R and Julia scripts on the 3.12 leg; they
  skipped on every run because the runner had neither. `setup-uv` is pinned to the
  Dockerfiles' uv version, every workflow declares `permissions`, Dependabot covers
  `chat/uv.lock`, and `server.json` lists the hosted Streamable HTTP endpoint.
- Docs: the README environment table lists `MAPLE_USAGE_STATS`, the LODE cache variables
  and `MAPLE_EXPORT_DIR`; four broken relative links in `docs/`; the roadmap's release
  and monitoring rows; the connect page's volume count.

### Security

- `reproduce_code`: the tool name is validated against the registry and sanitised before it
  is written into the Stata `log using` line; a crafted name used to inject a `shell` line
  into the generated do-file. The PUMF builder checks the ZIP URL against StatCan's host
  the way the PUMF tools do, instead of emitting a script that downloads and unzips any
  URL it was given.
- `isq`: a table URL is accepted only when its host is exactly `statistique.quebec.ca`;
  a string-prefix check let `statistique.quebec.ca.example.net` and
  `statistique.quebec.ca@example.net` through (server-side request forgery).
- `csv_files` and `nfd` re-check the host allow-list on every redirect hop; the chat demo's
  `/api/chat` requires `Content-Type: application/json` (a cross-site "simple" POST from
  any web page could spend the model budget) and trusts `X-Forwarded-For` only on Render
  or when `CHAT_TRUST_PROXY_HEADERS=1`; its CDN scripts carry integrity hashes and
  DOMPurify is 3.4.17; the Smithery publish step installs from a lockfile with integrity
  checks instead of `npx`; a repeated `X-Forwarded-For` header line can no longer choose
  its own rate-limit bucket.
- `reproduce_code` refuses a redirect, on a request it replays, to anywhere other than the
  request's own site or a file host (never an IP address, localhost or plain http), the rule
  `remote_zip` already applied.

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

[Unreleased]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/dsanchezp18/maplestats-mcp/releases/tag/v0.1.0
