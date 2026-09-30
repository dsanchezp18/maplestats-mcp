<p align="center">
  <img src="https://raw.githubusercontent.com/dsanchezp18/maplestats-mcp/main/site/assets/logo.svg" width="160" height="160" alt="MapleStats MCP logo: a white pixel maple leaf over the name maplestats-mcp on a red square">
</p>
<p align="center">
  <h1 align="center">MapleStats MCP</h1>
  <p align="center">
    <strong>One MCP server for Canadian open data.</strong>
  </p>
  <p align="center">
    <a href="https://pypi.org/project/maplestats-mcp/"><img src="https://img.shields.io/pypi/v/maplestats-mcp" alt="PyPI version"></a>
    <a href="https://pypi.org/project/maplestats-mcp/"><img src="https://img.shields.io/pypi/pyversions/maplestats-mcp" alt="Supported Python versions"></a>
    <a href="https://github.com/dsanchezp18/maplestats-mcp/blob/main/LICENSE"><img src="https://img.shields.io/github/license/dsanchezp18/maplestats-mcp" alt="License: MIT"></a>
    <a href="https://pypistats.org/packages/maplestats-mcp"><img src="https://img.shields.io/pypi/dm/maplestats-mcp" alt="PyPI downloads per month"></a>
    <a href="https://github.com/dsanchezp18/maplestats-mcp/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/dsanchezp18/maplestats-mcp/ci.yml?branch=main&label=CI" alt="CI status"></a>
    <a href="https://dsanchezp18.github.io/maplestats-mcp/"><img src="https://img.shields.io/github/actions/workflow/status/dsanchezp18/maplestats-mcp/pages.yml?branch=main&label=website" alt="Website build status"></a>
    <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff"></a>
    <a href="https://m8ven.ai/mcp/dsanchezp18/maplestats-mcp"><img src="https://m8ven.ai/badge/mcp/dsanchezp18/maplestats-mcp" alt="M8ven Score"></a>
    <a href="https://mcplookup.com/server/io.github.dsanchezp18/maplestats-mcp"><img src="https://mcplookup.com/badge/io.github.dsanchezp18/maplestats-mcp" alt="MCPLookup Trust Index"></a>
    <a href="https://glama.ai/mcp/servers/dsanchezp18/maplestats-mcp"><img src="https://glama.ai/mcp/servers/dsanchezp18/maplestats-mcp/badges/score.svg" alt="MapleStats MCP server quality and maintenance score on Glama"></a>
    <a href="https://smithery.ai/servers/dsanchezp998/maplestats-mcp"><img src="https://img.shields.io/badge/Smithery-listed-FF5601" alt="Listed on Smithery"></a>
    <a href="https://mcprush.com/dsanchezp18/maplestats-mcp"><img src="https://img.shields.io/badge/Mcprush-listed-B6F24B" alt="Listed on Mcprush"></a>
    <a href="https://lobehub.com/mcp/dsanchezp18-maplestats-mcp"><img src="https://img.shields.io/badge/LobeHub-listed-1F1F1F" alt="Listed on LobeHub"></a>
    <a href="https://www.piwheels.org/project/maplestats-mcp/"><img src="https://img.shields.io/badge/piwheels-Raspberry%20Pi-C51A4A" alt="Wheels for Raspberry Pi on piwheels"></a>
    <a href="https://registry.modelcontextprotocol.io/?q=io.github.dsanchezp18/maplestats-mcp"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fregistry.modelcontextprotocol.io%2Fv0%2Fservers%2Fio.github.dsanchezp18%252Fmaplestats-mcp%2Fversions%2Flatest&query=%24.server.version&label=MCP%20Registry&prefix=v&color=blue" alt="MCP Registry version"></a>
  </p>
</p>

<!-- mcp-name: io.github.dsanchezp18/maplestats-mcp -->

