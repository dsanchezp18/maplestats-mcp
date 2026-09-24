# AGENTS.md — working guide for this repository

This is the canonical guide for any agent (or human) contributing code
to MapleData MCP. `CLAUDE.md` in this repo intentionally carries no
independent content — it points here.

Read [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md) and [`ROADMAP.md`](ROADMAP.md)
first for project scope and source status. This file is about *how*
to build things here, not *what* to build.

## Architecture

### Module layout

Every data source is a folder under `src/maple_data_mcp/modules/`:

```
modules/<source>/
  __init__.py      # MODULE_NAME + MODULE_DESCRIPTION (+ _FR)
  constants.py     # BASE_URL, rate limit, cache TTLs
  schemas.py       # typed Pydantic response models
  client.py        # async functions -> typed model (or raise)
  tools.py         # @tool functions, one per client function
  resources.py       # (optional) zero-parameter docs:// resources
  prompts.py          # (optional) guided-workflow prompts
  __tests__/
```

A source with more than one distinct sub-API splits into subfolders
instead, each with its own `constants.py`/`schemas.py`/`client.py`/
`tools.py` — see `modules/statcan/{wds,sdmx,rdaas}/` for the pattern.
The top-level `statcan/__init__.py`, `resources.py`, and `prompts.py`
stay shared across the sub-APIs.

A new portal on a platform this server already covers (ArcGIS Hub,
Socrata, CKAN) is **not** a new module: add one entry to that family's
`constants.PORTALS` (and its `PortalKey` literal in `schemas.py` — a
unit test keeps the two in sync). `modules/arcgis_hub/`,
`modules/socrata/`, and `modules/ckan/` replaced 28, 5, and 10
copy-pasted per-portal modules whose code differed only in
configuration; one tool family with a
`portal` argument also keeps `search_tools` from returning several
indistinguishable per-city tools.

`modules/_example/` is the literal template — copy it, don't reinvent
the pattern. It is underscore-prefixed on purpose: `server.py` adds
one `FileSystemProvider` per `modules/*` directory and explicitly
skips any name starting with `_`, since `FileSystemProvider` itself
has no built-in convention for "don't register this one live."

### Registration and tool discovery

`server.py` builds one `FastMCP` instance, adds a `FileSystemProvider`
per module directory (auto-discovers every `@tool`/`@resource`/
`@prompt`-decorated function, recursing into submodule subfolders —
confirmed working for the `statcan/{wds,sdmx,rdaas}/` split), and adds
a `BM25SearchTransform`. The practical effect: the server exposes only
two tools directly, `search_tools` and `call_tool` — every per-source
tool is discovered by natural-language query through `search_tools`
and invoked through `call_tool`. Don't design a new tool assuming a
client sees it in a flat list; write its docstring so it's findable.

### Response contract

Every tool's return type annotation is a Pydantic `BaseModel` (never
a plain `dict`). Confirmed directly against the installed `fastmcp`
version: when the return type is a `BaseModel`, FastMCP derives
`outputSchema` from its JSON schema and populates `structuredContent`
from the returned instance automatically. **Just `return SomeModel(...)`
— do not hand-build an envelope dict.**

Every response model embeds a `provenance: Provenance` field
(`shared/models.py`) built via `shared/envelope.py::make_provenance()`
— source name, URL, query timestamp, and (where known) as-of date,
freshness, coverage, and limits.

**Errors are raised, never returned.** Raising a plain exception from
a tool propagates as a real MCP `isError: true` result with the
exception message as content — confirmed via an in-memory client call.
Use the typed exceptions in `shared/errors.py` (`InvalidInput`,
`NotFound`, `UpstreamError`, `UpstreamUnavailable`, `DataLocked`) via
`shared/envelope.py::raise_error()`. **Never return a dict shaped like
an error** (`{"error": "..."}`) from a tool — that looks like a
success to a client checking `isError`.

## Three things that look removable and are not

1. **`http2=True` in `shared/http.py`'s client.** Diagnosed live
   against `statcan.gc.ca`: a plain `httpx`/`httpcore` client's
   default (`http2=False`) sends a TLS `ClientHello` whose ALPN
   extension offers only `"http/1.1"`, and something on StatCan's
   network path blocks exactly that fingerprint. The connection still
   negotiates and transacts over HTTP/1.1 either way — `http2=True`
   only changes what's *offered* during the handshake. Removing it
   reintroduces a real, silent connection failure to this project's
   primary data source. `h2` is a pinned dependency because of this,
   not an optional extra.
2. **`shared/json_utils.py::list_or_empty()`.** `dict.get(key, [])`
   only applies its default when `key` is *absent* — several
   government JSON APIs send the key with an explicit `null` instead
   (confirmed live: StatCan WDS's `surveyCode`/`subjectCode` on some
   cubes). Use `list_or_empty(obj, key)` for any list-typed field
   pulled from an external API, not a bare `.get(key, [])`.
3. **`tzdata` as a pinned dependency.** Windows Python has no system
   IANA timezone database — `zoneinfo.ZoneInfo("America/Toronto")`
   raises `ZoneInfoNotFoundError` without it. Needed wherever a client
   computes "today" in a source's own reference timezone rather than
   the host machine's local time (see `wds/client.py`'s
   `get_changed_cube_list`).

## A lesson from auditing the StatCan module after it "worked"

