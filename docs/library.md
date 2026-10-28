# Using MapleStats as a Python library

MapleStats is an MCP server, but every source module is ordinary async
Python underneath. A script, a notebook or another application can import
the package and call the same functions the tools call, with no MCP client
and no server running.

> **Not a stable API yet.** Semantic versioning covers the MCP tools (their
> names, parameters and output fields; see `tests/test_tool_surface.py`).
> The Python module paths, function names and signatures described here can
> change in any release without a deprecation period. Pin an exact version
> (`maplestats-mcp==0.4.3`) if you build on them, and read the changelog when
> you upgrade.

## Install

```bash
uv add maplestats-mcp        # or: pip install maplestats-mcp
```

Python 3.12 or newer. No account or key is needed for any source.

## Three ways in

| Route | What you call | What you get |
|---|---|---|
| Client functions | `maplestats_mcp.modules.<source>/client.py` | The lowest level: one typed result per upstream call. |
| Tool functions | `maplestats_mcp.modules.<source>/tools.py` | The MCP tool's own function, with the same arguments (`lang`, transforms, limits) and return model. |
| In-process MCP | `fastmcp.Client(maplestats_mcp.server.mcp)` | Exactly what an MCP client gets, server middleware included. |

Each module is a folder under `src/maplestats_mcp/modules/`; a source with
several APIs has a subfolder per API (`statcan/wds`, `statcan/sdmx`,
`statcan/rdaas`, ...). The tool name's prefix tells you the folder:
`wds_get_data_from_vectors` is in `modules/statcan/wds/tools.py`, and it calls
`get_data_from_vectors_and_latest_n_periods` in
`modules/statcan/wds/client.py`. `docs://catalogue` (or the
[website](https://maplestats.danielstats.io/)) lists every module.

Client and tool functions are coroutines: call them with `await` inside an
event loop (`asyncio.run(...)` in a script; a Jupyter cell can `await`
directly).

## Example 1: StatCan series from the client

```python
import asyncio

from maplestats_mcp.modules.statcan.wds import client


async def main() -> None:
    # Consumer Price Index, all-items, Canada: vector 41690973 (table 18-10-0004-01)
    result = await client.get_data_from_vectors_and_latest_n_periods([41690973], 3)
    for series in result.series:
        for obs in series.observations:
            print(series.vector_id, obs.ref_period, obs.value, obs.status)
    print(result.failed)
    print(result.provenance.source, result.provenance.url)
    print(result.provenance.commercial_use, result.provenance.cached)


asyncio.run(main())
```

Output on 2026-10-28:

```text
41690973 2026-07-01 169.9 normal
41690973 2026-08-01 169.8 normal
41690973 2026-09-01 170.0 normal
[]
statcan-wds https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods
allowed False
```

`result` is a Pydantic model (`VectorDataSet`); `result.model_dump()` gives a
dict and `result.model_dump_json()` the JSON an MCP client would see.

## Example 2: Bank of Canada exchange rates, in French

Most clients take `lang="en"` or `lang="fr"`. French changes the labels, the
units and the provenance text where the source publishes French:

```python
import asyncio

from maplestats_mcp.modules.boc import client


async def main() -> None:
    fx = await client.get_observations(["FXUSDCAD"], recent=3, lang="fr")
    print(fx.series["FXUSDCAD"].label, "-", fx.series["FXUSDCAD"].unit)
    for row in fx.observations:
        print(row.ref_date, row.values["FXUSDCAD"])
    print(fx.provenance.as_of)
    print(fx.provenance.licence)


asyncio.run(main())
```

Output on 2026-10-28:

```text
USD/CAD - Dollars canadiens par dollar américain
2026-10-27 1.4038
2026-10-26 1.4025
2026-10-23 1.3993
2026-10-27 00:00:00+00:00
Conditions d'utilisation de la Banque du Canada (https://www.banqueducanada.ca/conditions-utilisation-avis/) : indiquer la Banque du Canada comme source et signaler toute modification, sans laisser entendre que la Banque approuve l'utilisation ; le contenu transmis par un service payant doit être présenté comme provenant du site Web de la Banque.
```

The Statistics Canada clients (`statcan/wds`, `statcan/sdmx`, ...) have no
`lang` argument; they read the language set with `client.use_lang("fr")`,
which lasts for the current asyncio task (example 4).

## Example 3: a tool function, with a transform

The tool functions take the same arguments as the MCP tools and do what the
tool does on top of the client, such as computing a change:

```python
import asyncio

from maplestats_mcp.modules.statcan.wds import tools


async def main() -> None:
    result = await tools.wds_get_data_from_vectors(
        [41690973], latest_n=13, transform="yoy_pct_change"
    )
    change = result.series[0].transformed
    assert change is not None
    print(change.formula, "|", change.unit)
    for point in change.points[-3:]:
        print(point)


asyncio.run(main())
```

Output on 2026-10-28:

```text
Computed by MapleStats: yoy_pct_change = 100 * (x_t / x_{t-12} - 1), t in months (the same period a year earlier, matched by date) | percent
period='2026-07' ref_date=datetime.date(2026, 7, 1) level=169.9 value=3.0321406913
period='2026-08' ref_date=datetime.date(2026, 8, 1) level=169.8 value=3.0339805825
period='2026-09' ref_date=datetime.date(2026, 9, 1) level=170.0 value=3.0927835052
```

## Example 4: errors, language and the cache

```python
import asyncio

from maplestats_mcp.modules.statcan.wds import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def main() -> None:
    try:
        await client.get_cube_metadata(99999999)
    except NotFound as exc:
        print("NotFound:", exc)

    client.use_lang("fr")  # WDS messages in French for this task
    try:
        await client.get_data_from_vectors_and_latest_n_periods([], 3)
    except InvalidInput as exc:
        print("InvalidInput:", exc)

    first = await client.get_data_from_vectors_and_latest_n_periods([41690973], 3)
    again = await client.get_data_from_vectors_and_latest_n_periods([41690973], 3)
    print(first.provenance.cached, again.provenance.cached)


asyncio.run(main())
```

Output on 2026-10-28:

```text
NotFound: getCubeMetadata: The cube product ID 99999999 does not exist. Error code = CUBE_NOT_AVAILABLE
InvalidInput: vector_ids ne doit pas être vide.
False True
```

## The same thing an MCP client gets

To get exactly what an MCP client receives (including the server's
middleware below), call the server in process with FastMCP's client:

```python
import asyncio

from fastmcp import Client

from maplestats_mcp.server import mcp


async def main() -> None:
    async with Client(mcp) as session:
        result = await session.call_tool(
            "call_tool",
            {"name": "boc_get_observations",
             "arguments": {"series_names": ["FXUSDCAD"], "recent": 2}},
        )
        print(result.structured_content["observations"])


asyncio.run(main())
```

Output on 2026-10-28 (trimmed):

```text
[{'ref_date': '2026-10-27', 'values': {'FXUSDCAD': 1.4038}, 'non_numeric': None}, {'ref_date': '2026-10-26', 'values': {'FXUSDCAD': 1.4025}, 'non_numeric': None}]
```

Here results are dicts, not models.

## Typed results and provenance

Every client and tool function returns a Pydantic model from the module's
`schemas.py`, and every model has a `provenance` field
(`maplestats_mcp.shared.models.Provenance`):

| Field | Meaning |
|---|---|
| `source`, `url` | The upstream API and the exact URL fetched |
| `queried_at`, `as_of` | When MapleStats asked, and the data's own reference or release date when the source gives one |
| `freshness`, `coverage`, `limits` | Update cadence; what the result leaves out; caps and truncation applied |
| `cached` | Whether the result came from MapleStats's cache |
| `licence` | The publisher's licence or terms and the attribution they ask for |
| `commercial_use` | `allowed`, `not_allowed` (non-commercial only, or written permission needed), `varies` (each dataset or feed has its own licence) or `unknown`; read `licence` for the conditions |
| `caveats` | Fitness-for-use cautions (filled by the server; see below) |

## What the server adds, and what you get without it

These apply in library use too, because they live in the shared helpers
every client calls:

- **Cache.** Responses are cached in memory, per process, with a lifetime
  per kind of request (`provenance.cached` says when a result came from
  it). `MAPLE_CACHE_MAX_ENTRIES` (default 2000 per lifetime bucket) and
  `MAPLE_CACHE_MAX_MB` (default 128) bound it. A new process starts empty.
- **Rate limits.** Each source has a token bucket at its documented or
  polite rate (StatCan WDS 20 requests a second, the Bank of Canada 10);
  calls past it wait rather than fail. They are per process.
- **Retries and the circuit breaker.** Timeouts, connection errors and 5xx
  answers are retried with backoff, honouring `Retry-After`. After
  repeated failures a host is paused for a cooldown and calls to it raise
  `UpstreamUnavailable` at once (`MAPLE_BREAKER=0` turns this off;
  `MAPLE_BREAKER_FAILURES`, `MAPLE_BREAKER_WINDOW_SECONDS` and
  `MAPLE_BREAKER_COOLDOWN_SECONDS` tune it).
- **File parsing.** `MAPLE_PARSE_WORKERS` and `MAPLE_PARSE_TIMEOUT_SECONDS`
  bound the threads that read Excel and CSV files; the cache folders
  (`MAPLE_PUMF_CACHE_DIR`, `MAPLE_LODE_CACHE_DIR`, ...) and
  `MAPLE_DUCKDB_MEMORY_LIMIT` apply as on the server.

These belong to the server and are skipped when you call a client or tool
function directly (the in-process MCP route keeps them):

- the byte budget per result (`MAPLE_RESPONSE_MAX_BYTES`): a direct call
  returns every row the function fetched;
- `provenance.caveats`, filled from the fitness-for-use rules
  (`docs://planner/fitness-rules`): empty on a direct call;
- the per-call time limit (`MAPLE_TOOL_TIMEOUT_SECONDS`), and the
  per-client rate limit and concurrency cap of the HTTP server.

The [README's settings table](../README.md#hosting) lists every
`MAPLE_*` variable. Set them in the environment before the first call.

## Errors

Failures are raised, never returned. The classes are in
`maplestats_mcp.shared.errors`, all subclasses of `ValueError`:

| Class | Meaning | What to do |
|---|---|---|
| `InvalidInput` | An argument the function cannot act on | Fix the call; the message names the argument |
| `NotFound` | The source has no matching record | Check the identifier, or search first |
| `UpstreamUnavailable` | Network error, timeout, 5xx, or a paused host (`CloudflareChallenge` is a kind of it) | Retry later |
| `UpstreamError` | The source answered in an unexpected shape | Report it: the source may have changed |
| `DataLocked` | StatCan WDS during its nightly update (midnight to 8:30 ET) | Retry after the time the message gives |

Messages follow the call's language (`lang="fr"`, or `use_lang("fr")` for
the StatCan clients).
