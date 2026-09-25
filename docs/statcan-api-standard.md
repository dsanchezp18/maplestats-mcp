# Statistics Canada API Standard — Investigation

Investigated 2026-09-14. Covers the official StatCan API surface itself,
plus what the two dedicated StatCan-specific MCP benchmarks named in the
[project guide](../PROJECT_GUIDE.md) (`Aryan-Jhaveri/mcp-statcan`,
`pipeworx-io/mcp-statcan`) actually implement against it — so the gap
analysis for MapleStats's StatCan module is grounded in code, not just the
official docs.

## There are two separate StatCan APIs

### 1. Web Data Service (WDS) — the core data API

- **Base URL:** `https://www150.statcan.gc.ca/t1/wds/rest/`
- **Protocol:** REST over HTTPS, JSON responses, GET and POST, no
  authentication required.
- **15 methods**, three groups:
  - *Change tracking:* `getChangedSeriesList`, `getChangedCubeList`
  - *Metadata/discovery:* `getCubeMetadata`, `getSeriesInfoFromCubePidCoord`,
    `getSeriesInfoFromVector`, `getAllCubesList`, `getAllCubesListLite`,
    `getCodeSets`
  - *Data retrieval:* `getChangedSeriesDataFromCubePidCoord`,
    `getChangedSeriesDataFromVector`,
    `getDataFromCubePidCoordAndLatestNPeriods`,
    `getDataFromVectorsAndLatestNPeriods`, `getBulkVectorDataByRange`,
    `getDataFromVectorByReferencePeriodRange`, `getFullTableDownloadCSV`,
    `getFullTableDownloadSDMX`
- **Addressing system:**
  - **PID** — 10-digit Product ID: subject code (2) + product type (2) +
    sequential number (4) + optional simple-view id (2).
  - **Vector** — `V` + up to 10 digits, a stable time-series identifier
    carried over from legacy CANSIM.
  - **Coordinate** — dot-concatenated member IDs, one per dimension, up
    to 10 dimensions (e.g. `1.3.1.1.1.1.0.0.0.0`).
- **Rate limits:** 50 req/sec server-wide, 25 req/sec per IP.
- **Not for bulk retrieval** — WDS methods cap data points per request.
  StatCan's own alternative for large volumes is the **Delta File**, a
  flat file of everything that changed on a given release day.
- **Update cadence:** new data at 8:30am ET every business day.
  **12am-8:30am ET is a lock window** — some methods return HTTP 409 or
  stale data during it. A real gotcha any adaptor needs to handle
  defensively (retry/backoff or explicit "data locked" surfacing), not
  silently swallow.
- **Response payload gotchas:**
  - `value` already has `decimals` applied (unlike legacy CANSIM
    outputs).
  - `scalarFactorCode` (the x1000/x1M multiplier) is **not**
    auto-applied — must be fetched separately via `getCodeSets` and
    applied by the client.
  - `symbolCode` flags preliminary/revised/normal; `securityLevelCode`
    flags public vs. confidentiality-suppressed.
- Also offers full-table export as **CSV** (bilingual) and **SDMX/XML**.

### 2. Reference Data as a Service (RDaaS) — classification/metadata API

- **Base URL:** `https://api.statcan.gc.ca/rdaas`
- Separate API for **classifications, codesets, concordances, indices,
  and exclusions** — e.g. NAICS, the Standard Geographical
  Classification, occupational classifications, and the correspondence
  tables between classification versions.
- Purpose per StatCan: facilitate data harmonization across departments
  and external partners via standardized reference data through an open
  API.
- This maps directly onto the MapleStats project guide's ambition to make
  "StatCan documentation pages a first-class agent-accessible source" —
  RDaaS delivers concepts/classifications/methodology as a structured
  REST/JSON API, not something that requires scraping PDFs or HTML
  documentation pages.

## What the existing StatCan-specific MCP benchmarks actually cover

