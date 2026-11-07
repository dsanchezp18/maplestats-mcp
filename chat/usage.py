# ============================================================
# Usage counts for the chat demo
# Author: Daniel Sanchez
# Purpose: Count what the public chat does (questions and how each ended,
#          model tokens, tool calls, stop reasons, latency) so the demo's use
#          and cost can be followed, without keeping anything a visitor typed.
# Inputs:  calls from app.py as each request ends
# Outputs: the public /stats JSON; optionally a JSON file (CHAT_USAGE_STATS_FILE)
# ============================================================

"""Usage counts for the chat demo: how questions end, what they cost, which tools run.

Kept: counts per UTC day of each outcome (answered, refused and by which limit,
failed), billed tokens by kind, model and tool calls, tool names (only names
shaped like a MapleStats tool), the model's stop reasons, and the turn number of
each question; plus the durations of recent answers. Never kept: the question,
the answer, tool arguments or results, or the caller's address.

By default the counts live in memory and a restart starts them again. With
CHAT_USAGE_STATS_FILE set they are also kept in that JSON file: read at startup,
saved every SAVE_SECONDS and at shutdown. A save adds what this process counted
since its last save to what the file holds, so two revisions running side by
side during a deploy both count (the MCP server's shared/usage.py does the same).
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from collections import Counter, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("maplestats_chat.usage")

SAVE_SECONDS = 60
# Days kept, a little over a year.
MAX_DAYS = 400
# Durations kept for the p50 and p95.
LATENCY_SAMPLES = 500
FILE_VERSION = 1

# Groups of counters. Each holds a few fixed keys, except "tools", whose keys
# are tool names the model chose; those are checked against _TOOL_NAME and
# capped, since a prompt can steer a model into calling any name.
OUTCOMES = (
    "answered",  # an answer was returned
    "empty",  # the model was billed but returned no text
    "failed",  # the model or the data server failed (502)
    "unavailable",  # a fault of this deployment: key, model (503)
    "limited_address",  # 429: this address's hourly limit
    "limited_daily",  # 429: the day's question limit
    "limited_tokens",  # 429: the day's token budget
    "rejected",  # 400, 413, 415: the request itself was refused
)
TOKEN_KINDS = ("input", "output", "cache_write", "cache_read")
WORK = ("model_calls", "tool_calls", "tool_errors")
GROUPS = ("outcomes", "tokens", "work", "tools", "stop_reasons", "turns")
# Groups also counted per day.
DAILY_GROUPS = ("outcomes", "tokens", "work")

_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_STOP_REASON = re.compile(r"^[a-z_]{1,32}$")
MAX_TOOL_NAMES = 500

Counts = dict[str, Counter[str]]


def _empty() -> Counts:
    return {group: Counter() for group in GROUPS}


def _percentile(ordered: list[float], share: float) -> float:
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


class ChatStats:
    """Counters for the chat demo, optionally kept in a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.since = datetime.now(UTC)
        self.totals: Counts = _empty()
        self.days: dict[str, Counts] = {}
        self.durations: deque[float] = deque(maxlen=LATENCY_SAMPLES)
        # Counted since the last save; the next save adds these to the file.
        self._new_totals: Counts = _empty()
        self._new_days: dict[str, Counts] = {}
        if path is not None:
            saved = self._read()
            if saved is not None:
                self.since, self.totals, self.days = saved

    # ---- recording

    def _add(self, group: str, key: str, n: int = 1, *, daily: bool = False) -> None:
        if n <= 0:
            return
        if group == "tools":
            full = (
                key not in self.totals["tools"]
                and len(self.totals["tools"]) >= MAX_TOOL_NAMES
            )
            if full or not _TOOL_NAME.match(key):
                key = "other"
        self.totals[group][key] += n
        self._new_totals[group][key] += n
        if daily:
            day = datetime.now(UTC).date().isoformat()
            for days in (self.days, self._new_days):
                days.setdefault(day, {g: Counter() for g in DAILY_GROUPS})[group][
                    key
                ] += n
            _drop_old_days(self.days)

    def outcome(self, name: str) -> None:
        """How one request to /api/chat ended (one of OUTCOMES)."""
        self._add("outcomes", name if name in OUTCOMES else "failed", daily=True)

    def turn(self, number: int) -> None:
        """The question's turn in its conversation: 1 for a first question."""
        self._add("turns", str(number) if 1 <= number <= 8 else "9+")

    def tokens(self, kind: str, n: int) -> None:
        if kind in TOKEN_KINDS:
            self._add("tokens", kind, n, daily=True)

    def model_call(self, stop_reason: str | None) -> None:
        self._add("work", "model_calls", daily=True)
        reason = (stop_reason or "unknown").lower()
        self._add("stop_reasons", reason if _STOP_REASON.match(reason) else "other")

    def tool_call(self, name: str, ok: bool) -> None:
        self._add("work", "tool_calls", daily=True)
        self._add("tools", name)
        if not ok:
            self._add("work", "tool_errors", daily=True)

    def answered_in(self, seconds: float) -> None:
        self.durations.append(seconds)

    # ---- reporting

    def snapshot(self, today: dict[str, Any] | None = None) -> dict[str, Any]:
        ordered = sorted(self.durations)
        latency = (
            {
                "p50_ms": round(_percentile(ordered, 0.5) * 1000),
                "p95_ms": round(_percentile(ordered, 0.95) * 1000),
                "samples": len(ordered),
            }
            if ordered
            else {}
        )
        kept = (
            "the counts are also saved to disk and survive a restart; latency covers "
            "answers since this process started"
            if self.path is not None
            else "in memory; a restart starts the count again"
        )
        outcomes = self.totals["outcomes"]
        return {
            "counting_since": self.since.isoformat(),
            "persisted": self.path is not None,
            "note": (
                "Counts of how questions ended, billed tokens, model and tool calls, "
                f"tool names and stop reasons only, never questions, answers or "
                f"addresses; {kept}."
            ),
            "questions": sum(outcomes.values()),
            "outcomes": _sorted(outcomes),
            "tokens": _sorted(self.totals["tokens"]),
            "work": _sorted(self.totals["work"]),
            "tools": _sorted(self.totals["tools"]),
            "stop_reasons": _sorted(self.totals["stop_reasons"]),
            "turns": dict(sorted(self.totals["turns"].items(), key=_turn_order)),
            "answer_latency_ms": latency,
            "today": today or {},
            "by_day": {
                day: {group: _sorted(counts[group]) for group in DAILY_GROUPS}
                for day, counts in sorted(self.days.items())
            },
        }

    # ---- the file (CHAT_USAGE_STATS_FILE)

    def _read(self) -> tuple[datetime, Counts, dict[str, Counts]] | None:
        """The file's counts, or None. An invalid file is moved aside, never overwritten."""
        assert self.path is not None
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning("Chat usage file unreadable, counting from zero: %s", exc)
            return None
        try:
            return _parse(json.loads(raw))
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            aside = self.path.with_name(self.path.name + ".bad")
            logger.warning("Chat usage file is not valid (%s); moved to %s", exc, aside)
            try:
                os.replace(self.path, aside)
            except OSError:
                pass
            return None

    def save(self) -> bool:
        """Add what was counted since the last save to the file; True when written.

        Synchronous: with no await between reading the file and adopting its
        counts, no request can be counted in between and lost.
        """
        if self.path is None:
            return False
        saved = self._read()
        since, totals, days = saved if saved is not None else (self.since, _empty(), {})
        for group, counts in self._new_totals.items():
            totals[group].update(counts)
        for day, groups in self._new_days.items():
            target = days.setdefault(day, {g: Counter() for g in DAILY_GROUPS})
            for group, counts in groups.items():
                target[group].update(counts)
        _drop_old_days(days)
        since = min(since, self.since)
        body = {
            "version": FILE_VERSION,
            "counting_since": since.isoformat(),
            "totals": {group: dict(counts) for group, counts in totals.items()},
            "by_day": {
                day: {group: dict(groups[group]) for group in DAILY_GROUPS}
                for day, groups in sorted(days.items())
            },
        }
        temp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
            os.replace(temp, self.path)  # atomic: a reader sees the old file or the new
        except OSError as exc:
            logger.warning("Chat usage not saved to %s: %s", self.path, exc)
            return False  # the unsaved counts stay queued for the next save
        self.since, self.totals, self.days = since, totals, days
        self._new_totals = _empty()
        self._new_days = {}
        return True


