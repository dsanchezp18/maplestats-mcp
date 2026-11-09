"""How much smaller brief results are than full ones, offline, from recorded tool calls.

Two sets of recordings, neither needing the network:

- the Maple Test replay fixtures (tests/maple_test/replay/): each question's tool call
  with every HTTP exchange the server had. Each call runs again through `call_tool`
  against this checkout, the recorded HTTP served in place of the sources, once with
  detail="full" and once with the default (brief). These are the StatCan vector and
  Bank of Canada calls most Maple Test questions make.
- the website's case recordings (site/_data/cases/): full results of other tools (CMHC,
  FCAC, IRCC, Bank of Canada history), shaped here by shared/brief.py as the server
  shapes them. "Before" is the result as recorded by a server without brief results.

For each call it prints the characters of the text a model reads and an estimate of its
tokens (four characters a token): before (the recorded result), full and brief.

    uv run python scripts/benchmark_brief.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maplestats_mcp.shared.brief import estimated_tokens, exempt, shape
from tests.maple_test.replay import (
    CASES,
    call,
    fixture_path,
    frozen_today,
    load_http,
    request_id,
)

CASES_DIR = ROOT / "site" / "_data" / "cases"
# Site recordings worth measuring: one per tool, the larger results.
SITE_CASES = ("housing", "cards", "ircc", "boc", "policy_rate")


def compact(value: Any) -> str:
    """The text FastMCP sends for a structured result (compact JSON)."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def serve_recorded(store: dict[str, dict[str, Any]]) -> None:
    """Answer every outgoing request from the recorded exchanges; fail on any other."""
    from maplestats_mcp.shared import cache

    async def handle(self: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        rid = request_id(request.method, str(request.url), request.content or b"")
        if rid not in store:
            raise RuntimeError(f"not recorded: {request.method} {request.url}")
        exchange = store[rid]
        body = exchange["text"].encode() if "text" in exchange else b""
        return httpx.Response(
            exchange["status"], headers=exchange["headers"], content=body, request=request
        )

    httpx.AsyncHTTPTransport.handle_async_request = handle  # type: ignore[method-assign]
    cache._caches.clear()


async def replayed() -> list[tuple[str, int, int, int]]:
    from maplestats_mcp.shared import cache

    serve_recorded(load_http())
    rows = []
    for case in CASES:
        fixture = json.loads(fixture_path(case).read_text(encoding="utf-8"))
        with frozen_today(date.fromisoformat(fixture["recorded_on"])):
            cache._caches.clear()
            _, full = await call(case, detail="full")
            cache._caches.clear()
            _, brief = await call(case, detail="brief")
        label = f"{case.question_id} {case.tool}"
        # The fixture drops queried_at; today's output is the full text itself.
        rows.append((label, len(full), len(full), len(brief)))
    return rows


def recorded() -> list[tuple[str, int, int, int]]:
    rows = []
    for name in SITE_CASES:
        data = json.loads((CASES_DIR / f"{name}.json").read_text(encoding="utf-8"))
        call_ = max(data["calls"], key=lambda c: len(compact(c["response"])))
        tool, payload = call_["name"], call_["response"]
        if exempt(tool) or not isinstance(payload, dict):
            continue
        before = compact(payload)
        full = compact(shape(payload, "full") or payload)
        brief = compact(shape(payload, "brief") or payload)
        rows.append((f"site:{name} {tool}", len(before), len(full), len(brief)))
    return rows


def main() -> int:
    rows = asyncio.run(replayed()) + recorded()
    print(
        f"{'call':<46} {'before':>8} {'full':>8} {'brief':>8} {'brief/before':>12} "
        f"{'tokens before':>14} {'tokens brief':>13}"
    )
    for label, before, full, brief in rows:
        print(
            f"{label:<46} {before:>8,} {full:>8,} {brief:>8,} {brief / before:>12.0%} "
            f"{estimated_tokens(before):>14,} {estimated_tokens(brief):>13,}"
        )
    totals = [sum(r[1] for r in rows), sum(r[2] for r in rows), sum(r[3] for r in rows)]
    print(
        f"{'all calls':<46} {totals[0]:>8,} {totals[1]:>8,} {totals[2]:>8,} "
        f"{totals[2] / totals[0]:>12.0%} {estimated_tokens(totals[0]):>14,} "
        f"{estimated_tokens(totals[2]):>13,}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