MapleStats MCP gives AI agents (Claude, Cursor and any MCP client) typed
access to Canadian open data through one server: Statistics Canada
(tables, Census, public use microdata), the Bank of Canada, CMHC, federal
agencies, and federal, provincial, territorial and municipal open-data
portals, in English and French. Every result carries its source.

*MapleStats MCP donne aux agents IA un accès structuré aux données
ouvertes canadiennes par un seul serveur, en français et en anglais.*

Project vision: [`docs/PROJECT_GUIDE.md`](https://github.com/dsanchezp18/maplestats-mcp/blob/main/docs/PROJECT_GUIDE.md).
Source coverage: [`docs/ROADMAP.md`](https://github.com/dsanchezp18/maplestats-mcp/blob/main/docs/ROADMAP.md).
Website: <https://dsanchezp18.github.io/maplestats-mcp/>.

## The easiest way: ask your agent

1. Copy this prompt.
2. Paste it into Claude Code, Codex, Cursor or any agent that can run
   commands on your computer.
3. Restart the agent when it says so, then ask for data.

> Connect the MapleStats MCP server to this agent. Follow the setup steps in https://github.com/dsanchezp18/maplestats-mcp

### Instructions for the agent doing the setup

The default is the hosted server: nothing to install, no account, no key.

1. Register this remote (HTTP) MCP server under the name `maplestats`:
   - **Claude Code:** `claude mcp add --transport http --scope user maplestats https://maplestats-mcp.onrender.com/mcp`
   - **Codex CLI:** `codex mcp add maplestats --url https://maplestats-mcp.onrender.com/mcp`
   - **Cursor, Claude Desktop and other `mcpServers` clients:** add the entry
     below to the client's config file (Cursor: `~/.cursor/mcp.json`; Claude
     Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json`
     on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows),
     keeping any servers already there.
   - **claude.ai and the Claude phone app:** on the web, open Settings →
     Connectors → Add custom connector, name it `MapleStats`, and enter
     `https://maplestats-mcp.onrender.com/mcp`. Then switch it on from the tools
     menu in a chat, on the web or in the phone app. Claude asks for approval
     before each call by default; every tool is read-only, so set them to
     always allow in the connector's tool permissions.
   - **ChatGPT (web):** turn on Settings → Security and login → Developer mode,
     then create a developer-mode app for a remote MCP server with the same
     address and No Authentication. Every tool is read-only, so ChatGPT
     should not ask to confirm calls. OpenAI documents this feature for the web.
   - **A whole organization:** on Claude Team or Enterprise, an Owner adds it once
     under Organization settings → Connectors → Add custom connector, and each
     member then connects it. On ChatGPT Business, Enterprise or Edu, an admin
     turns on Developer mode (Workspace Settings → Permissions & Roles →
     Connected Data), creates the app, and publishes it (Workspace settings →
     Apps → Drafts → Publish). The hosted server is a shared free instance, so
     a large organization should run its own copy.
   - **VS Code:** the same entry under a `servers` key, with `"type": "http"`,
     in `.vscode/mcp.json`.

   ```json
   {
     "mcpServers": {
       "maplestats": {
         "url": "https://maplestats-mcp.onrender.com/mcp"
       }
     }
   }
   ```
2. Tell the user to restart or reload the client, then check that the
   `search_tools` tool is listed.
3. Only if the client cannot use remote servers, or the user wants the
   microdata tabulation tool or everything kept on their own machine, run it
   locally instead: `claude mcp add --scope user maplestats -- uvx maplestats-mcp`
   (needs [uv](https://docs.astral.sh/uv/)), or the equivalent `uvx
   maplestats-mcp` entry for other clients (see [Install](#install)).

The hosted server is a free instance: the first request after a quiet spell can
take up to a minute, each client gets 60 requests a minute, and the microdata
tabulation tool is switched off there. Your agent's tool calls (a search phrase, a table number) reach the server and its host, Render, and the code stores none of them. Check Render's [terms](https://render.com/terms) and [privacy policy](https://render.com/privacy); for full privacy, run it locally. What it logs:
[FAQ](https://dsanchezp18.github.io/maplestats-mcp/faq.html#hosted). Other
clients: the [Connect](https://dsanchezp18.github.io/maplestats-mcp/connect.html)
page.

## Install locally (optional)

Prefer to run it on your machine? It works over stdio with no account or key.

```bash
uvx maplestats-mcp                 # run without installing
uv tool install maplestats-mcp     # or install the command once (pip works too)
uv tool upgrade maplestats-mcp     # update
```

For the development version: `uv tool install git+https://github.com/dsanchezp18/maplestats-mcp.git`.
If you installed the command, use `"command": "maplestats-mcp"` with no
`args` in the JSON above. On Windows, make sure the directory where `uv`
installs tools is on `PATH`, and restart the client afterwards.

## Using it

Tools are found through search rather than listed flat: call
`search_tools` with a plain-language query (English or French), then
`call_tool` with the name it returns.

```json
{"name": "search_tools", "arguments": {"query": "consumer price index"}}
{"name": "call_tool", "arguments": {"name": "wds_search_cubes", "arguments": {"query": "consumer price index"}}}
```

`plan_query` turns a question into an ordered, multi-source plan, and
`reproduce_code` writes the R, Python, Stata or Julia script that fetches
the same data straight from the source. Most tools accept `lang: "en"|"fr"`
(a documented no-op on single-language sources), and every response has a
`provenance` block: source, URL, query time, freshness and limits.
`docs://catalogue` describes every module in both languages.

## What it covers

About 230 tools. Run `docs://catalogue` for the full, bilingual list.

| Area | Tool prefixes | Covers |
|---|---|---|
| Statistics Canada | `wds_`, `sdmx_`, `rdaas_`, `statcan_*` | Tables and series, classifications, Census Profiles 2001–2021, public use microdata (codebooks, weighted tables), The Daily, indicators, surveys, census geography |
| Bank of Canada | `boc_` | Valet series, groups, observations |
| CMHC | `cmhc_`, `cmhc_dt_` | Housing Market Information Portal and Excel data tables |
| Federal agencies | `eccc_`, `ised_*`, `gazette_`, `tc_recalls_`, `recalls_`, `cdc_`, `cfia_`, `fcac_`, `cihi_`, `phac_infobase_`, `gc_infobase_`, `cer_`, `nrcan_*`, `dfo_iwls_`, `cgc_`, `ircc_*`, `pbo_`, `elections_financial_returns_`, `cra_digital_economy_registry_`, `earthquakes_`, `canadabuys_` | Weather and climate, corporations and IP, regulations, recalls, dairy, animal disease, consumer banking, health, spending, energy, oceans, grain, immigration, budgets, tenders |
| Wildland fire | `cwfis_` | NRCan's Canadian Wildland Fire Information System: satellite hotspots, fire danger and weather stations |
| Electricity | `electricity_ontario_`, `electricity_quebec_` | IESO (Ontario) demand, generation and prices; Hydro-Québec demand, generation and trade (CC BY-NC 4.0: credit Hydro-Québec, non-commercial use only) |
| Parliament | `parliament_`, `senate_` | Bills, votes, MPs, Hansard, committees |
| Provincial agencies | `aer_`, `bcgw_`, `ab_economic_`, `isq_` | Alberta Energy Regulator, BC Geographic Warehouse, Alberta Economic Dashboard, Institut de la statistique du Québec |
| Open-data portals | `ckan_`, `arcgis_hub_`, `socrata_` + `portal` | Federal, provincial, territorial and municipal catalogues (`*_list_portals` names each one) |
| Other municipal | `opendatasoft_vancouver_`, `nl_opendata_`, `eps_`, `ets_`, `epcor_` | Vancouver, Newfoundland and Labrador, Edmonton police, transit and water quality |

Other federal series (CRA, OSFI, ISED insolvency) are ordinary
open.canada.ca datasets, reachable with
`ckan_search_datasets(portal="federal", fq="organization:<org>")`.

## Development

```bash
uv sync                          # install
uv run ruff check src tests      # lint
uv run ruff format src tests     # format
uv run pyright                   # type check
uv run pytest                    # unit tests (mocked, no network)
```

`.\scripts\verify.ps1` runs that gate plus every `scripts/smoke_test*.py`
against the live APIs. The website is generated from the tool registry:
`uv run python scripts/build_site.py` writes `build/site/`. See
[`AGENTS.md`](https://github.com/dsanchezp18/maplestats-mcp/blob/main/AGENTS.md)
for the contributor guide and how to add a source module.

## Hosting

`MAPLE_TRANSPORT=http MAPLE_HOST=0.0.0.0 MAPLE_PORT=8000 uv run maplestats-mcp`
serves HTTP instead of stdio; `docker compose up --build` does the same in
Docker. Docker is optional and unnecessary on a personal computer. If the
server is exposed beyond your machine, set `MAPLE_AUTH_TOKEN` and keep
`MAPLE_REQUIRE_AUTH=1`. `GET /health` reports uptime and version.

| Env var | Default | Purpose |
|---|---|---|
| `MAPLE_TRANSPORT` | `stdio` | `stdio` for local clients, `http` for hosting |
| `MAPLE_HOST` / `MAPLE_PORT` | `127.0.0.1` / `8000` | HTTP bind address |
| `MAPLE_AUTH_TOKEN`, `MAPLE_REQUIRE_AUTH` | unset, `0` | Bearer token required on `/mcp`; refuse to start without one if `1` |
| `MAPLE_RATE_LIMIT_REQUESTS` / `MAPLE_RATE_LIMIT_WINDOW_SECONDS` | `120` / `60` | Per-client rate limit |
| `MAPLE_MAX_CONCURRENT_REQUESTS` | `8` | In-flight request cap; the excess waits 5 s, then gets 503 |
| `MAPLE_SSL_CERTFILE` / `MAPLE_SSL_KEYFILE` | unset | TLS in-process |
| `MAPLE_TRUST_PROXY_HEADERS` | `0` | Rate-limit on `X-Forwarded-For`; only behind a proxy that sets it |
| `MAPLE_CACHE_MAX_ENTRIES` | `2000` | Response cache size per TTL bucket |
| `MAPLE_TOOL_TIMEOUT_SECONDS` | `120` | Longest a tool call may run |
| `MAPLE_PUMF_TABULATE` | `1` | `0` hides `statcan_pumf_tabulate` (it downloads whole PUMF ZIPs); search, listings and codebooks stay |
| `MAPLE_PUMF_CACHE_DIR`, `MAPLE_PUMF_CACHE_MAX_GB` | system temp, `5` | Downloaded microdata cache; use a persistent volume when hosted |
| `MAPLE_IP_HORIZONS_CACHE_DIR`, `MAPLE_IP_HORIZONS_CACHE_MAX_GB` | system temp, `3` | CIPO patent table cache |

## License

MIT

## Acknowledgments

MapleStats owes its architecture to
[EcuDataMCP](https://github.com/DweskZ/EcuDataMCP), my MCP server for
Ecuador's open data, and its module pattern to ReyemTech's `mcp-canada`.
Its approach to Canadian data owes much to the R developers who got there
first: Jens von Bergmann
([mountainMath](https://github.com/mountainMath)) and his co-authors,
Thierry Warin ([statcanR](https://github.com/warint/statcanR)), Valentin
Lucet ([rgovcan](https://github.com/VLucet/rgovcan)), and others. Thanks
to them, and to everyone who publishes Canadian data in the open.

For other ways to get Canadian data, see the
[alternatives](https://dsanchezp18.github.io/maplestats-mcp/about.html#alternatives).