def _sorted(counts: Counter[str]) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _turn_order(item: tuple[str, int]) -> int:
    return 99 if item[0] == "9+" else int(item[0])


def _drop_old_days(days: dict[str, Counts]) -> None:
    for old in sorted(days)[:-MAX_DAYS]:
        del days[old]


def _counter(raw: Any) -> Counter[str]:
    if not isinstance(raw, dict):
        raise TypeError("counts are not an object")
    out: Counter[str] = Counter()
    for key, value in raw.items():
        if not isinstance(key, str):
            raise TypeError("count key is not text")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"not a count: {value!r}")
        if value:
            out[key] = value
    return out


def _parse(body: Any) -> tuple[datetime, Counts, dict[str, Counts]]:
    if not isinstance(body, dict) or body.get("version") != FILE_VERSION:
        raise ValueError("unknown file version")
    since = datetime.fromisoformat(body["counting_since"])
    if since.tzinfo is None:
        raise ValueError("counting_since has no time zone")
    totals = _empty()
    for group, raw in body["totals"].items():
        if group in totals:
            totals[group] = _counter(raw)
    days: dict[str, Counts] = {}
    for day, groups in body["by_day"].items():
        datetime.strptime(day, "%Y-%m-%d")
        days[day] = {g: _counter(groups.get(g, {})) for g in DAILY_GROUPS}
    return since, totals, days


def stats_from_environment() -> ChatStats:
    raw = os.environ.get("CHAT_USAGE_STATS_FILE", "").strip()
    return ChatStats(Path(raw) if raw else None)
