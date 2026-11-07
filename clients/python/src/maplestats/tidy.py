"""Turn a tool result into rows, the way the server's reproduce_workbook does.

A line-for-line port of `rows_and_left_out` in
`src/maplestats_mcp/modules/reproduce/workbook.py`; keep the two in step.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

Record = dict[str, Any]


def _record_lists(payload: Any) -> list[list[Record]]:
    """Every list of objects in the payload, three levels deep, provenance aside."""
    found: list[list[Record]] = []
    frontier: list[Any] = [payload]
    for _ in range(4):
        next_frontier: list[Any] = []
        for node in frontier:
            if (
                isinstance(node, list)
                and node
                and all(isinstance(v, dict) for v in node)
            ):
                found.append(node)
            elif isinstance(node, dict):
                next_frontier += [v for k, v in node.items() if k != "provenance"]
        frontier = next_frontier
    return found


def _flatten(record: Record, prefix: str = "") -> Record:
    """Nested objects become dotted names; lists become text."""
    flat: Record = {}
    for key, value in record.items():
        if key == "provenance":
            continue
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{name}."))
        elif isinstance(value, list):
            scalar = all(not isinstance(v, dict | list) for v in value)
            flat[name] = (
                "; ".join("" if v is None else str(v) for v in value)
                if scalar
                else json.dumps(value, ensure_ascii=False, default=str)
            )
        else:
            flat[name] = value
    return flat


def _holds(node: Any, best: list[Record]) -> bool:
    if node is best:
        return True
    if isinstance(node, dict):
        return any(_holds(v, best) for k, v in node.items() if k != "provenance")
    return False


def _left_out(node: Any, best: list[Record], prefix: str = "") -> Record:
    """The result's fields outside the rows, by dotted name."""
    left: Record = {}
    if not isinstance(node, dict):
        return left
    for key, value in node.items():
        name = f"{prefix}{key}"
        if key == "provenance" or value is best:
            continue
        if isinstance(value, dict) and _holds(value, best):
            left.update(_left_out(value, best, f"{name}."))
        elif isinstance(value, dict):
            left[name] = "[object]"
        elif isinstance(value, list):
            left[name] = "[list]"
        else:
            left[name] = value
    return left


def rows_and_left_out(payload: Any) -> tuple[list[Record], Record]:
    """The table a result holds (its largest list of objects) and what it leaves out.

    When each object holds its own list of objects (a series and its
    observations), every inner object is one row carrying the outer
    object's other fields.
    """
    if isinstance(payload, dict) and isinstance(payload.get("result"), list):
        payload = payload["result"]
    lists = _record_lists(payload)
    if not lists:
        if isinstance(payload, dict):
            single = {k: v for k, v in payload.items() if k != "provenance"}
            return ([_flatten(single)] if single else []), {}
        return [], {}
    best = max(lists, key=len)
    left = _left_out(payload, best)
    child_keys = [
        key
        for key, value in best[0].items()
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value)
    ]
    if not child_keys:
        return [_flatten(row) for row in best], left
    key = max(child_keys, key=lambda k: sum(len(row.get(k) or []) for row in best))
    rows: list[Record] = []
    for parent in best:
        outer = _flatten({k: v for k, v in parent.items() if k != key})
        rows += [{**outer, **_flatten(child)} for child in parent.get(key) or []]
    return rows, left


def clean_name(name: str) -> str:
    """snake_case, ASCII only, as janitor::clean_names does."""
    plain = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", plain)
    return re.sub(r"[^0-9a-z]+", "_", split.lower()).strip("_") or "x"


def clean_names(names: list[str]) -> list[str]:
    """clean_name for each, with names that clean alike numbered."""
    taken: set[str] = set()
    out: list[str] = []
    for name in (clean_name(n) for n in names):
        candidate, suffix = name, 2
        while candidate in taken:
            candidate = f"{name}_{suffix}"
            suffix += 1
        taken.add(candidate)
        out.append(candidate)
    return out


def provenance(payload: Any) -> Record:
    """The result's provenance, or its first item's for a list result."""
    if isinstance(payload, dict) and isinstance(payload.get("result"), list):
        payload = payload["result"]
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        payload = payload[0]
    found = payload.get("provenance") if isinstance(payload, dict) else None
    return found if isinstance(found, dict) else {}


def citations(payload: Any) -> list[str]:
    """Each distinct `citation` string in the result, else one built from provenance."""
    found: list[str] = []
    stack: list[Any] = [payload]
    while stack:
        node = stack.pop(0)
        if isinstance(node, dict):
            value = node.get("citation")
            if isinstance(value, str) and value not in found:
                found.append(value)
            stack += list(node.values())
        elif isinstance(node, list):
            stack += node
    if found:
        return found
    source = provenance(payload)
    if not source:
        return []
    parts = [f"Source: {source.get('source', 'unknown')}."]
    if source.get("url"):
        parts.append(str(source["url"]))
    if source.get("queried_at"):
        parts.append(f"(queried {source['queried_at']})")
    return [" ".join(parts)]
