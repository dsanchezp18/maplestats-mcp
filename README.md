<p align="center">
  <h1 align="center">🍁 MapleData MCP</h1>
  <p align="center">
    <strong>One MCP server for Canadian public data.</strong>
  </p>
</p>

MapleData MCP gives AI agents (Claude, Cursor, and any MCP-compatible
client) structured, typed access to Canadian public data through a
single server — starting with Statistics Canada, expanding across
federal, provincial, territorial, and municipal sources.

See [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md) for the project vision and
[`ROADMAP.md`](ROADMAP.md) for source coverage status.

## Status

**Currently implemented: Statistics Canada**, across its three public
APIs:

| Submodule | Tools | Covers |
|---|---|---|
| `wds` | 16 | Web Data Service — table/cube discovery, metadata, time series |
| `sdmx` | 4 | SDMX REST — filtered, server-side-sliced series queries |
| `rdaas` | 12 | Reference Data as a Service — classifications, codesets, concordances (e.g. NAICS) |

Every tool accepts `lang: "en"|"fr"` and returns a typed response with
a `provenance` block (source, URL, query time, freshness, limits). See
[`AGENTS.md`](AGENTS.md) for the full architecture and response
contract.

## Quick start

```bash
uv sync
```

**Connect to Claude Code:**

```bash
claude mcp add maple-data -- uv run --directory /path/to/maple-data-mcp python -m maple_data_mcp
```

**Run directly (stdio, for local MCP clients):**

```bash
MAPLE_TRANSPORT=stdio uv run python -m maple_data_mcp
```

**Run as a hosted HTTP server:**

```bash
MAPLE_TRANSPORT=http MAPLE_HOST=0.0.0.0 MAPLE_PORT=8000 uv run python -m maple_data_mcp
```

See [Hosting](#hosting) below for the full environment-variable
surface (auth, rate limiting, TLS).

## Using it

Tools are discovered through a search layer rather than listed flat —
call `search_tools` with a plain-language query, then `call_tool` with
the name it returns:

```json
{"name": "search_tools", "arguments": {"query": "consumer price index"}}
{"name": "call_tool", "arguments": {"name": "wds_search_cubes", "arguments": {"query": "consumer price index"}}}
```

Two example workflows, also available as guided MCP prompts
(`find_and_fetch_series`, `look_up_classification`,
`build_sdmx_or_key`):

- **Find and fetch a data series:** `wds_search_cubes` → `wds_get_cube_metadata`
  → `wds_get_series_info_from_cube_pid_coord` → `wds_get_data_from_vectors`.
- **Look up a classification:** `rdaas_search_classifications` →
  `rdaas_get_classification` → `rdaas_get_classification_categories_detailed`.

## Development

```bash
uv sync                          # install
uv run ruff check src tests      # lint
uv run ruff format src tests     # format
uv run pyright                   # type check
uv run pytest                    # unit tests (mocked, no network)
```

**Live verification** (hits the real StatCan APIs — needs outbound
HTTPS, not just mocks):

```powershell
.\scripts\verify.ps1
```

runs the full gate above plus [`scripts/smoke_test.py`](scripts/smoke_test.py)
against live endpoints, and (if Docker is installed) a build + `compose up`
+ health check.

See [`AGENTS.md`](AGENTS.md) for the full contributor guide, including
how to add a new source module.

## Hosting

| Env var | Default | Purpose |
|---|---|---|
| `MAPLE_TRANSPORT` | `http` | `stdio` or `http` |
| `MAPLE_HOST` / `MAPLE_PORT` | `127.0.0.1` / `8000` | HTTP bind address |
| `MAPLE_AUTH_TOKEN` | unset | Bearer token required on `/mcp` if set |
| `MAPLE_REQUIRE_AUTH` | `0` | Refuse to start without a token if `1` |
| `MAPLE_RATE_LIMIT_REQUESTS` / `MAPLE_RATE_LIMIT_WINDOW_SECONDS` | `120` / `60` | Per-client sliding-window rate limit |
| `MAPLE_MAX_CONCURRENT_REQUESTS` | `8` | Concurrency cap |
| `MAPLE_SSL_CERTFILE` / `MAPLE_SSL_KEYFILE` | unset | TLS termination in-process |

```bash
docker compose up --build
```

`GET /health` reports uptime and version; it bypasses auth/rate
limiting so it's always reachable.

## License

MIT

## Acknowledgments

The module architecture (per-source folders, auto-registered tools,
bilingual response envelope) and the hosting layer (Bearer auth,
sliding-window rate limiting, health checks) were informed by prior
open-source work building MCP servers for government and public data
— most directly **ReyemTech's `mcp-canada`** for the module pattern
and **DweskZ's `EcuDataMCP`** for the hosting middleware, alongside
the StatCan-specific benchmarks reviewed while researching this
project. Thank you to their authors for building in the open.
