# Per-language clients: design note

Status: proposed 2026-11-07. Covers the roadmap row "Per-language clients"
and the Notion page "Architecture decision: Python core, hosted REST + MCP,
per-language clients" (2026-09-14, status note of 2026-10-19).

## What the clients are for

The MCP server is used by an AI agent. The clients are for a researcher
writing an R, Python or Julia script: find a tool, call it, get a data frame
back with its source attached. They are thin. Every tool, every source quirk
and every citation stays in the Python server; a client knows only how to
talk to `/mcp` and how to turn a tool result into rows.

## What the clients call: the MCP endpoint, no REST layer

The 2026-09-14 decision planned a plain REST/JSON facade beside `/mcp`,
mainly because Stata and SAS cannot speak MCP's transport. For R, Python and
Julia it is not needed. Checked live against
`https://mcp.maplestats.danielstats.io/mcp` on 2026-11-07 (server 0.4.8):

1. `POST /mcp` with a JSON-RPC `initialize` request and
   `Accept: application/json, text/event-stream` answers HTTP 200 with
   `content-type: text/event-stream` and an `mcp-session-id` header. The body
   is one `event: message` whose `data:` line is the JSON-RPC response.
2. `notifications/initialized` with that session id answers HTTP 202.
3. `tools/call` on `call_tool` (`{"name": tool, "arguments": {...}}`) answers
   one `event: message` with `result.structuredContent`, the tool's Pydantic
   model as JSON, `provenance` included (checked with `boc_get_observations`
   and `wds_get_data_from_vectors`). A tool error comes back as
   `result.isError: true` with the message in `result.content[0].text`
   (checked with an unknown Valet series).

That is ordinary HTTP plus reading one `data:` line, which `httpx`, `httr2`
and `HTTP.jl` all do without an MCP SDK. The clients therefore speak the
streamable HTTP transport directly. A REST facade stays an option for a later
Stata or SAS client; nothing here depends on it, and nothing here changes the
server.

Transport rules the clients follow:

- One session per client object, opened lazily on the first call. The hosted
  server drops idle sessions after 5 minutes (`session_idle_timeout=300` in
  `asgi.py`); on HTTP 404 for a known session the client opens a new one and
  repeats the request once.
- Protocol version `2025-06-18`, sent as `mcp-protocol-version` after
  `initialize`.
- Request timeout 240 s: the hosted server lets a tool call run 230 s.
- HTTP 429 (60 requests a minute per client) raises an error that carries
  `Retry-After`; the client does not sleep and retry on its own.
- A `User-Agent` of `maplestats-<language>/<version>`. No token: the hosted
  endpoint is public. `MAPLESTATS_URL` (and a `url` argument) point a client
  at a self-hosted or local server; `MAPLESTATS_TOKEN` adds a bearer token for
  one started with `MAPLE_AUTH_TOKEN`.

## Minimal API

The same five operations in each language, named in each language's style.

| Operation | Python (`maplestats`) | R (`maplestats`) | Julia (`MapleStats`) |
|---|---|---|---|
| Find tools | `search_tools(query)` | `ms_search_tools(query)` | `search_tools(query)` |
| Plan a multi-source question | `plan_query(question)` | `ms_plan_query(question)` | `plan_query(question)` |
| Call a tool, raw result | `call_tool(tool, **args)` | `ms_call_tool(tool, ...)` | `call_tool(tool; args...)` |
| Call a tool, tidy rows | `get_data(tool, **args)` | `ms_get_data(tool, ...)` | `get_data(tool; args...)` |
| Script that re-fetches it | `reproduce_code(tool, args, language)` | `ms_reproduce_code(tool, args, language)` | `reproduce_code(tool, args; language)` |

Each language also has a client object (`Client`, `ms_client()`,
`MapleStats.Client`) holding the URL, timeout and session; the functions above
use a default one and take an optional client.

- **Search** returns a data frame with one row per tool: `name`,
  `description`, and the input schema as JSON text.
- **Raw result** is the decoded `structuredContent` (a dict, list or `Dict`).
- **Tidy rows** apply the rule `reproduce_workbook` already uses
  (`modules/reproduce/workbook.py::rows_and_left_out`), ported line for line:
  the result's largest list of objects (searched four levels deep, provenance
  aside) becomes the rows; when each of those objects holds its own list of
  objects (a series and its observations), every inner object is a row and
  carries the outer object's other fields; nested objects become dotted names
  and scalar lists become `"; "`-joined text. Names are then cleaned to
  snake_case as `clean_names` does. No value conversion beyond JSON's own
  types: dates stay text, so the client never guesses a type the server did
  not state.
