"""Aggregate usage counts for the hosted server: which tools run, not what was asked.

The counters hold a tool's name, the UTC day, whether the call succeeded,
for a failure its error code (`not_found`, `invalid_input`, ... from
shared/error_hints.py: a fixed list, never the message), how long it took
(the last LATENCY_SAMPLES durations per tool, for its p50 and p95) and how
large its result was (characters of text, and tokens estimated from them:
what a call costs a model to read). They never hold
arguments, query text, result content, client addresses or anything else a
caller typed. The one thing kept about who calls is a label from a fixed list
(`CLIENT_LABELS`): the kind of client software, matched from the name it announces
when it connects (never stored as sent), or `internal` for calls that carry the
maintainer's secret header (MAPLE_INTERNAL_TOKEN), so their own use and benchmark
runs can be told apart from everyone else's. `/stats` reports the period they cover, with
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
import hmac
import json
import logging
import math
import os
import re
import time
from collections import Counter, deque
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from maplestats_mcp import config
from maplestats_mcp.shared import path_health
from maplestats_mcp.shared.breaker import BREAKER
from maplestats_mcp.shared.brief import estimated_tokens
from maplestats_mcp.shared.error_hints import ERROR_CODES, error_code
from maplestats_mcp.shared.goatcounter import FORWARDER, GoatCounterForwarder

logger = logging.getLogger("maplestats_mcp.usage")

# Days kept, a little over a year; older ones are dropped so the counters stay small.
MAX_DAYS = 400
# How often counts are written to MAPLE_USAGE_STATS_FILE; a crash loses at most this much.
SAVE_SECONDS = 60
# Still 1 after `by_error` was added: it is optional on read, and a bump would make a
# revision from before it move the file aside. During a rollout that old revision's
# save rewrites the file without `by_error`, so the error codes counted by the new one
# in those minutes are lost (the call counts are not).
FILE_VERSION = 1
# Durations kept per tool for its percentiles: recent enough to show a slow
# upstream today, and at most a few hundred kilobytes for every tool together.
LATENCY_SAMPLES = 500
# Tools listed in /stats' `top_failing_tools`. The counters are already bounded
# (registered tool names plus "other", codes from ERROR_CODES); this keeps the ranking
# short enough to read, and every tool's codes stay in `by_error`.
TOP_FAILING = 20

# What the file holds: counting since, calls by (tool, ok), calls by day, failures by
# (tool, code), calls by (client label, ok), and calls by day and client label.
_Saved = tuple[
    datetime,
    Counter[tuple[str, bool]],
    dict[str, Counter[bool]],
    Counter[tuple[str, str]],
    Counter[tuple[str, bool]],
    dict[str, Counter[str]],
]

# The sources a blocked StatCan tool can be answered from (shared/substitution.py): a
# fixed list, so the counter never holds text from a request. An unknown name counts as
# "other".
FALLBACK_SOURCES = ("ccei", "stcshared", "boc", "ab_economic")
# Why the HTTP layer refused a request (shared/security.py): over the per-client rate
# limit (429), too many in flight from one client (429), every slot busy (503).
REFUSAL_REASONS = ("rate_limited", "client_busy", "server_busy")

# Header the maintainer's own clients send, with the secret MAPLE_INTERNAL_TOKEN holds.
INTERNAL_HEADER = "x-maple-internal"
# Query parameter a client can add to the endpoint URL to say what it is (see caller_label).
CLIENT_HINT_PARAM = "client"

# Kind of client, from the name it announces in the MCP `initialize` request. Each
# entry is (text found in the lower-cased name, label); the first match wins, so
# the specific names come before the general ones. The name is chosen by whoever
# runs the client, so it says what software connected, not who is using it, and
# anything not matched is "other": a caller cannot add a label.
CLIENT_LABELS: tuple[tuple[str, str], ...] = (
    ("uptime-check", "uptime-check"),
    ("maple-test", "maple-test"),
    ("maplestats-chat", "chat-demo"),
    ("maplestats", "maplestats-client"),
    ("claude-code", "claude-code"),
    ("claude-ai", "claude-ai"),
    ("claude", "claude"),
    ("cursor", "cursor"),
    ("windsurf", "windsurf"),
    ("visual studio code", "vscode"),
    ("vscode", "vscode"),
    ("codex", "codex"),
    ("openai", "chatgpt"),
    ("chatgpt", "chatgpt"),
    ("gemini", "gemini"),
    ("cline", "cline"),
    ("zed", "zed"),
    ("goose", "goose"),
    ("mcp-remote", "mcp-remote"),
    ("inspector", "mcp-inspector"),
    ("fastmcp", "python-fastmcp"),
    ("mcp", "mcp-sdk"),
)
CLIENT_OTHER = "other"
CLIENT_UNKNOWN = "unknown"
CLIENT_INTERNAL = "internal"
KNOWN_CLIENT_LABELS = frozenset({label for _, label in CLIENT_LABELS}) | {
    CLIENT_OTHER,
    CLIENT_UNKNOWN,
    CLIENT_INTERNAL,
}


def client_label(announced: str | None) -> str:
    """The fixed label for a client's announced name; the name itself is never kept."""
    if not announced or not announced.strip():
        return CLIENT_UNKNOWN
    lowered = announced.strip()[:200].lower()
    return next((label for needle, label in CLIENT_LABELS if needle in lowered), CLIENT_OTHER)