Both repos were cloned and inspected directly (not just their READMEs).

### Aryan-Jhaveri/mcp-statcan — the stronger of the two

- MIT-licensed, Python, hosted publicly on Render
  (`mcp-statcan.onrender.com`), also ships a standalone `statcan` CLI for
  non-LLM/direct-terminal use — the same code path serves both surfaces.
- **WDS coverage:** full discovery/metadata (`search_cubes_by_title`,
  `get_all_cubes_list`/`_lite`, `get_cube_metadata`, `get_code_sets`),
  series resolution and change detection (`get_series_info`,
  `get_series_info_from_vector`, `get_changed_cube_list`,
  `get_changed_series_list`, `get_changed_series_data_from_cube_pid_coord`
  /`_from_vector`, `get_bulk_vector_data_by_range`).
- **SDMX coverage — the most sophisticated part:** tools return only the
  requested slice of a table, not the full table, keeping response size
  small. `get_sdmx_structure` fetches dimension codelists before a query;
  `get_sdmx_key_for_dimension` solves a real StatCan SDMX gotcha —
  wildcarding (`.`) a dimension with more than ~30 codes returns a
  sparse, unpredictable sample, so this tool fetches the full leaf-member
  list as a ready-to-paste OR key instead.
- **Composite/database tools** (`fetch_vectors_to_database`,
  `store_cube_metadata`, `query_database`, table CRUD) exist but are
  deliberately excluded from the shared hosted server — SQLite is
  per-process, not safe to share across simultaneous users — and are
  local/stdio-mode only. This is the same public/maintenance split
  pattern EcuDataMCP uses, arrived at independently.
- **No RDaaS coverage at all** — confirmed by grepping the full source
  tree. Classifications/concordances are entirely untouched.

### pipeworx-io/mcp-statcan — a thin, curated wrapper

- TypeScript, part of the larger Pipeworx MCP gateway (1,476+ sources
  across all packs). Only 7 tools: `statcan_indicator` (curated
  headline series — CPI, unemployment, GDP, population, by friendly
  name), `statcan_series` (raw vector lookup), `statcan_list_cubes`,
  `statcan_cube_metadata`, `statcan_cube_data`, `statcan_changed_series`,
  `statcan_csv_url`.
- No SDMX support, no RDaaS, no CLI, no composite/database tools. A
  minimal reference implementation, not an architecture benchmark.
- Connecting to its scoped endpoint also pulls in ~30 shared
  Pipeworx-gateway meta-tools (`ask_pipeworx`, `discover_tools`, etc.) —
  a real design tradeoff of building on someone else's gateway rather
  than a standalone server.

## Implication for MapleStats's StatCan module

- **RDaaS is a genuine, confirmed gap** across every benchmark reviewed
  (ReyemTech, Aryan's, pipeworx-io's). Building it is real new coverage,
  not duplicated effort, and it is the most direct way to deliver the
  "StatCan documentation/classifications as a first-class source" goal
  from the project guide — as a structured API, not scraped
  documentation.
- **Aryan's SDMX slice-only pattern and `get_sdmx_key_for_dimension`
  helper are directly worth porting** — they solve real StatCan API
  footguns (context bloat from full-table returns; silent sparse
  sampling on wildcarded large dimensions) that a naive implementation
  would rediscover the hard way.
- **Aryan's hosted/local tool-split and CLI-plus-MCP dual surface** are
  both worth adopting as general MapleStats architecture patterns (see
  the [architecture decision page](https://app.notion.com/p/3db4d10b4945813aa4d2cd0217038de1) in Notion), not just for the StatCan
  module specifically.
- The response-payload gotchas (`scalarFactorCode` not auto-applied,
  the 12am-8:30am ET lock window, `securityLevelCode` suppression) must
  be handled explicitly in MapleStats's `statcan/client.py` — none of
  this is optional correctness work, since silently returning an
  unscaled value or a stale locked-window response would be a real data
  error, not a style issue.