- **Citations travel with the frame.**
  - R: attributes on the tibble, `attr(x, "provenance")` (the list),
    `attr(x, "citation")` (character, one per distinct citation, from
    `context.citation` where the source gives one, else built from
    `provenance.source`, `url` and `queried_at`), `attr(x, "tool")` and
    `attr(x, "arguments")`.
  - Julia: DataFrames.jl metadata, `metadata(df, "citation")` and the same
    keys, with style `:note` so they survive most transformations.
  - Python: polars frames cannot carry attributes, so `get_data` returns a
    small `Result` dataclass: `.data` (`polars.DataFrame`), `.provenance`,
    `.citation` (list of str), `.left_out` (fields beside the rows, as the
    workbook's Source sheet lists them), `.tool`, `.arguments`, `.raw`. The
    frame is the one thing most code touches; the rest is one attribute away.
    `pandas` is not a dependency; `.data.to_pandas()` works when `pyarrow` and
    `pandas` are installed.
- **Errors** are raised, never returned: a tool's `isError` result, a
  JSON-RPC error and a non-2xx HTTP answer each raise the language's error
  type (`MapleStatsError` in Python and Julia, an `rlang` condition of class
  `maplestats_error` in R) with the server's message, which already says how
  to fix the call.

Deliberately left out: one wrapper function per tool (about 500 tools that
change every week; `search_tools` is the index), caching (the server caches
upstream), async (one call at a time is the right pace against a 60 a minute
limit), and value typing.

## Names and where they live

- Python: distribution `maplestats`, import `maplestats`. R: package
  `maplestats`, functions prefixed `ms_` (as `cansim` uses `get_cansim_*`, a
  prefix keeps tab completion useful). Julia: `MapleStats.jl`. Check each name
  is free on PyPI, CRAN and the General registry before the first release.
- In this repository, under `clients/python/`, `clients/r/` and
  `clients/julia/`. One repository keeps the clients next to the tool surface
  they depend on and the design rule they port, and lets one pull request
  change both when the result shape changes. All three package managers
  accept a package in a subfolder (PyPI builds from any folder; CRAN takes the
  built tarball; the General registry records a `subdir`). Move a client to
  its own repository only if it gains outside maintainers.
- None of them is a dependency of the server, and the server's `pytest`,
  `ruff` and `pyright` runs do not reach `clients/` (`testpaths` is `tests`
  and `src`). Each client has its own project file, lint configuration and
  tests.

## Packaging: not now

No release to PyPI, CRAN or the General registry yet. Install from GitHub:

```bash
pip install "git+https://github.com/dsanchezp18/maplestats-mcp#subdirectory=clients/python"
```

```r
pak::pak("dsanchezp18/maplestats-mcp/clients/r")
```

```julia
using Pkg; Pkg.add(url="https://github.com/dsanchezp18/maplestats-mcp", subdir="clients/julia")
```

## Tests

Each client's tests run without network access against recorded responses:
the SSE bodies of `initialize`, `search_tools`, a Bank of Canada call, a WDS
vector call and a tool error, saved under each client's test fixtures by
`clients/record_fixtures.py`. One live test per client, skipped unless
`MAPLESTATS_LIVE=1`, runs search, a small Bank of Canada call and the tidy
conversion against the hosted server.

Conventions: Python uses `ruff` (format and check), type hints checked by
`pyright`, and returns polars frames; R uses the native pipe, tidyverse style,
`styler` and `lintr`, `httr2` for HTTP and `testthat` for tests; Julia uses
`HTTP.jl`, `JSON3.jl`, `DataFrames.jl` and `JuliaFormatter`.

## How this relates to `reproduce_code`

They answer different needs and do not replace each other.

- A **client** goes through MapleStats: one interface to every source, the
  server's validation and error messages, citations attached. It needs the
  server to be up, and it is the quick way to explore.
- **`reproduce_code`** writes a script that goes straight to the publisher
  (`cansim`, Valet, CKAN, the source's own files) with no MapleStats in the
  path. It is what belongs in a replication package, because it keeps working
  if MapleStats changes or goes away.

The bridge is `reproduce_code()` in each client: explore with `get_data`,
then ask for the script that fetches the same rows directly and save it into
the project. A client never writes or runs that script on its own.

## Order of work

1. This note (one pull request).
2. Python client, with tests.
3. R client, with tests.
4. Julia client, with tests.

Each is its own pull request. A Stata client is not planned: `reproduce_code`
already writes Stata do-files, and a Stata user who wants live calls can use
the Python client through `pystata`.
