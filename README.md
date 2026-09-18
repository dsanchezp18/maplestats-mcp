<p align="center">
  <h1 align="center">🍁 MapleData MCP</h1>
  <p align="center">
    <strong>One MCP server for Canadian public data.</strong>
  </p>
</p>

MapleData MCP gives AI agents (Claude, Cursor, and any MCP-compatible
client) structured, typed access to Canadian public data through a
single server — covering Statistics Canada, the Bank of Canada, and
verified federal, provincial, territorial, and municipal CKAN portals.

See [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md) for the project vision and
[`ROADMAP.md`](ROADMAP.md) for source coverage status.

## Status

**Currently implemented:** Statistics Canada, the Bank of Canada, and
CKAN catalogues for the federal government, Alberta, British Columbia,
Ontario, Quebec, the Northwest Territories, Yukon, Montreal, and
Toronto.

| Submodule | Tools | Covers |
|---|---|---|
| `wds` | 16 | Web Data Service — table/cube discovery, metadata, time series |
| `sdmx` | 4 | SDMX REST — filtered, server-side-sliced series queries |
| `rdaas` | 12 | Reference Data as a Service — classifications, codesets, concordances (e.g. NAICS) |

The Bank of Canada module provides Valet series, group, metadata, and
observation tools. The CKAN modules provide dataset search plus dataset,
organization, resource, license, tag, and (where used by the portal)
group details. Portal language behavior is documented in each module;
`lang` is a no-op on monolingual catalogues.

Every tool accepts `lang: "en"|"fr"` and returns a typed response with
a `provenance` block (source, URL, query time, freshness, limits). See
[`AGENTS.md`](AGENTS.md) for the full architecture and response
contract.

## Install locally (no Docker required)

Install the command directly from GitHub with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/dsanchezp18/maple-data-mcp.git
```

The command is now available on your `PATH`:

```bash
maple-data-mcp
```

It speaks MCP over **stdio** by default, which is the format local MCP
clients expect. The process is started by the client; do not open a port and
do not run Docker.

To update an existing installation:

```bash
uv tool upgrade maple-data-mcp
```

If you are working from a clone instead:

```bash
uv sync
uv run maple-data-mcp
```

### MCP client configuration

For clients that accept a standard `mcpServers` JSON configuration, add:

```json
{
  "mcpServers": {
    "maple-data": {
      "command": "maple-data-mcp"
    }
  }
}
```

For Claude Code:

```bash
claude mcp add maple-data -- maple-data-mcp
```

On Windows, make sure the directory where `uv` installs tools is on `PATH`,
then restart the MCP client after installation.

## Development quick start

```bash
uv sync
```

**Run directly from a checkout (stdio, for local MCP clients):**

```bash
uv run maple-data-mcp
```

**Run as a hosted HTTP server:**

```bash
MAPLE_TRANSPORT=http MAPLE_HOST=0.0.0.0 MAPLE_PORT=8000 uv run maple-data-mcp
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

runs the full gate above plus the live smoke tests for StatCan, the Bank of
Canada, and every implemented CKAN portal. If Docker is installed, it also
runs a build, `compose up`, and health check.

See [`AGENTS.md`](AGENTS.md) for the full contributor guide, including
how to add a new source module.

## Hosting

| Env var | Default | Purpose |
|---|---|---|
| `MAPLE_TRANSPORT` | `stdio` | `stdio` for local MCP clients; `http` for hosting |
| `MAPLE_HOST` / `MAPLE_PORT` | `127.0.0.1` / `8000` | HTTP bind address |
| `MAPLE_AUTH_TOKEN` | unset | Bearer token required on `/mcp` if set |
| `MAPLE_REQUIRE_AUTH` | `0` | Refuse to start without a token if `1` |
| `MAPLE_RATE_LIMIT_REQUESTS` / `MAPLE_RATE_LIMIT_WINDOW_SECONDS` | `120` / `60` | Per-client sliding-window rate limit |
| `MAPLE_MAX_CONCURRENT_REQUESTS` | `8` | Concurrency cap |
| `MAPLE_SSL_CERTFILE` / `MAPLE_SSL_KEYFILE` | unset | TLS termination in-process |

```bash
MAPLE_TRANSPORT=http MAPLE_REQUIRE_AUTH=0 docker compose up --build
```

Docker is an optional deployment method. For a personal computer, use the
local installation above. If the HTTP server is exposed beyond the local
machine, set `MAPLE_AUTH_TOKEN` and keep `MAPLE_REQUIRE_AUTH=1`.

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
