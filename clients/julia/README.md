# MapleStats.jl

A small Julia client for the hosted [MapleStats MCP](https://maplestats.danielstats.io/)
server: Canadian open data from Statistics Canada, the Bank of Canada, CMHC,
provincial agencies and city portals, returned as DataFrames with their
citation in the frame's metadata. It calls the server's `/mcp` endpoint with
HTTP.jl and needs no MCP SDK. Design: [`docs/clients.md`](../../docs/clients.md).

Not in the General registry yet. Install from GitHub:

```julia
using Pkg
Pkg.add(; url="https://github.com/dsanchezp18/maplestats-mcp", subdir="clients/julia")
```

## Use

```julia
using MapleStats

# Find a tool: name, description and input schema, best match first
search_tools("bank of canada exchange rate")

# Run it and get rows
usd_cad = get_data("boc_get_observations"; series_names=["FXUSDCAD"], recent=5)
metadata(usd_cad, "citation")
metadata(usd_cad, "provenance").licence

# A StatCan series carries its own citation (table, vector, release date)
unemployment = get_data("wds_get_data_from_vectors"; vector_ids=[2062815], latest_n=12)
metadata(unemployment, "citation")

# The raw result, as the server returns it (a JSON3.Object)
call_tool("boc_get_observations"; series_names=["FXUSDCAD"], recent=5)

# Which tools to call for a question that spans sources
plan_query("How has rent in Calgary changed against wages?")

# A script that fetches the same data straight from the publisher, for a
# replication package
code = reproduce_code(
    "boc_get_observations", Dict("series_names" => ["FXUSDCAD"], "recent" => 5)
)
write("code/cleaning/00_download_boc.jl", code.scripts[1].code)
```

`get_data` takes the result's largest list of objects as the rows (a series'
observations become one row each, carrying the series' fields), turns nested
fields into `parent_child` columns and cleans names to snake_case, as
TidierData's `@clean_names` does. JSON `null` becomes `missing`; other values
keep their JSON types, so dates stay text. The metadata keys are `"citation"`,
`"provenance"`, `"left_out"` (fields of the result beside the rows), `"tool"`
and `"arguments"`, all with style `:note`.

Errors throw `MapleStatsError` with the server's message, which says how to fix
the call. When the hosted server's limit of 60 requests a minute is hit,
`retry_after` holds the seconds to wait.

## Settings

| Setting | Default |
|---|---|
| `Client(; url=...)` or `MAPLESTATS_URL` | `https://mcp.maplestats.danielstats.io/mcp` |
| `Client(; token=...)` or `MAPLESTATS_TOKEN` | none (only a self-hosted server with `MAPLE_AUTH_TOKEN` needs one) |
| `Client(; timeout=...)` | 240 s (the hosted server lets a call run 230 s) |

```julia
local_server = Client(; url="http://127.0.0.1:8000/mcp")
search_tools("rent Calgary"; client=local_server)
```

## Develop

```julia
using JuliaFormatter; format(".")      # .JuliaFormatter.toml: blue style
using Pkg; Pkg.test()                   # recorded responses, no network
```

Set `MAPLESTATS_LIVE=1` to add one call to the hosted server. The recorded
responses in `test/fixtures/` come from `clients/record_fixtures.py`, which
refreshes the fixtures of every client.