The initial build exercised only 2 of 32 StatCan tools against the
real API before being called done (the rest were unit-tested against
hand-written mock fixtures). A later pass that actually called all 32
tools live found **9 more real bugs** the mocks had no way to catch,
because the mocks were shaped by the same assumptions that were wrong:
wrong field names for 4 of 10 `getCodeSets` categories, a footnote
field assumed to be `list[str]` when it's really a list of objects,
two WDS methods needing a request body shaped differently than every
other WDS POST method, two methods with opposite date-parameter
requirements from what was assumed, an RDaaS filters endpoint
returning a list where a dict was assumed, and 404/406 responses
propagating as raw `HTTPStatusError` instead of the typed errors they
were supposed to become.

**The rule this leaves behind:** before considering any client.py
done, write a throwaway script that calls every function it exports
against the real API with realistic arguments — not just the 1-2 a
smoke test happens to cover — and read every failure. A clean
`pytest` run against mocks you wrote yourself only proves the code
does what you assumed the API does; it cannot catch a wrong
assumption shared by the code and its tests.

## Adding a new source module

1. Copy `modules/_example/` to `modules/<source>/`, rename functions
   and constants.
2. Research the real API against live responses where possible —
   field names in this codebase are verified against actual payloads,
   not guessed from documentation prose (see the `statcan` submodules'
   docstrings for what that verification looks like and why it
   mattered: several real fields differed from published specs).
3. Write typed Pydantic models in `schemas.py` for every distinct
   response shape, each embedding `provenance: Provenance`.
4. Write `client.py`: use `shared/http.py`'s `api_get`/`api_post`/
   `get_raw` (never a bare `httpx` call; when a source genuinely needs
   its own cookie jar, redirect following, or `http2=False`, create its
   client with `shared/http.py::new_client()`, not `httpx.AsyncClient`), `shared/rate_limiter.py`'s
   `get_limiter(source, rate, capacity)` for the source's documented
   rate limit, and `shared/cache.py`'s `cached_fetch` for anything
   cacheable. Raise typed errors; never return error-shaped dicts.
5. Write `tools.py`: one `@tool` per client function, each with a
   `lang: Literal["en", "fr"] = "en"` parameter and a docstring
   containing `Use for:`, `Keywords:` (8+ keywords), and `Mots-clés :`
   (a French equivalent set of 8+ terms, not a literal word-for-word
   translation — real French search terms a francophone user would
   type) lines — this is what `BM25SearchTransform` indexes on for
   discovery, and `Mots-clés :` is what lets a French-language query
   find the tool at all.
6. Add `__tests__/test_client.py` using `pytest-httpx`'s `httpx_mock`
   fixture (it mocks httpx at the transport level, including
   module-level singleton clients — confirmed working here). Cover
   real-world quirks the live API actually has, not just the happy
   path.
7. Add live steps for every tool to `scripts/smoke_test_modules.py`
   (or write a dedicated `scripts/smoke_test_<module>.py`), and run
   them. `tests/test_live_coverage.py` fails for a module with
   neither: the Earthquakes Canada module passed all its mocked tests
   while every live call failed.
8. Run the full gate below before considering it done.

## Development commands

```bash
uv sync                          # install
uv run ruff check src tests      # lint
uv run ruff format src tests     # format
uv run pyright                   # type check — must be 0 errors
uv run pytest                    # unit tests, all mocked, no network
```

The root `conftest.py` removes tenacity's retry backoff and the
per-source rate-limit waits in tests (retry counts and rules are
unchanged), which keeps the mocked suite at seconds rather than
minutes. Don't add real `sleep`s to tests to compensate.

**Before merging a change touching a client.py**, also run the live
smoke test — mocked tests cannot catch a real API's actual quirks
(they proved this twice already: the ALPN/TLS issue and the
null-vs-absent-list bug above were both only found by hitting the
real API):

```powershell
.\scripts\verify.ps1
```

or directly:

```bash
uv run python scripts/smoke_test.py
```

## Style

- `snake_case` everywhere; module-prefixed tool names (`wds_*`,
  `sdmx_*`, `rdaas_*`).
- Docstrings on tools always have `Use for:`, `Keywords:`, and
  `Mots-clés :` lines.
- Comments explain *why*, not *what* — especially for anything ported
  from or verified against a live API response; state what was
  confirmed and how, so a future edit doesn't silently regress a
  fix for a real quirk.
- `SERVER_INSTRUCTIONS` in `server.py` is sent to every client on
  every session: keep it a short routing index (add the new prefix to
  it), and put per-source detail in tool docstrings, the module's
  `MODULE_DESCRIPTION` (surfaced by the generated `docs://catalogue`),
  or a `docs://` resource.
- A source that needs a session warm-up (a cookie set by an earlier
  request) must also detect a *lost* session on every response, not
  only warm up once per process: server-side sessions expire, and
  these portals answer an expired session with a normal-looking page
  (an empty form, an unfiltered listing), not an error. Re-warm once
  and retry, then raise — never return or cache that page as a result.
  See `statcan/reference`, `statcan/surveys`, and
  `elections_financial_returns` for the pattern.
- No CLI companion yet (deferred by design, see `PROJECT_GUIDE.md`).

## Acknowledgments

See [`README.md`](README.md#acknowledgments) for credit to the prior
open-source work this architecture draws on.
