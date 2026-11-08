"""Recorded tool exchanges for a subset of Maple Test questions, replayed offline in CI.

A Maple Test run needs a model and the live sources, so it cannot guard a pull request.
This file records, once, the MapleStats tool call that answers each question in `CASES`:
the call as a model makes it (through `call_tool`), every HTTP exchange the server had
with StatCan or the Bank of Canada, and the result the model read. `tests/test_maple_test
_replay.py` then runs the same calls against this checkout with the recorded HTTP served
by pytest-httpx, so no source and no model is called, and fails if:

- the result differs from the recorded one (a value, a citation, a caveat, the shape);
- a figure the answer key cites is no longer in the result (the check that matters for
  grading: an answer can only be right if the tool result holds the key's figure);
- the server asks a source for something that was not recorded (a changed request).

Recording checks the live result against the answer key first and refuses to write a
fixture that does not hold the key's figures: a revised source means the key needs a
rebuild (`build_key --check`), not a fixture that hides it.

    uv run python -m tests.maple_test.replay record   # needs the network; rewrites replay/

Re-record when a change to the server is meant to change these results, read the diff of
`replay/*.json` in the pull request, and say why it changed. Re-record also after
`build_key`/`build_key_v2` rebuilds a key these questions use.
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import json
import math
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from tests.maple_test.grade import load_key

HERE = Path(__file__).resolve().parent
REPLAY = HERE / "replay"
HTTP_STORE = REPLAY / "http.json.gz"

# Response headers kept with each recorded body. The body is stored decoded, so
# content-encoding and content-length must not be replayed; date, server and cookies
# change on every request and no client here reads them.
KEPT_HEADERS = ("content-type", "content-disposition", "etag", "last-modified", "location")
# Fields that differ on every call whatever the server does.
VOLATILE = frozenset({"queried_at"})


@dataclass(frozen=True)
class Case:
    """One question, the tool call that answers it, and what the result must hold.

    `cite` checks every citation in the key that names a vector or Valet series and a
    numeric value. `transformed` maps an `expected` key to (series, period) for a computed
    value. `absent` lists (series, period) pairs that must not be in the result (a refusal
    is right only because the figure is not published). `latest` maps an `expected` key to
    the series whose last observation must be that period.
    """

    question_id: str
    version: str
    tool: str
    arguments: dict[str, Any]
    cite: bool = True
    transformed: dict[str, tuple[str, str]] = field(default_factory=dict)
    absent: tuple[tuple[str, str], ...] = ()
    latest: dict[str, str] = field(default_factory=dict)


# StatCan vectors and Valet series only: those are the questions most arms compete on,
# and the ones whose results carry the citation the grader reads. Each call is the one a
# model makes for the question (the v2 runs show these tools through call_tool).
CASES = (
    Case("M-01", "v1", "wds_get_data_from_vectors", {"vector_ids": [2062815], "latest_n": 14}),
    Case(
        "M-07",
        "v1",
        "wds_get_data_from_vectors",
        {"vector_ids": [108785715, 108785714], "latest_n": 2},
    ),
    Case("M-09", "v1", "wds_get_data_from_vectors", {"vector_ids": [87008984], "latest_n": 4}),
    Case(
        "M-11",
        "v1",
        "boc_get_observations",
        {"series_names": ["FXUSDCAD"], "start_date": "2026-10-30", "end_date": "2026-10-30"},
    ),
    Case(
        "M-12",
        "v1",
        "boc_get_observations",
        {
            "series_names": ["BD.CDN.10YR.DQ.YLD"],
            "start_date": "2026-10-26",
            "end_date": "2026-10-30",
        },
    ),
    # A Sunday: the result must have the Friday and the Monday and nothing between.
    Case(
        "M-14",
        "v1",
        "boc_get_observations",
        {"series_names": ["FXUSDCAD"], "start_date": "2026-10-30", "end_date": "2026-11-02"},
        absent=(("FXUSDCAD", "2026-10-31"), ("FXUSDCAD", "2026-11-01")),
    ),
    Case(
        "C-01",
        "v2",
        "wds_get_data_from_vectors",
        {"vector_ids": [2063951, 2063762], "latest_n": 3},
    ),
    Case(
        "C-06",
        "v2",
        "wds_get_data_from_vectors",
        {"vector_ids": [41690973], "latest_n": 1, "transform": "yoy_pct_change"},
        cite=False,
        transformed={"allitems_yoy_pct": ("v41690973", "2026-09")},
    ),
    Case(
        "C-19",
        "v2",
        "boc_get_observations",
        {"series_names": ["V39079"], "start_date": "2026-10-23", "end_date": "2026-10-30"},
    ),
    # October 2026 CPI is not out (key built 2026-11-03; it comes out mid-November): the
    # latest observation must be September.
    Case(
        "C-22",
        "v2",
        "wds_get_data_from_vectors",
        {"vector_ids": [41690973], "latest_n": 2},
        absent=(("v41690973", "2026-10"),),
        latest={"latest_month": "v41690973"},
    ),
)


def question(case: Case) -> dict[str, Any]:
    return next(q for q in load_key(case.version) if q["id"] == case.question_id)


def fixture_path(case: Case) -> Path:
    return REPLAY / f"{case.question_id}.json"


# ---- reading a result -------------------------------------------------------------


def observations(result: dict[str, Any]) -> dict[tuple[str, str], float | None]:
    """(series, period) -> value, for WDS vector results and Valet observations.

    WDS series are keyed "v<vector>" with periods as WDS gives them ("2026-09-01"), Valet
    series by name with their dates.
    """
    found: dict[tuple[str, str], float | None] = {}
    series = result.get("series")
    if isinstance(series, list):
        for s in series:
            for o in s.get("observations") or []:
                found[(f"v{s['vector_id']}", o["ref_period"])] = o.get("value")
    for o in result.get("observations") or []:
        for name, value in (o.get("values") or {}).items():
            found[(name, o["ref_date"])] = value
    return found


def transformed(result: dict[str, Any]) -> dict[tuple[str, str], float | None]:
    """(series, period) -> computed value, from a WDS result's `transformed` blocks."""
    found: dict[tuple[str, str], float | None] = {}
    series = result.get("series")
    for s in series if isinstance(series, list) else []:
        for point in (s.get("transformed") or {}).get("points") or []:
            found[(f"v{s['vector_id']}", point["period"])] = point.get("value")
    return found


