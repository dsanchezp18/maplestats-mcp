"""Recording truncation in `provenance.limits`, and keeping responses a sane size.

Several tools returned hundreds of kilobytes (a few, megabytes) by
default, which crowds out everything else in a model's context. The
rule now: a small default, a hard maximum, and when rows are dropped,
`provenance.limits` says so in one sentence with how many there were
and how to get the rest. `truncation_note` writes that sentence the same
way for every module; `fit_to_budget` trims a list to a byte budget when
a row count alone cannot bound the size (rows with geometry or long
text); `join_limits` merges several notes into the one `limits` string.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import pydantic_core
from pydantic import BaseModel

# Default byte budget for one tool response's data rows. About 200 KB of
# JSON is still several thousand short rows, and leaves room in a model's
# context for the rest of the conversation.
DEFAULT_MAX_BYTES = 200_000

Order = Literal["first", "latest", "top"]

_ORDER_TEXT = {
    "first": "the first",
    "latest": "the most recent",
    "top": "the top",
}


def truncation_note(
    *,
    returned: int,
    total: int | None,
    unit: str = "rows",
    order: Order = "first",
    how_to_get_more: str | None = None,
) -> str | None:
    """One sentence saying what was cut, or None when nothing was.

    `total` may be None when the source does not say how many there are
    but more exist (a page came back full); pass `returned + 1` or more
    in that case only if you know there are more.
    """
    if total is not None and returned >= total:
        return None
    count = f"{total:,}" if total is not None else "more"
    note = f"Returned {_ORDER_TEXT[order]} {returned:,} of {count} {unit}"
    note += "." if not how_to_get_more else f"; {how_to_get_more.rstrip('.')}."
    return note


def join_limits(*parts: str | None) -> str | None:
    """Join the non-empty notes into one `limits` string (None when there are none)."""
    kept = [part.strip().rstrip(".") + "." for part in parts if part and part.strip()]
    return " ".join(kept) or None


def _size(item: Any) -> int:
    if isinstance(item, BaseModel):
        return len(item.model_dump_json())
    return len(json.dumps(item, default=str))


def fit_to_budget[T](
    items: Sequence[T],
    max_bytes: int = DEFAULT_MAX_BYTES,
    size: Callable[[T], int] = _size,
) -> list[T]:
    """The longest prefix of `items` whose serialised size stays within `max_bytes`.

    Always keeps at least one item, so a single oversized row still
    comes back (with the truncation recorded by the caller) rather than
    an empty result that reads as "no data".
    """
    kept: list[T] = []
    used = 0
    for item in items:
        used += size(item) + 1
        if kept and used > max_bytes:
            break
        kept.append(item)
    return kept


# Server-wide budget -----------------------------------------------------------
#
# fit_to_budget above bounds the rows a module knows about. Some tools have no
# bound at all, and a module's own cap is set per tool; trim_payload is the last
# line, applied to every tool's serialised result by
# shared/response_budget.py.

# Lists under these keys are geometry (GeoJSON coordinates, rings of points):
# keeping a prefix of one would draw a different shape, not a shorter list.
_UNTRIMMABLE_KEYS = frozenset({"provenance", "geometry", "coordinates", "geometries", "bbox"})

# Sibling fields that count the rows of the list beside them; updated when that
# list is trimmed so the result does not say 5,000 next to 1,200 rows.
_COUNT_KEYS = ("returned_count", "returned")

# Date fields of time-series rows. A series listed oldest first keeps its most
# recent rows instead of its first: the latest values are what was asked for
# (WDS observations come back in ascending ref_period, confirmed live).
_PERIOD_KEYS = ("ref_period", "reference_period", "ref_date", "period", "date", "time_period")


def _ascending_by_period(items: list[Any]) -> bool:
    first, last = items[0], items[-1]
    if not isinstance(first, dict) or not isinstance(last, dict):
        return False
    for key in _PERIOD_KEYS:
        start, end = first.get(key), last.get(key)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if isinstance(start, str) and isinstance(end, str):
            return start < end
    return False


def response_max_bytes() -> int:
    """The byte budget for one tool result: MAPLE_RESPONSE_MAX_BYTES, default 200,000.

    Below 10,000 bytes the provenance alone would not fit, so smaller
    values are raised to that.
    """
    raw = os.environ.get("MAPLE_RESPONSE_MAX_BYTES", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MAX_BYTES
    except ValueError:
        value = DEFAULT_MAX_BYTES
    return max(10_000, value)


def json_size(value: Any) -> int:
    """Bytes of `value` as compact JSON, as FastMCP sends it."""
    return len(pydantic_core.to_json(value, fallback=str))


@dataclass
class _Found:
    pattern: str  # the path with list indices as [*]
    paths: list[str] = field(default_factory=list)
    lists: list[list[Any]] = field(default_factory=list)
    parents: list[dict[str, Any] | None] = field(default_factory=list)
    sizes: list[int] = field(default_factory=list)

    @property
    def size(self) -> int:
        return sum(self.sizes)


def _collect(
    node: Any,
    path: str,
    pattern: str,
    parent: dict[str, Any] | None,
    found: dict[str, _Found],
) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _UNTRIMMABLE_KEYS or not isinstance(value, dict | list):
                continue
            sub = f"{path}.{key}" if path else str(key)
            sub_pattern = f"{pattern}.{key}" if pattern else str(key)
            _collect(value, sub, sub_pattern, node, found)
    elif isinstance(node, list):
        if len(node) > 1:
            group = found.setdefault(pattern, _Found(pattern))
            group.paths.append(path)
            group.lists.append(node)
            group.parents.append(parent)
            group.sizes.append(json_size(node))
        for index, item in enumerate(node):
            if isinstance(item, dict | list):
                _collect(item, f"{path}[{index}]", f"{pattern}[*]", None, found)


def _pick(found: dict[str, _Found]) -> _Found | None:
    """The largest group of lists, or the part of it that holds most of its bytes.

    `series` (three series) is larger than `series[*].observations`, but
    trimming observations in each keeps every series the caller asked for;
    so descend while one group inside holds at least half the bytes.
    """
    if not found:
        return None
    best = max(found.values(), key=lambda group: group.size)
    while True:
        inner = [
            group
            for group in found.values()
            if group.pattern.startswith(best.pattern + "[*]") and group.size * 2 >= best.size
        ]
        if not inner:
            return best
        best = max(inner, key=lambda group: group.size)


def _ceiling(sizes: list[int], target: int) -> float:
    """The largest per-list size C with sum(min(size, C)) <= target.

    The lists of a group share the cut from the top: a dimension with 300
    members loses members before one with three loses any.
    """
    remaining = max(0, target)
    ordered = sorted(sizes)
    for index, size in enumerate(ordered):
        left = len(ordered) - index
        if size * left > remaining:
            return remaining / left
        remaining -= size
    return float("inf")


@dataclass
class Trimmed:
    """One group of lists trimmed: where, and how many items were kept of how many."""

    pattern: str
    kept: int
    total: int
    lists: int
    latest: bool = False  # the most recent rows were kept, not the first


def trim_payload(payload: dict[str, Any], max_bytes: int, reserve: int = 0) -> list[Trimmed]:
    """Trim the largest lists in `payload`, in place, until it fits `max_bytes`.

    Each round keeps a prefix of the largest group of lists (the same
    field in every item of a parent list counts as one group, trimmed in
    proportion), so the payload stays valid against its schema: only list
    lengths change. `reserve` is room kept for the note the caller adds.
    Returns what was trimmed, empty when the payload already fits.
    Geometry and provenance are never cut.
    """
    trimmed: list[Trimmed] = []
    budget = max_bytes - reserve
    for _ in range(12):
        total = json_size(payload)
        if total <= budget:
            break
        found: dict[str, _Found] = {}
        _collect(payload, "", "", None, found)
        group = _pick(found)
        if group is None:
            break
        ceiling = _ceiling(group.sizes, group.size - (total - budget))
        kept = original = 0
        latest = False
        for items, parent, size in zip(group.lists, group.parents, group.sizes, strict=True):
            tail = _ascending_by_period(items)
            latest = latest or tail
            ordered = items[::-1] if tail else items
            keep = fit_to_budget(ordered, int(min(size, ceiling)), size=json_size)
            original += len(items)
            kept += len(keep)
            if parent is not None:
                for key in _COUNT_KEYS:
                    if parent.get(key) == len(items) and not isinstance(parent[key], bool):
                        parent[key] = len(keep)
                if parent.get("truncated") is False:
                    parent["truncated"] = True
            if tail:
                del items[: len(items) - len(keep)]
            else:
                del items[len(keep) :]
        if kept == original:  # every list already down to one item
            break
        trimmed.append(Trimmed(group.pattern, kept, original, len(group.lists), latest))
    return trimmed
