# ReyemTech `mcp-canada` — Source & Functionality Scan

Scan date: 2026-09-14. Source: shallow clone of
[ReyemTech/mcp-canada](https://github.com/ReyemTech/mcp-canada) at the
`main` branch tip (v0.12.0, released 2026-08-24). This is a working
reference for the MapleStats MCP fork decision — it records exactly what
the benchmark project covers today, so gap analysis against the
[MapleStats MCP vision](../PROJECT_GUIDE.md) doesn't rely on memory or the
README's marketing copy.

## Project health

- MIT-licensed, PyPI-published (`mcp-canada`), currently v0.12.0.
- ~109,000 lines across 341 Python files in `src/`, plus ~60,000 lines of
  tests. Not a stub — a substantial, working codebase.
- 96% test coverage enforced in CI (`fail_under = 95` in `pyproject.toml`),
  CI runs on Python 3.12/3.13/3.14 with `ruff`, `pyright`, `pytest`, and a
  catalog-freshness check.
- `python-semantic-release` automates versioning, changelog, and GitHub
  releases from conventional commits.
- Appears to be built by a single maintainer with heavy AI-assisted
  development (an 18KB `CLAUDE.md` dev-convention doc ships in the repo).
- `ROADMAP.md` is stale relative to the actual code — it still lists most
  shipped provinces as "Planned."

## Architecture

Every data-source module follows the same file pattern (a `_example/`
module in the repo serves as the living template):

```
src/mcp_canada/modules/{name}/
  __init__.py      # MODULE_NAME + MODULE_DESCRIPTION (+ _FR variant)
  constants.py     # BASE_URL, rate limits, cache TTLs
  schemas.py       # Pydantic v2 flat models
  client.py        # Async functions -> (data, was_cached)
  tools.py         # @tool functions, BM25 keywords in docstrings
  resources.py      # (optional) MCP resources
  prompts.py        # (optional) MCP prompts
  __tests__/
```

Shared infrastructure reused by every module (`src/mcp_canada/shared/`):

- BM25-indexed tool search for natural-language tool discovery.
- Bilingual support — every tool takes `lang: en|fr`.
- `cached_fetch()` with per-source TTLs.
- `get_limiter()` — a per-source `TokenBucket` rate limiter.
- `fetch_and_parse()` for CSV/XLS/XLSX.
- `make_response()` / `make_error()` — a standard `_meta` response
  envelope with provenance.
- A local SQLite datastore module for cross-source joins.
- A 14-platform installer (Claude Desktop, Claude Code, Cursor, VS Code,
  Windsurf, Zed, Codex CLI, Gemini CLI, Amazon Q, OpenCode, Cline, Roo
  Code, Goose CLI, Junie CLI).

There is no hosted server — it runs locally via `uvx mcp-canada` (stdio),
though FastMCP (the underlying framework) supports HTTP/SSE transport if
that were wired up for hosting.

## Source coverage — 21 modules, ~295 tools

### Federal (10 modules)

| Module | Coverage |
|---|---|
| `statcan` | WDS + SDMX: cube/table search, metadata, code sets, series lookup by vector/coordinate, data retrieval (vector, coordinate, date range, bulk), change detection (changed series/cubes), SDMX structure/data/vector endpoints, fetch-to-local-datastore. |
| `bank_of_canada` | Valet API: exchange rates, interest rates (policy rate, CORRA, bond yields), commodity price index (BCPI), CPI/inflation, series search, series metadata, raw observations, group browsing. |
| `ckan` | Federal Open Government portal (open.canada.ca, 80K+ datasets): search, dataset details, organizations, tag search, resource metadata, group listing, portal stats. |
| `ircc` | Immigration: permanent residents, study permits, work permits (TFWP/IMP), Express Entry, TR-to-PR transitions, asylum claimants, operational processing, Afghan refugees, ad-hoc PR, citizenship, dataset listing — sliceable by country/province/gender/age. |
| `drug_database` | Health Canada Drug Product Database: search by brand/DIN/company, ingredients, routes of administration, schedule class, ATC therapeutic class, market status. |
| `recalls` | Health Canada recalls: recent, keyword search, full details, food-specific, vehicle-specific, health-product-specific. |
| `nutrient_file` | Canadian Nutrient File: food search, per-100g nutrient detail, serving sizes, food-group browsing, nutrient/food-group listing, side-by-side food comparison (2-5 items). |
| `open_parliament` | OpenParliament.ca: bill search, bill details, MP search/lookup, riding search, party member lists, vote records, individual MP voting record, Hansard debate browsing, full-text Hansard search. |
| `weather` | Environment Canada MSC GeoMet (OGC API Features), split into 9 sub-modules: `current`, `climate` (daily/hourly/normals), `aqhi` (air quality), `hydro`, `marine`, `severe` weather alerts, `snow` depth, `summary`, `collections` — ~40+ tools. |
| `datastore` | Local SQLite: create table, insert, query (SQL), list tables, schema inspection, drop table — persists at `~/.mcp-canada/datastore.db`. |

### Provincial — 8 of 10 provinces (missing NL, PEI; no territories)

| Province | Portal tech + curated coverage |
|---|---|
| Alberta | CKAN (33K+ datasets) + ArcGIS REST + wildfire/health FeatureServers + AER energy reports (well licences, pipelines, production) + 511 road/traffic. |
| British Columbia | CKAN + direct OGC WFS geospatial: wildfires, forestry (tenure/cut blocks), protected areas, water wells, fish habitat, mining tenure, ER/walk-in clinics, highways, climate stations. |
| Manitoba | ArcGIS Hub: flood/hydrology, agriculture/drought, parks, regional health, 511 transport. |
| Saskatchewan | ArcGIS Hub + separate WSA/SPSA servers: crop yields, grain elevators, mining (potash/uranium/helium/coal), fire bans, air quality, hydrometric stations. |
| Nova Scotia | Socrata (SODA): aquaculture (marine/landbased leases, hatchery, production), water quality, boil-water advisories, health facilities, vital statistics, chronic disease prevalence. |
| New Brunswick | 4 mixed surfaces (federal CKAN subset + Socrata + bare ArcGIS Server GeoNB + key-gated 511): flood hazard, wetlands, contaminated sites, Crown land, parcels, civic addresses, schools. |
| Ontario | CKAN (2,946+ datasets, 20+ ministries): population projections 2024-2051, general dataset search/resource access. |
| Quebec | Données Québec CKAN (1,593 datasets) + MTQ WFS: health installations, ER wait times, population by municipality, road conditions/works/events, bridges, forest fires, air/water quality, electricity. |

### Municipal / regional (2 modules, covering 5 municipalities)

| Module | Coverage |
|---|---|
| `toronto` | CKAN: TTC GTFS (stops/routes), neighbourhood profiles (140 areas, 2K+ indicators), 311 requests, RentSafeTO evaluations, short-term rental (Airbnb) registrations. |
| `york_region` | Bundles 4 ArcGIS Hub portals: York Region (transit, roads, census demographics, public health, waste), Markham (addresses, roads), Newmarket (discovery only), Aurora (discovery only). |

## Confirmed gaps

Nothing found in the codebase for: **CMHC**, **Census/CanPUMF microdata**,
**Beyond 20/20**, **CRTC**, **CER**, **CRA**, **ISED**, **OSFI**, Health
Canada sources beyond drug database/nutrient file/recalls, **Transport
Canada/CTA**, **Elections Canada**, CanadaBuys procurement beyond what is
already noted in the [project guide](../PROJECT_GUIDE.md), and the
remaining provinces/territories: **Newfoundland and Labrador**, **Prince
Edward Island**, **Northwest Territories**, **Yukon**, **Nunavut**.

These gaps line up closely with the "high-priority additions" and
"deferred to v1.x/v2" sections of the MapleStats MCP project guide — see
that document for the fuller source backlog and sequencing.