def lookup(
    values: dict[tuple[str, str], float | None], series: str, period: str
) -> list[float | None]:
    """Values of `series` whose period starts with `period` ("2026-09" finds "2026-09-01")."""
    return [v for (s, p), v in values.items() if s == series and p.startswith(period)]


def problems(case: Case, result: dict[str, Any]) -> list[str]:
    """What the result lacks for the key's answer to be readable from it; empty if fine.

    A brief result's CSV rows are read back as rows first.
    """
    from maplestats_mcp.shared.brief import expand_tables

    q = question(case)
    result = expand_tables(result)
    found = observations(result)
    out: list[str] = []
    if case.cite:
        for c in q["citations"]:
            vid, value = c.get("vector_id"), c.get("value")
            if not vid or not isinstance(value, int | float):
                continue
            got = lookup(found, vid, c["reference_period"])
            if not any(v is not None and math.isclose(v, value, abs_tol=1e-9) for v in got):
                out.append(f"{vid} {c['reference_period']}: key {value}, result {got or 'none'}")
    computed = transformed(result)
    for key, (series, period) in case.transformed.items():
        want = q["expected"][key]
        got = lookup(computed, series, period)
        # The key states the published rounding (one decimal); the tool computes more.
        if not any(v is not None and abs(v - want) <= 0.05 for v in got):
            out.append(f"{key} ({series} {period}): key {want}, computed {got or 'none'}")
    for series, period in case.absent:
        if lookup(found, series, period):
            out.append(f"{series} {period} should not be published, but the result has it")
    for key, series in case.latest.items():
        periods = sorted(p for s, p in found if s == series)
        want = q["expected"][key]
        if not periods or not periods[-1].startswith(want):
            out.append(f"{series}: latest should be {want}, result has {periods[-1:] or 'none'}")
    return out


def normalize(value: Any) -> Any:
    """The result without the fields that change on every call."""
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


# ---- HTTP --------------------------------------------------------------------------


def request_id(method: str, url: str, body: bytes) -> str:
    return hashlib.sha256(b"\n".join([method.encode(), url.encode(), body])).hexdigest()[:16]


def encoded(content: bytes) -> dict[str, str]:
    """A body as text when it is UTF-8 (all of these are JSON), which gzips far smaller."""
    try:
        return {"text": content.decode()}
    except UnicodeDecodeError:
        return {"base64": base64.b64encode(content).decode()}


def load_http() -> dict[str, dict[str, Any]]:
    return json.loads(gzip.decompress(HTTP_STORE.read_bytes()))


def response_kwargs(exchange: dict[str, Any]) -> dict[str, Any]:
    """`httpx_mock.add_response` arguments that serve one recorded exchange."""
    return {
        "method": exchange["method"],
        "url": exchange["url"],
        "match_content": exchange["body"].encode(),
        "status_code": exchange["status"],
        "headers": exchange["headers"],
        "content": (
            exchange["text"].encode()
            if "text" in exchange
            else base64.b64decode(exchange["base64"])
        ),
        "is_reusable": True,
    }


