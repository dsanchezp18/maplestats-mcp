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

*MapleData MCP donne aux agents IA (Claude, Cursor et tout client
compatible MCP) un accès structuré et typé aux données publiques
canadiennes par l'entremise d'un seul serveur — couvrant Statistique
Canada, la Banque du Canada, ainsi que des portails CKAN fédéraux,
provinciaux, territoriaux et municipaux vérifiés.*

See [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md) for the project vision and
[`ROADMAP.md`](ROADMAP.md) for source coverage status.

## Bilingual by design / Conçu pour être bilingue

Tools accept `lang: "en"|"fr"`, several sources are French-first
or French-only (Quebec's `ckan_qc_*` and Montreal's `ckan_montreal_*`),
and tool discovery works in either language: every tool's docstring
carries both a `Keywords:` line and a `Mots-clés:` line, so calling
`search_tools` with a French-language query (e.g. *"recherche de
jeux de données sur le climat"*) finds the same tools an equivalent
English query would. Read `docs://catalogue` for a bilingual
(EN/FR) one-line description of every module. Not every underlying
government portal is itself bilingual — see each module's own
docstring (or `docs://catalogue`) for where `lang` genuinely changes
the response versus where it is a documented no-op on a monolingual
source.

*Chaque outil accepte `lang : "en"|"fr"`, plusieurs sources sont
francophones ou exclusivement en français (le `ckan_qc_*` du Québec
et le `ckan_montreal_*` de Montréal), et la découverte d'outils
fonctionne dans les deux langues : chaque outil porte à la fois une
ligne `Keywords:` et une ligne `Mots-clés:`, de sorte qu'un appel à
`search_tools` avec une requête en français trouve les mêmes outils
qu'une requête équivalente en anglais. Consultez `docs://catalogue`
pour une description bilingue (EN/FR) de chaque module. Tous les
portails gouvernementaux sous-jacents ne sont pas eux-mêmes
bilingues — consultez la documentation de chaque module (ou
`docs://catalogue`) pour savoir où `lang` change réellement la
réponse et où il s'agit d'un no-op documenté sur une source
unilingue.*

## Status

About 200 tools across these sources (run `docs://catalogue` for a
bilingual one-line description of each module):

| Area | Tool prefixes | Covers |
|---|---|---|
| Statistics Canada | `wds_`, `sdmx_`, `rdaas_`, `statcan_*` | Tables and series, classifications (e.g. NAICS), 2001–2021 Census Profiles, The Daily, indicators, daily bulk-update files, definitions/methods and analysis catalogues, survey directory and IMDB metadata, census geography, SDG hub |
| Bank of Canada | `boc_` | Valet series, groups, observations |
| CMHC | `cmhc_`, `cmhc_dt_` | Housing Market Information Portal tables; Excel data tables |
| ECCC / MSC | `eccc_` | Weather, climate, hydrometric, air quality (OGC API) |
| ISED | `ised_corporations_`, `ised_spectrum_`, `ised_cipo_` | Federal corporations, spectrum licences, trademarks |
| Other federal | `ircc_`, `elections_financial_returns_`, `cra_digital_economy_registry_`, `nrcan_nbac_`, `canadabuys_` | Express Entry draws, candidate financial returns, digital platform operators, burned areas, federal tenders, contract awards and contract history |
| Provincial agencies | `aer_`, `bcgw_` | Alberta Energy Regulator; BC Geographic Warehouse |
| CKAN catalogues | `ckan_` (federal), `ckan_ab_`, `ckan_bc_`, `ckan_on_`, `ckan_qc_`, `ckan_nt_`, `ckan_yt_`, `ckan_montreal_`, `ckan_toronto_`, `ckan_regina_` | Dataset search/detail and, on most portals, DataStore row queries |
| ArcGIS Hub portals | `arcgis_hub_` + `portal` | 33 provinces, cities, regions, and agencies (`arcgis_hub_list_portals`) |
| Socrata portals | `socrata_` + `portal` | Nova Scotia, New Brunswick, Calgary, Edmonton, Winnipeg (`socrata_list_portals`) |
| Other municipal | `opendatasoft_vancouver_`, `nl_opendata_`, `eps_`, `ets_`, `epcor_` | Vancouver (Opendatasoft); Newfoundland and Labrador (HTML catalogue); Edmonton police occurrences, real-time transit (GTFS-RT), and EPCOR water quality |

Many federal administrative series (IRCC permits, CRA statistics and
charities, OSFI returns, ISED insolvency data) are ordinary open.canada.ca
datasets, reachable through `ckan_search_datasets(fq="organization:<org>")`.

Most tools accept `lang: "en"|"fr"` (a documented no-op on single-language
sources), and every tool returns a typed response with a `provenance`
block (source, URL, query time, freshness, limits). See
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

runs the full gate above plus every `scripts/smoke_test*.py` live smoke
test. If Docker is installed, it also
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
| `MAPLE_MAX_CONCURRENT_REQUESTS` | `8` | Cap on in-flight MCP requests (POST/DELETE); excess requests wait up to 5 s, then get 503. Long-lived GET event streams are not counted |
| `MAPLE_SSL_CERTFILE` / `MAPLE_SSL_KEYFILE` | unset | TLS termination in-process |
| `MAPLE_TRUST_PROXY_HEADERS` | `0` | Key rate limits on `X-Forwarded-For`; enable only behind a proxy that sets it |
| `MAPLE_CACHE_MAX_ENTRIES` | `2000` | Max entries per TTL bucket in the in-memory response cache |

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
