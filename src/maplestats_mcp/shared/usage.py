"""Aggregate usage counts for the hosted server: which tools run, not what was asked.

The counters hold a tool's name, the UTC day, whether the call succeeded and
how long it took (the last LATENCY_SAMPLES durations per tool, for its p50
and p95). They never hold arguments, query text, client addresses or
anything else a caller typed. They live in memory, so a restart (a free
host's idle sleep included) starts them again; `/stats` reports the period
they cover, with the upstream hosts' error counts and breaker states from
shared/breaker.py.
"""

from __future__ import annotations

import math
import time
from collections import Counter, deque
from collections.abc import Iterable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from maplestats_mcp.shared.breaker import BREAKER

# Days kept; older ones are dropped so the counters stay small.
MAX_DAYS = 90
# Durations kept per tool for its percentiles: recent enough to show a slow
# upstream today, and at most a few hundred kilobytes for every tool together.
LATENCY_SAMPLES = 500


def _percentile(ordered: list[float], share: float) -> float:
    """Nearest-rank percentile of an ascending, non-empty list."""
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


class UsageStats:
    """Calls per tool and per day, split into succeeded and failed."""

    def __init__(self, tool_names: Iterable[str] = ()) -> None:
        self.tool_names = set(tool_names)
        self.since = datetime.now(UTC)
        self.tools: Counter[tuple[str, bool]] = Counter()
        self.days: dict[str, Counter[bool]] = {}
        self.durations: dict[str, deque[float]] = {}

    def register_tools(self, names: Iterable[str]) -> None:
        """Accept names from the server registry, never from a request."""
        self.tool_names.update(names)

    def record(self, tool: str, ok: bool, seconds: float | None = None) -> None:
        name = tool if tool in self.tool_names else "other"
        self.tools[(name, ok)] += 1
        if seconds is not None:
            samples = self.durations.setdefault(name, deque(maxlen=LATENCY_SAMPLES))
            samples.append(seconds)
        day = datetime.now(UTC).date().isoformat()
        self.days.setdefault(day, Counter())[ok] += 1
        for old in sorted(self.days)[:-MAX_DAYS]:
            del self.days[old]

    def snapshot(self) -> dict[str, Any]:
        per_tool: dict[str, dict[str, int]] = {}
        for (name, ok), count in self.tools.items():
            per_tool.setdefault(name, {"ok": 0, "error": 0})["ok" if ok else "error"] += count
        ordered = sorted(per_tool.items(), key=lambda item: -(item[1]["ok"] + item[1]["error"]))
        latency: dict[str, dict[str, float | int]] = {}
        for name, _ in ordered:
            samples = sorted(self.durations.get(name, ()))
            if samples:
                latency[name] = {
                    "p50_ms": round(_percentile(samples, 0.5) * 1000),
                    "p95_ms": round(_percentile(samples, 0.95) * 1000),
                    "samples": len(samples),
                }
        return {
            "counting_since": self.since.isoformat(),
            "note": (
                "Tool names, outcomes and durations, and upstream host names with their error "
                "counts, only, in memory; a restart starts the count again."
            ),
            "calls": sum(self.tools.values()),
            "errors": sum(c for (_, ok), c in self.tools.items() if not ok),
            "by_day": {
                day: {"ok": counts[True], "error": counts[False]}
                for day, counts in sorted(self.days.items())
            },
            "by_tool": dict(ordered),
            "latency_ms": latency,
        }


# True while a counted call runs. reproduce_code and reproduce_workbook call the
# server again in-process; that inner call is part of the outer one, not a second
# call by the caller, and the variable reaches it because tasks inherit context.
_inside_call: ContextVar[bool] = ContextVar("maplestats_usage_inside_call", default=False)

# The process-wide counters the middleware fills and /stats reports.
STATS = UsageStats()


def public_snapshot() -> dict[str, Any]:
    """What /stats serves: the tool counts and latencies, then the upstream hosts' health."""
    return {**STATS.snapshot(), "upstreams": BREAKER.snapshot()}


class UsageMiddleware(Middleware):
    """Count each tool call by the tool it runs; the call_tool meta-tool counts as its target."""

    def __init__(self, stats: UsageStats) -> None:
        self.stats = stats

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext) -> Any:
        if _inside_call.get():
            return await call_next(context)
        params = context.message
        name = getattr(params, "name", "other")
        arguments = getattr(params, "arguments", None) or {}
        if name == "call_tool" and isinstance(arguments, dict):
            target = arguments.get("name")
            name = target if isinstance(target, str) else "other"
        token = _inside_call.set(True)
        started = time.perf_counter()
        try:
            result = await call_next(context)
        except Exception:
            self.stats.record(str(name), False, time.perf_counter() - started)
            raise
        finally:
            _inside_call.reset(token)
        # fastmcp 4.1 re-raises a failing tool as ToolError, which the except
        # branch above counts; an error result only gets here when a tool returned
        # ToolResult(is_error=True) itself.
        self.stats.record(
            str(name), not getattr(result, "is_error", False), time.perf_counter() - started
        )
        return result