@contextmanager
def frozen_today(day: date) -> Iterator[None]:
    """Make the server's "today" the recording date.

    Results say when newer data exist relative to today ("Today is 2026-11-07; for the
    latest values pass recent"), so a replay on a later day would differ for no change in
    the server. Every module that imported `newer_data.today` gets the frozen one.
    """
    from maplestats_mcp.shared import newer_data

    real = newer_data.today
    patched = [
        m
        for name, m in list(sys.modules.items())
        if name.startswith("maplestats_mcp") and getattr(m, "today", None) is real
    ]
    for m in patched:
        m.today = lambda: day  # type: ignore[attr-defined]
    try:
        yield
    finally:
        for m in patched:
            m.today = real  # type: ignore[attr-defined]


async def call(case: Case, detail: str = "full") -> tuple[dict[str, Any], str]:
    """Run the case's tool through `call_tool`, as a model does; (structured, text).

    `detail` is call_tool's: fixtures hold the full result, which a brief one is
    checked against (tests/test_maple_test_replay.py).
    """
    from fastmcp import Client
    from mcp.types import TextContent

    from maplestats_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool(
            "call_tool", {"name": case.tool, "arguments": case.arguments, "detail": detail}
        )
    first = result.content[0]
    assert isinstance(first, TextContent)
    return result.structured_content or {}, first.text


# ---- recording ---------------------------------------------------------------------


async def record_all(commit: str) -> int:
    import httpx

    from maplestats_mcp.shared import cache, newer_data

    exchanges: dict[str, dict[str, Any]] = {}
    seen: list[str] = []
    real_send = httpx.AsyncHTTPTransport.handle_async_request

    async def recording(self: httpx.AsyncHTTPTransport, request: httpx.Request) -> Any:
        response = await real_send(self, request)
        content = await response.aread()
        body = request.content or b""
        rid = request_id(request.method, str(request.url), body)
        exchanges[rid] = {
            "method": request.method,
            "url": str(request.url),
            "body": body.decode(),
            "status": response.status_code,
            "headers": {k: v for k, v in response.headers.items() if k.lower() in KEPT_HEADERS},
            **encoded(content),
        }
        seen.append(rid)
        return response

    httpx.AsyncHTTPTransport.handle_async_request = recording  # type: ignore[method-assign]
    recorded_on = newer_data.today()
    fixtures: dict[Path, dict[str, Any]] = {}
    failed = 0
    for case in CASES:
        # Each case starts cold, as the replay does (conftest empties the caches per test),
        # so its recorded requests are all the ones it needs on its own.
        cache._caches.clear()
        cache._inflight.clear()
        seen.clear()
        structured, _ = await call(case)
        lacking = problems(case, structured)
        if lacking:
            failed += 1
            print(f"{case.question_id}: NOT RECORDED, the live result does not hold the key:")
            for line in lacking:
                print(f"  {line}")
            continue
        fixtures[fixture_path(case)] = {
            "question_id": case.question_id,
            "version": case.version,
            "recorded_on": recorded_on.isoformat(),
            "server_commit": commit,
            "tool": case.tool,
            "arguments": case.arguments,
            "requests": sorted(set(seen)),
            "result": normalize(structured),
        }
        print(f"{case.question_id}: {len(set(seen))} requests")
    httpx.AsyncHTTPTransport.handle_async_request = real_send  # type: ignore[method-assign]
    if failed:
        print(f"{failed} case(s) failed; nothing written. Rebuild the key or fix the case.")
        return 1
    REPLAY.mkdir(exist_ok=True)
    for old in REPLAY.glob("*.json"):
        old.unlink()
    for path, fixture in fixtures.items():
        text = json.dumps(fixture, indent=1, ensure_ascii=False) + "\n"
        path.write_text(text, encoding="utf-8", newline="\n")
    used = {rid for f in fixtures.values() for rid in f["requests"]}
    store = json.dumps({rid: exchanges[rid] for rid in sorted(used)}, sort_keys=True)
    # mtime=0: the same bytes for the same exchanges, so an unchanged store is no diff.
    HTTP_STORE.write_bytes(gzip.compress(store.encode(), mtime=0))
    print(f"wrote {len(fixtures)} fixtures and {len(used)} exchanges to {REPLAY}")
    return 0


def main() -> int:
    if sys.argv[1:] != ["record"]:
        print(__doc__)
        return 2
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        cwd=HERE,
    ).stdout.strip()
    return asyncio.run(record_all(commit))


if __name__ == "__main__":
    sys.exit(main())
