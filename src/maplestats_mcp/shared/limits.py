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
from collections.abc import Callable, Sequence
from typing import Any, Literal

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