def is_internal(headers: dict[str, str], token: str | None) -> bool:
    """True when the request carries the maintainer's secret; always False with none set."""
    sent = headers.get(INTERNAL_HEADER, "")
    return bool(token) and bool(sent) and hmac.compare_digest(sent.encode(), (token or "").encode())


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
        # Failures by (tool, error code); a failure counted before codes existed has none.
        self.errors: Counter[tuple[str, str]] = Counter()
        # Calls by (client label, ok), and per day by label. Calls counted before
        # labels were kept have none; the snapshot reports them as "untracked".
        self.clients: Counter[tuple[str, bool]] = Counter()
        self.client_days: dict[str, Counter[str]] = {}
        # Answers a tool gave from a substitute source because its own was blocked
        # (shared/substitution.py), by source; in memory, like the latencies.
        self.fallbacks: Counter[str] = Counter()
        # MCP requests the HTTP layer refused before any tool ran (shared/security.py),
        # by reason only; in memory. Added 2026-11-20, when six steps of the Azure live
        # check failed on refusals that left no trace on the server.
        self.refusals: Counter[str] = Counter()
        self.durations: dict[str, deque[float]] = {}
        # Per tool: [results sized, characters in all of them, the largest]. The
        # size of what the client read, never its content.
        self.sizes: dict[str, list[int]] = {}
        # Counted since the last save, added to the file by the next one.
        self._new_tools: Counter[tuple[str, bool]] = Counter()
        self._new_days: dict[str, Counter[bool]] = {}
        self._new_errors: Counter[tuple[str, str]] = Counter()
        self._new_clients: Counter[tuple[str, bool]] = Counter()
        self._new_client_days: dict[str, Counter[str]] = {}
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
                (
                    self.since,
                    self.tools,
                    self.days,
                    self.errors,
                    self.clients,
                    self.client_days,
                ) = saved

    def register_tools(self, names: Iterable[str]) -> None:
        """Accept names from the server registry, never from a request."""
        self.tool_names.update(names)

    def _name(self, tool: str) -> str:
        name = tool if tool in self.tool_names else normalized_tool_name(tool)
        return name if name in self.tool_names else "other"

    def record_fallback(self, source: str) -> None:
        """Count one answer served from `source` in place of a blocked StatCan source."""
        self.fallbacks[source if source in FALLBACK_SOURCES else CLIENT_OTHER] += 1

    def record_refusal(self, reason: str) -> None:
        """Count one MCP request refused before it reached a tool (a 429 or a 503)."""
        self.refusals[reason if reason in REFUSAL_REASONS else CLIENT_OTHER] += 1

    def record_size(self, tool: str, chars: int) -> None:
        """Count one result of `chars` characters (the text the client read) for `tool`."""
        entry = self.sizes.setdefault(self._name(tool), [0, 0, 0])
        entry[0] += 1
        entry[1] += chars
        entry[2] = max(entry[2], chars)

    def record(
        self,
        tool: str,
        ok: bool,
        seconds: float | None = None,
        code: str | None = None,
        client: str | None = None,
    ) -> None:
        name = self._name(tool)
        self.tools[(name, ok)] += 1
        self._new_tools[(name, ok)] += 1
        if not ok:
            # Only a code from the fixed list is kept, never text from the failure.
            kind = code if code in ERROR_CODES else "error"
            self.errors[(name, kind)] += 1
            self._new_errors[(name, kind)] += 1
        if self.forwarder is not None:
            self.forwarder.add(name, ok)
        if seconds is not None:
            samples = self.durations.setdefault(name, deque(maxlen=LATENCY_SAMPLES))
            samples.append(seconds)
        day = datetime.now(UTC).date().isoformat()
        self.days.setdefault(day, Counter())[ok] += 1
        self._new_days.setdefault(day, Counter())[ok] += 1
        if client is not None:
            # Only a label from the fixed list is kept, never text a caller sent.
            label = client if client in KNOWN_CLIENT_LABELS else CLIENT_OTHER
            self.clients[(label, ok)] += 1
            self._new_clients[(label, ok)] += 1
            self.client_days.setdefault(day, Counter())[label] += 1
            self._new_client_days.setdefault(day, Counter())[label] += 1
            _drop_old_days(self.client_days)
        _drop_old_days(self.days)
        self._start()

    # ---- the file (MAPLE_USAGE_STATS_FILE)

    def _read(self) -> _Saved | None:
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
        since, tools, days, errors, clients, client_days = (
            saved if saved is not None else (self.since, Counter(), {}, Counter(), Counter(), {})
        )
        tools.update(self._new_tools)
        errors.update(self._new_errors)
        clients.update(self._new_clients)
        for day, counts in self._new_days.items():
            days.setdefault(day, Counter()).update(counts)
        for day, label_counts in self._new_client_days.items():
            client_days.setdefault(day, Counter()).update(label_counts)
        _drop_old_days(days)
        _drop_old_days(client_days)
        since = min(since, self.since)
        body = {
            "version": FILE_VERSION,
            "counting_since": since.isoformat(),
            "by_tool": _by_tool(tools),
            "by_day": _by_day(days),
            "by_error": _by_error(errors),
            "by_client": _by_client(clients),
            "by_day_client": _by_day_client(client_days),
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
        self.since, self.tools, self.days, self.errors = since, tools, days, errors
        self.clients, self.client_days = clients, client_days
        self._new_tools = Counter()
        self._new_days = {}
        self._new_errors = Counter()
        self._new_clients = Counter()
        self._new_client_days = {}
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
        sizes = {
            name: {
                "results": count,
                "mean_chars": round(total / count),
                "max_chars": largest,
                "mean_tokens_est": estimated_tokens(round(total / count)),
            }
            for name, (count, total, largest) in sorted(
                self.sizes.items(), key=lambda item: -item[1][1]
            )
            if count
        }
        kept = (
            "the call counts are also saved to disk and survive a restart; latencies and "
            "result sizes cover calls since this process started"
            if self.path is not None
            else "a restart starts the count again"
        )
        failed = sum(c for (_, ok), c in self.tools.items() if not ok)
        by_code: Counter[str] = Counter()
        for (_, code), count in self.errors.items():
            by_code[code] += count
        error_codes = dict(by_code.most_common())
        # Failures counted before codes were kept (an older file) have none.
        if failed > sum(by_code.values()):
            error_codes["uncoded"] = failed - sum(by_code.values())
        by_client = _by_client(self.clients)
        tracked = sum(c["ok"] + c["error"] for c in by_client.values())
        total = sum(self.tools.values())
        if total > tracked:
            # Counted before labels were kept (an older file), so with no label.
            by_client["untracked"] = {
                "ok": sum(c for (_, ok), c in self.tools.items() if ok)
                - sum(c["ok"] for c in by_client.values()),
                "error": failed - sum(c["error"] for c in by_client.values()),
            }
        internal = by_client.get(CLIENT_INTERNAL, {"ok": 0, "error": 0})
        return {
            "counting_since": self.since.isoformat(),
            "persisted": self.path is not None,
            "note": (
                "Tool names, outcomes, error codes (a fixed list such as not_found or "
                "invalid_input, never the message), the kind of client that called (a fixed "
                "list such as claude-code or python-fastmcp, or internal for the "
                "maintainer's own calls; never the name it sent or an address), "
                "durations and result sizes (characters, "
                "and tokens estimated at four characters each), upstream host names with "
                "their error counts, and how many answers a blocked StatCan tool took from "
                "another official source (by source name), and how many requests the HTTP "
                "layer refused by reason (rate limit, busy), "
                f"only, in memory; {kept}. Where "
                "GoatCounter is "
                "configured, each call's tool name and outcome are also counted there."
            ),
            "calls": total,
            "calls_excluding_internal": total - internal["ok"] - internal["error"],
            "errors": failed,
            "error_codes": error_codes,
            "by_day": _by_day(self.days),
            "by_tool": dict(ordered),
            "by_error": _by_error(self.errors, order=[name for name, _ in ordered]),
            "top_failing_tools": _top_failing(per_tool, self.errors),
            "by_client": by_client,
            "by_day_client": _by_day_client(self.client_days),
            "latency_ms": latency,
            "result_size": sizes,
            "fallbacks": dict(self.fallbacks.most_common()),
            "refused_requests": dict(self.refusals.most_common()),
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


def _drop_old_days(days: dict[str, Counter[Any]]) -> None:
    for old in sorted(days)[:-MAX_DAYS]:
        del days[old]


def _by_tool(tools: Counter[tuple[str, bool]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for (name, ok), count in sorted(tools.items()):
        out.setdefault(name, {"ok": 0, "error": 0})["ok" if ok else "error"] += count
    return out


def _by_client(clients: Counter[tuple[str, bool]]) -> dict[str, dict[str, int]]:
    """Calls per client label, busiest first."""
    out: dict[str, dict[str, int]] = {}
    for (label, ok), count in clients.items():
        out.setdefault(label, {"ok": 0, "error": 0})["ok" if ok else "error"] += count
    return dict(
        sorted(out.items(), key=lambda item: (-(item[1]["ok"] + item[1]["error"]), item[0]))
    )


def _by_day_client(client_days: dict[str, Counter[str]]) -> dict[str, dict[str, int]]:
    return {
        day: dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
        for day, counts in sorted(client_days.items())
    }


def _by_error(
    errors: Counter[tuple[str, str]], order: list[str] | None = None
) -> dict[str, dict[str, int]]:
    """Failures per tool, then per code; tools in `order` first (else by name), codes by count."""
    out: dict[str, dict[str, int]] = {}
    for (name, code), count in sorted(errors.items(), key=lambda item: (-item[1], item[0])):
        out.setdefault(name, {})[code] = count
    names = order if order is not None else sorted(out)
    return {name: out[name] for name in names if name in out}


def _top_failing(
    per_tool: dict[str, dict[str, int]], errors: Counter[tuple[str, str]]
) -> list[dict[str, Any]]:
    """The TOP_FAILING tools with the most failures, each with its error rate and codes.

    What MapleStats could not answer, most often first. A tool's failures counted
    before codes were kept (an older file) show under "uncoded", as in `error_codes`.
    """
    codes: dict[str, Counter[str]] = {}
    for (name, code), count in errors.items():
        codes.setdefault(name, Counter())[code] += count
    failing = sorted(
        ((name, counts) for name, counts in per_tool.items() if counts["error"]),
        key=lambda item: (-item[1]["error"], item[0]),
    )[:TOP_FAILING]
    out: list[dict[str, Any]] = []
    for name, counts in failing:
        calls = counts["ok"] + counts["error"]
        by_code = codes.get(name, Counter())
        tool_codes = dict(sorted(by_code.items(), key=lambda item: (-item[1], item[0])))
        if counts["error"] > sum(by_code.values()):
            tool_codes["uncoded"] = counts["error"] - sum(by_code.values())
        out.append(
            {
                "tool": name,
                "calls": calls,
                "errors": counts["error"],
                "error_rate": round(counts["error"] / calls, 3),
                "codes": tool_codes,
            }
        )
    return out


def _by_day(days: dict[str, Counter[bool]]) -> dict[str, dict[str, int]]:
    return {
        day: {"ok": counts[True], "error": counts[False]} for day, counts in sorted(days.items())
    }


def _count(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"not a count: {value!r}")
    return value


def _parse(body: Any) -> _Saved:
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
    # Absent from a file written before error codes were kept.
    errors: Counter[tuple[str, str]] = Counter()
    for name, codes in body.get("by_error", {}).items():
        if not isinstance(name, str):
            raise TypeError("tool name is not text")
        for code, count in codes.items():
            if not isinstance(code, str):
                raise TypeError("error code is not text")
            errors[(name, code)] = _count(count)
    # Absent from a file written before client labels were kept.
    clients: Counter[tuple[str, bool]] = Counter()
    for label, counts in body.get("by_client", {}).items():
        if not isinstance(label, str):
            raise TypeError("client label is not text")
        clients[(label, True)] = _count(counts["ok"])
        clients[(label, False)] = _count(counts["error"])
    client_days: dict[str, Counter[str]] = {}
    for day, counts in body.get("by_day_client", {}).items():
        datetime.strptime(day, "%Y-%m-%d")
        client_days[day] = Counter({str(label): _count(n) for label, n in counts.items()})
    # Zero entries are dropped so a tool with no failures shows as before.
    return since, +tools, days, +errors, +clients, client_days


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
    """What /stats serves: the tool counts and latencies, then the upstream hosts' health.

    `upstreams.challenged_paths` lists the StatCan path groups ("cimt", "pages", ...) that
    answered with its bot check in the last 15 minutes and not since (shared/path_health.py);
    empty while none has. The chat demo reads it to show its notice.
    """
    upstreams = {**BREAKER.snapshot(), "challenged_paths": sorted(path_health.challenged_now())}
    return {**STATS.snapshot(), "upstreams": upstreams}


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
        client = caller_label(context)
        token = _inside_call.set(True)
        started = time.perf_counter()
        try:
            result = await call_next(context)
        except Exception as exc:
            self.stats.record(
                str(name), False, time.perf_counter() - started, error_code(exc), client
            )
            raise
        finally:
            _inside_call.reset(token)
        # fastmcp 4.1 re-raises a failing tool as ToolError, which the except
        # branch above counts; an error result only gets here when a tool returned
        # ToolResult(is_error=True) itself.
        ok = not getattr(result, "is_error", False)
        code = None if ok else leading_code(result)
        self.stats.record(str(name), ok, time.perf_counter() - started, code, client)
        if ok:
            self.stats.record_size(str(name), result_chars(result))
        return result


def _url_hint() -> str | None:
    """The `?client=` value of the HTTP request being served, None when there is none."""
    with suppress(Exception):
        from fastmcp.server.dependencies import get_http_request

        return get_http_request().query_params.get(CLIENT_HINT_PARAM)
    return None


def caller_label(context: MiddlewareContext) -> str:
    """The client label for this call: `internal` with the secret header, else the kind of client.

    The kind comes from a `?client=` hint on the URL when it names a known client, else
    from the name the client announced at initialize.

    Never raises: a transport with no HTTP request (stdio, in-memory) or no
    initialize yet is simply "unknown".
    """
    token = config.get_internal_token()
    if token:
        # Labelling must never fail a tool call, so a failure here means "not internal".
        with suppress(Exception):
            from fastmcp.server.dependencies import get_http_headers

            if is_internal(get_http_headers(include={INTERNAL_HEADER}), token):
                return CLIENT_INTERNAL
    # A URL hint, for callers that cannot set a client name or a header: Anthropic's MCP
    # connector (the chat demo's default backend) is given `?client=maplestats-chat`.
    # It goes through the same fixed list as an announced name, and counts only when it
    # matches a known label, so a made-up value falls back to the announced name.
    hinted = client_label(_url_hint())
    if hinted not in (CLIENT_OTHER, CLIENT_UNKNOWN):
        return hinted
    try:
        params = context.fastmcp_context.session.client_params  # type: ignore[union-attr]
        # `client_info` in the installed mcp SDK (confirmed 2026-11-16 with fastmcp 4.1.4,
        # protocol 2026-07-28); `clientInfo` in the camelCase spelling of older ones.
        info = getattr(params, "client_info", None) or getattr(params, "clientInfo", None)
        announced = getattr(info, "name", None)
    except Exception:  # noqa: BLE001
        return CLIENT_UNKNOWN
    return client_label(announced)


_LEADING_CODE = re.compile(r"\[([a-z_]{1,40})\]")


def leading_code(result: Any) -> str | None:
    """The "[code]" an error result's text starts with, when it is one of ERROR_CODES."""
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            found = _LEADING_CODE.match(text.lstrip())
            return found.group(1) if found and found.group(1) in ERROR_CODES else None
    return None


def result_chars(result: Any) -> int:
    """Characters of text the client reads in a tool result (its text blocks)."""
    content = getattr(result, "content", None) or []
    return sum(
        len(text) for block in content if isinstance(text := getattr(block, "text", None), str)
    )
