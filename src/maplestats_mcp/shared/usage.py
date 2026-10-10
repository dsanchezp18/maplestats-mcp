"""Aggregate usage counts for the hosted server: which tools run, not what was asked.

The counters hold a tool's name, the UTC day and whether the call succeeded.
They never hold arguments, query text, client addresses or anything else a
caller typed. They live in memory, so a restart (a free host's idle sleep
included) starts them again; `/stats` reports the period they cover.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

# Days kept; older ones are dropped so the counters stay small.
MAX_DAYS = 90


class UsageStats:
    """Calls per tool and per day, split into succeeded and failed."""

    def __init__(self, tool_names: Iterable[str] = ()) -> None:
        self.tool_names = set(tool_names)
        self.since = datetime.now(UTC)
        self.tools: Counter[tuple[str, bool]] = Counter()
        self.days: dict[str, Counter[bool]] = {}

    def register_tools(self, names: Iterable[str]) -> None:
        """Accept names from the server registry, never from a request."""
        self.tool_names.update(names)

    def record(self, tool: str, ok: bool) -> None:
        name = tool if tool in self.tool_names else "other"
        self.tools[(name, ok)] += 1
        day = datetime.now(UTC).date().isoformat()
        self.days.setdefault(day, Counter())[ok] += 1
        for old in sorted(self.days)[:-MAX_DAYS]:
            del self.days[old]

    def snapshot(self) -> dict[str, Any]:
        per_tool: dict[str, dict[str, int]] = {}
        for (name, ok), count in self.tools.items():
            per_tool.setdefault(name, {"ok": 0, "error": 0})["ok" if ok else "error"] += count
        ordered = sorted(per_tool.items(), key=lambda item: -(item[1]["ok"] + item[1]["error"]))
        return {
            "counting_since": self.since.isoformat(),
            "note": "Tool names and outcomes only, in memory; a restart starts the count again.",
            "calls": sum(self.tools.values()),
            "errors": sum(c for (_, ok), c in self.tools.items() if not ok),
            "by_day": {
                day: {"ok": counts[True], "error": counts[False]}
                for day, counts in sorted(self.days.items())
            },
            "by_tool": dict(ordered),
        }


# True while a counted call runs. reproduce_code and reproduce_workbook call the
# server again in-process; that inner call is part of the outer one, not a second
# call by the caller, and the variable reaches it because tasks inherit context.
_inside_call: ContextVar[bool] = ContextVar("maplestats_usage_inside_call", default=False)

# The process-wide counters the middleware fills and /stats reports.
STATS = UsageStats()


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
        try:
            result = await call_next(context)
        except Exception:
            self.stats.record(str(name), False)
            raise
        finally:
            _inside_call.reset(token)
        # A tool that raises comes back as an error result, not an exception.
        self.stats.record(str(name), not getattr(result, "is_error", False))
        return result
