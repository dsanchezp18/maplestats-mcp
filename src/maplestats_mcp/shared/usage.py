"""Aggregate usage counts for the hosted server: which tools run, not what was asked.

The counters hold a tool's name, the UTC day, whether the call succeeded and
how long it took (the last LATENCY_SAMPLES durations per tool, for its p50
and p95). They never hold arguments, query text, client addresses or
anything else a caller typed. `/stats` reports the period they cover, with
the upstream hosts' error counts and breaker states from shared/breaker.py.

By default they live in memory, so a restart (a deploy, a free host's idle
sleep) starts them again. With MAPLE_USAGE_STATS_FILE set, the per-tool and
per-day counts are also kept in that JSON file: read at startup, saved every
SAVE_SECONDS and when the process exits. A save adds what this process
counted since its last save to what the file holds, rather than writing its
own totals over it, because during a rollout the old and new revisions run
side by side for a few minutes and both count calls into the same file.
Latencies stay in memory: they describe recent calls, not a history.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import math
import os
import re
import time
from collections import Counter, deque
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from maplestats_mcp import config
from maplestats_mcp.shared.breaker import BREAKER
from maplestats_mcp.shared.goatcounter import FORWARDER, GoatCounterForwarder

logger = logging.getLogger("maplestats_mcp.usage")

# Days kept, a little over a year; older ones are dropped so the counters stay small.
MAX_DAYS = 400
# How often counts are written to MAPLE_USAGE_STATS_FILE; a crash loses at most this much.
SAVE_SECONDS = 60
FILE_VERSION = 1
# Durations kept per tool for its percentiles: recent enough to show a slow
# upstream today, and at most a few hundred kilobytes for every tool together.
LATENCY_SAMPLES = 500


def normalized_tool_name(name: str) -> str:
    """The bare tool name: no namespace ("StatCan.", "maplestats:"), lower case, underscores.

    call_tool runs a name that matches a tool once normalized (server.py), so the
    count goes to that tool too, not to "other".
    """
    bare = re.split(r"[./:]", name.strip()[:200])[-1]
    return re.sub(r"[\s-]+", "_", bare).lower()


def _percentile(ordered: list[float], share: float) -> float:
    """Nearest-rank percentile of an ascending, non-empty list."""
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


class UsageStats:
    """Calls per tool and per day, split into succeeded and failed."""

    def __init__(
        self,
        tool_names: Iterable[str] = (),
        forwarder: GoatCounterForwarder | None = None,
        path: Path | None = None,
    ) -> None:
        self.tool_names = set(tool_names)
        # Also sends each call to GoatCounter when configured (shared/goatcounter.py),
        # so the counts outlive a restart and both hosts add up in one place.
        self.forwarder = forwarder
        self.path = path
        self.since = datetime.now(UTC)
        self.tools: Counter[tuple[str, bool]] = Counter()
        self.days: dict[str, Counter[bool]] = {}
        self.durations: dict[str, deque[float]] = {}
        # Counted since the last save, added to the file by the next one.
        self._new_tools: Counter[tuple[str, bool]] = Counter()
        self._new_days: dict[str, Counter[bool]] = {}
        self._task: asyncio.Task[None] | None = None
        if path is not None:
            try:
                saved = self._read()
            except OSError as exc:
                # Counted from zero here, but save() re-reads the file and never
                # overwrites one it cannot read, so the history is kept.
                logger.warning("Usage stats file unreadable at start: %s", exc)
                saved = None
            if saved is not None:
                self.since, self.tools, self.days = saved

    def register_tools(self, names: Iterable[str]) -> None:
        """Accept names from the server registry, never from a request."""
        self.tool_names.update(names)

    def record(self, tool: str, ok: bool, seconds: float | None = None) -> None:
        name = tool if tool in self.tool_names else normalized_tool_name(tool)
        if name not in self.tool_names:
            name = "other"
        self.tools[(name, ok)] += 1
        self._new_tools[(name, ok)] += 1
        if self.forwarder is not None:
            self.forwarder.add(name, ok)
        if seconds is not None:
            samples = self.durations.setdefault(name, deque(maxlen=LATENCY_SAMPLES))
            samples.append(seconds)
        day = datetime.now(UTC).date().isoformat()
        self.days.setdefault(day, Counter())[ok] += 1
        self._new_days.setdefault(day, Counter())[ok] += 1
        _drop_old_days(self.days)
        self._start()

    # ---- the file (MAPLE_USAGE_STATS_FILE)

    def _read(self) -> tuple[datetime, Counter[tuple[str, bool]], dict[str, Counter[bool]]] | None:
        """The file's counts, or None when there is no file or it is not valid.

        A file that is not valid is moved aside (`.bad`) rather than overwritten, so
        a bad write or a hand edit never silently replaces the history. A file that
        exists but cannot be read (a network share's transient error) raises
        OSError: treating it as absent would let the next save overwrite it.
        """
        assert self.path is not None
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            return _parse(json.loads(raw))
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            aside = self.path.with_name(self.path.name + ".bad")
            logger.warning("Usage stats file is not valid (%s); moved to %s", exc, aside)
            try:
                os.replace(self.path, aside)
            except OSError:
                pass
            return None

    def save(self) -> bool:
        """Add the calls counted since the last save to the file; True when written.

        Synchronous on purpose: with no await between reading the file and taking
        its counts as the totals, no call can be recorded in between and lost. The
        read-add-replace runs under an advisory lock on a sidecar file, so two
        processes saving at once (old and new replica during a rollout) cannot
        both read the same file and lose one's counts.
        """
        if self.path is None:
            return False
        with _file_lock(self.path):
            return self._save_locked()

    def _save_locked(self) -> bool:
        assert self.path is not None
        try:
            saved = self._read()
        except OSError as exc:
            # The unsaved counts stay queued for the next save.
            logger.warning("Usage stats file unreadable, not saved this time: %s", exc)
            return False
        since, tools, days = saved if saved is not None else (self.since, Counter(), {})
        tools.update(self._new_tools)
        for day, counts in self._new_days.items():
            days.setdefault(day, Counter()).update(counts)
        _drop_old_days(days)
        since = min(since, self.since)
        body = {
            "version": FILE_VERSION,
            "counting_since": since.isoformat(),
            "by_tool": _by_tool(tools),
            "by_day": _by_day(days),
        }
        temp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
            # Atomic on the same filesystem: a reader sees the old file or the new one.
            os.replace(temp, self.path)
        except OSError as exc:
            # The unsaved counts stay queued for the next save.
            logger.warning("Usage stats not saved to %s: %s", self.path, exc)
            return False
        self.since, self.tools, self.days = since, tools, days
        self._new_tools = Counter()
        self._new_days = {}
        return True

    def _start(self) -> None:
        if self.path is None or (self._task is not None and not self._task.done()):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no loop (a sync caller); the next call from the server starts it
        self._task = loop.create_task(self._run(), name="usage-stats-save")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(SAVE_SECONDS)
            self.save()

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
        kept = (
            "the call counts are also saved to disk and survive a restart; latencies cover "
            "calls since this process started"
            if self.path is not None
            else "a restart starts the count again"
        )
        return {
            "counting_since": self.since.isoformat(),
            "persisted": self.path is not None,
            "note": (
                "Tool names, outcomes and durations, and upstream host names with their error "
                f"counts, only, in memory; {kept}. Where GoatCounter is configured, each "
                "call's tool name and outcome are also counted there."
            ),
            "calls": sum(self.tools.values()),
            "errors": sum(c for (_, ok), c in self.tools.items() if not ok),
            "by_day": _by_day(self.days),
            "by_tool": dict(ordered),
            "latency_ms": latency,
        }


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """An exclusive advisory lock on `path`.lock where the platform has flock.

    Best effort: without fcntl (Windows) or where the filesystem refuses the lock,
    the save goes ahead unlocked, as it did before.
    """
    try:
        import fcntl
    except ImportError:  # Windows
        yield
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path.with_name(path.name + ".lock"), "a+b")  # noqa: SIM115
    except OSError:
        yield
        return
    try:
        try:
            # Linux only (the import fails on Windows); pyright on Windows sees a stub.
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)  # pyright: ignore[reportAttributeAccessIssue]
        except OSError as exc:
            logger.debug("Usage stats lock not taken (%s); saving unlocked", exc)
        yield
    finally:
        handle.close()  # closing releases the lock


def _drop_old_days(days: dict[str, Counter[bool]]) -> None:
    for old in sorted(days)[:-MAX_DAYS]:
        del days[old]


def _by_tool(tools: Counter[tuple[str, bool]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for (name, ok), count in sorted(tools.items()):
        out.setdefault(name, {"ok": 0, "error": 0})["ok" if ok else "error"] += count
    return out


def _by_day(days: dict[str, Counter[bool]]) -> dict[str, dict[str, int]]:
    return {
        day: {"ok": counts[True], "error": counts[False]} for day, counts in sorted(days.items())
    }


def _count(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"not a count: {value!r}")
    return value


def _parse(body: Any) -> tuple[datetime, Counter[tuple[str, bool]], dict[str, Counter[bool]]]:
    """Check and read a saved file's body; raise ValueError when it is not one."""
    if not isinstance(body, dict) or body.get("version") != FILE_VERSION:
        raise ValueError("unknown file version")
    since = datetime.fromisoformat(body["counting_since"])
    if since.tzinfo is None:
        raise ValueError("counting_since has no time zone")
    tools: Counter[tuple[str, bool]] = Counter()
    for name, counts in body["by_tool"].items():
        if not isinstance(name, str):
            raise TypeError("tool name is not text")
        tools[(name, True)] = _count(counts["ok"])
        tools[(name, False)] = _count(counts["error"])
    days: dict[str, Counter[bool]] = {}
    for day, counts in body["by_day"].items():
        datetime.strptime(day, "%Y-%m-%d")
        days[day] = Counter({True: _count(counts["ok"]), False: _count(counts["error"])})
    # Zero entries are dropped so a tool with no failures shows as before.
    return since, +tools, days


# True while a counted call runs. reproduce_code and reproduce_workbook call the
# server again in-process; that inner call is part of the outer one, not a second
# call by the caller, and the variable reaches it because tasks inherit context.
_inside_call: ContextVar[bool] = ContextVar("maplestats_usage_inside_call", default=False)

# The process-wide counters the middleware fills and /stats reports.
STATS = UsageStats(forwarder=FORWARDER, path=config.get_usage_stats_file())
if STATS.path is not None:
    # The HTTP server saves at shutdown in asgi.py (uvicorn re-raises SIGTERM after
    # shutting down, so atexit does not run there); this covers stdio and any other
    # normal exit. A second save adds nothing, so both running is harmless.
    atexit.register(STATS.save)


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
