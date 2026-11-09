"""Brief results: the same answer in fewer tokens, unless the caller asks for detail='full'.

In the Maple Test (2026-11-03) MapleStats cost the most per question of every
server, USD 0.116, because each result carried, for every series and every
observation, the whole of what a reader might ever want: a JSON object per
observation with a dozen decoded codes, a licence paragraph, a member list
that repeats the series title, the reproduce hint. A model reads all of that
on every call.

`shape()` rewrites a tool's structured result in one of two ways:

- **brief** (the default): keeps what an answer needs to be right and citable:
  values, periods, units and scale, geography and members (the series title),
  the citation line, status and quality flags that differ from "normal", every
  caveat and limit in provenance (seasonal adjustment, revisions, "newer data
  exist", what was cut), the source URL, the licence's name and link and
  whether commercial use is allowed. It drops what repeats or what only a
  script needs: queried_at, cached, schema_name, freshness prose, the
  reproduce hint (said once, in `detail`), per-observation codes
  (decimals, status_code, ...), default flags ("normal", "none", "public"),
  empty fields, and members or titles the citation or series title already
  states. A list of more than CSV_MIN_ROWS flat rows becomes one CSV text
  block ({"format": "csv", "rows": n, "csv": "header\\nrow..."}).
- **full**: today's result, field for field, except that a note, caveat or
  licence repeated in several items of one list is stated once in
  `shared_notes` and each item says "shared_notes[i]" (both modes do this).

Brief only changes what the model reads. The tools, their output schemas and
everything reproduce_code and reproduce_workbook read are unchanged: those
call with detail='full', and `expand_tables()` turns CSV blocks back into rows
for code that reads results (the chat demo, the Maple Test replay).
"""

from __future__ import annotations

import copy
import csv
import io
import json
import re
from collections.abc import Mapping
from typing import Any, Literal

from maplestats_mcp.shared.i18n import pick

Detail = Literal["brief", "full"]
DEFAULT_DETAIL: Detail = "brief"

# A list of rows longer than this is written as CSV in a brief result; a short one
# stays JSON, which reads as clearly and costs about the same.
CSV_MIN_ROWS = 6

# Tools whose results are already shaped for the reader, or are read by code:
# they keep their own format. search_tools and plan_query return text and plans;
# check_answer returns problems; reproduce_* return scripts and files.
EXEMPT_TOOLS = frozenset(
    {
        "search_tools",
        "call_tool",
        "plan_query",
        "check_answer",
        "reproduce_code",
        "reproduce_workbook",
    }
)

# Provenance fields a brief result keeps. Dropped: queried_at, cached, lang,
# schema_name, freshness and reproduce (said once, in the result's `detail`).
_PROVENANCE_KEPT = (
    "source",
    "url",
    "as_of",
    "coverage",
    "limits",
    "licence",
    "commercial_use",
    "caveats",
)

# Codes StatCan sends beside their decoded text, and display hints: the decoded
# `status`, `symbol` and `security_level` stay when they say something.
_ROW_CODES = frozenset(
    {
        "decimals",
        "scalar_factor_code",
        "symbol_code",
        "status_code",
        "security_level_code",
        "frequency_code",
    }
)
# Values that only restate the default: dropped from a brief row.
_DEFAULT_FLAGS: dict[str, tuple[Any, ...]] = {
    "status": ("normal", "normale"),
    "symbol": ("none", "aucun"),
    "security_level": ("public",),
    "scale_multiplier": (1,),
    "terminated": (False, 0),
}
# Keys whose None is the value itself (a missing observation), not an empty field.
_VALUE_KEYS = frozenset({"value", "values"})
# Fields that hold notes, caveats or licence text: repeated in several items of one
# list, they are stated once in shared_notes.
_SHARED_KEYS = frozenset(
    {"notes", "note", "caveats", "caveat", "footnotes", "licence", "license", "terms"}
)
# A shorter text is cheaper to repeat than to refer to.
_SHARED_MIN_CHARS = 40
_SHARED_REF = "shared_notes[{i}]"

_JSON_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
# "Name (https://link)" at the head of a licence text: its name and link.
_LICENCE_HEAD = re.compile(r"^(.{3,160}?\(https?://[^)\s]+\))")

Scalar = str | int | float | bool | None


def brief_note(lang: str) -> str:
    """The one line a brief result carries instead of the full provenance."""
    return pick(
        lang,
        "brief: pass detail='full' for full provenance and every field; "
        "reproduce_code gives scripts that fetch the same data.",
        "bref : passez detail='full' pour la provenance complète et tous les champs ; "
        "reproduce_code donne des scripts qui récupèrent les mêmes données.",
    )


def normalize_detail(value: Any) -> Detail:
    """'full' when asked for it (any case), else the brief default."""
    return "full" if str(value or "").strip().lower() == "full" else "brief"


def exempt(tool: str) -> bool:
    """Whether `tool` keeps its own format (see EXEMPT_TOOLS; any search tool too)."""
    return tool in EXEMPT_TOOLS or "search" in tool


def shape(
    payload: dict[str, Any], detail: Detail, lang: str = "en", wrapped: bool = False
) -> dict[str, Any] | None:
    """The result to send for `detail`, or None when it is `payload` unchanged.

    `payload` is a tool's structured content; `wrapped` when FastMCP wrapped a
    non-object result as {"result": ...}. It is not modified.
    """
    out = copy.deepcopy(payload)
    changed = share_repeated_notes(out)
    if detail == "brief":
        out = _brief(out, lang, wrapped)
        changed = True
    return out if changed else None


# ---- shared notes (both modes) -----------------------------------------------------


def share_repeated_notes(payload: dict[str, Any]) -> bool:
    """State once the notes repeated across items of a list; True when any were.

    A note (or caveat, footnote, licence) that two or more items of the same list
    carry moves to payload["shared_notes"]; each item then holds "shared_notes[i]"
    in its place, so the item's field keeps its type.
    """
    shared: list[str] = list(payload.get("shared_notes") or [])
    found = False

    def visit(node: Any, depth: int) -> None:
        nonlocal found
        if depth > 6:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key != "provenance":
                    visit(value, depth + 1)
        elif isinstance(node, list):
            items = [item for item in node if isinstance(item, dict)]
            if len(items) >= 2:
                found = _share_in(items, shared) or found
            for item in node:
                visit(item, depth + 1)

    visit(payload, 0)
    if found:
        payload["shared_notes"] = shared
    return found


def _note_holders(item: dict[str, Any]) -> list[dict[str, Any]]:
    """The item and its nested dicts one level down (a series' `context`)."""
    return [item, *(v for k, v in item.items() if isinstance(v, dict) and k != "provenance")]


def _texts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _share_in(items: list[dict[str, Any]], shared: list[str]) -> bool:
    counts: dict[str, int] = {}
    for item in items:
        seen: set[str] = set()
        for holder in _note_holders(item):
            for key in _SHARED_KEYS.intersection(holder):
                seen.update(t for t in _texts(holder[key]) if len(t) >= _SHARED_MIN_CHARS)
        for text in seen:
            counts[text] = counts.get(text, 0) + 1
    repeated = {text for text, n in counts.items() if n >= 2}
    if not repeated:
        return False
    for text in sorted(repeated, key=list(counts).index):
        if text not in shared:
            shared.append(text)
    ref = {text: _SHARED_REF.format(i=shared.index(text)) for text in repeated}
    for item in items:
        for holder in _note_holders(item):
            for key in _SHARED_KEYS.intersection(holder):
                value = holder[key]
                if isinstance(value, str) and value in ref:
                    holder[key] = ref[value]
                elif isinstance(value, list):
                    holder[key] = [ref.get(v, v) if isinstance(v, str) else v for v in value]
    return True


# ---- brief --------------------------------------------------------------------------


def _brief(payload: dict[str, Any], lang: str, wrapped: bool) -> dict[str, Any]:
    body: Any = payload.get("result") if wrapped else payload
    body = _clean(body)
    if isinstance(body, dict):
        body["detail"] = brief_note(lang)
    return {**payload, "result": body} if wrapped else body


def licence_id(text: str) -> str:
    """A licence's name and link, without the attribution and conditions after them."""
    head = _LICENCE_HEAD.match(text.strip())
    if head:
        return head.group(1)
    first = re.split(r"(?<=[.;])\s", text.strip(), maxsplit=1)[0]
    return first if len(first) <= 200 else first[:197] + "..."


def _brief_provenance(provenance: dict[str, Any]) -> dict[str, Any]:
    kept = {
        k: provenance.get(k) for k in _PROVENANCE_KEPT if provenance.get(k) not in (None, "", [])
    }
    licence = kept.get("licence")
    if isinstance(licence, str):
        kept["licence"] = licence_id(licence)
    return kept


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _clean(node: Any, key: str = "", in_rows: bool = False) -> Any:
    """`node` without the fields a brief result drops, its long row lists as CSV.

    `key` is the field `node` is the value of; `in_rows` is true for the items of
    a list of objects.
    """
    if isinstance(node, list):
        rows = all(isinstance(v, dict) for v in node) and bool(node)
        cleaned = [_clean(v, key, in_rows=rows) for v in node]
        return _compact_list(cleaned) if rows else cleaned
    if not isinstance(node, dict):
        return node
    node = _without_restated(node)
    out: dict[str, Any] = {}
    for k, v in node.items():
        if k == "provenance" and isinstance(v, dict):
            out[k] = _brief_provenance(v)
            continue
        if in_rows and k in _ROW_CODES:
            continue
        if in_rows and k in _DEFAULT_FLAGS and v in _DEFAULT_FLAGS[k]:
            continue
        # A StatCan observation's release time: the series' citation states the
        # table's release, and a script that needs each revision's date asks for full.
        if in_rows and key == "observations" and k == "release_time":
            continue
        if _empty(v) and k not in _VALUE_KEYS:
            continue
        out[k] = _clean(v, k)
    return out


def _without_restated(node: dict[str, Any]) -> dict[str, Any]:
    """`node` without what another of its fields already says.

    A StatCan series' `members` are its `series_title` split on ";", and its table
    title and release time are in its `citation`.
    """
    item = dict(node)
    citation = item.get("citation")
    if isinstance(citation, str):
        title = item.get("table_title")
        if isinstance(title, str) and title in citation:
            del item["table_title"]
        released = item.get("table_release_time")
        if isinstance(released, str) and released[:10] in citation:
            del item["table_release_time"]
    members = item.get("members")
    series_title = item.get("series_title")
    if isinstance(members, list) and isinstance(series_title, str):
        names = [m.get("member") for m in members if isinstance(m, dict)]
        if all(isinstance(n, str) and n in series_title for n in names):
            del item["members"]
    return item


def _cell(value: Scalar) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return json.dumps(value)
    return str(value)


Path = tuple[str, ...]
# Nested objects in a row are flattened this many levels deep (a CMHC row's
# values -> Single -> value); a row nested deeper, or holding a list, stays JSON.
_MAX_ROW_DEPTH = 3


def _flat(row: dict[str, Any], prefix: Path = ()) -> dict[Path, Scalar] | None:
    """The row's values by their path of keys; None if it holds a list or nests deeper."""
    flat: dict[Path, Scalar] = {}
    for key, value in row.items():
        path = (*prefix, str(key))
        if isinstance(value, dict):
            if len(path) >= _MAX_ROW_DEPTH:
                return None
            inner = _flat(value, path)
            if inner is None:
                return None
            flat.update(inner)
        elif isinstance(value, list):
            return None
        else:
            flat[path] = value
    return flat


def _compact_list(rows: list[Any]) -> Any:
    """A long list of flat rows as one CSV block; anything else as it was.

    The header names a nested value by its keys joined with "."; when any value is
    nested, `columns` also lists each column's keys, since a key may itself hold a
    dot (Valet's "BD.CDN.10YR.DQ.YLD").
    """
    if len(rows) < CSV_MIN_ROWS or not all(isinstance(r, dict) for r in rows):
        return rows
    flat = [_flat(r) for r in rows]
    if any(f is None for f in flat):
        return rows
    columns: dict[Path, None] = {}
    for f in flat:
        assert f is not None
        columns.update(dict.fromkeys(f))
    if not columns:
        return rows
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([".".join(c) for c in columns])
    for f in flat:
        assert f is not None
        writer.writerow([_cell(f.get(c)) for c in columns])
    block: dict[str, Any] = {"format": "csv", "rows": len(rows)}
    if any(len(c) > 1 for c in columns):
        block["columns"] = [list(c) for c in columns]
    block["csv"] = buffer.getvalue()
    return block


# ---- reading a brief result back ---------------------------------------------------


def _parse_cell(text: str) -> Scalar:
    if text == "":
        return None
    if _JSON_NUMBER.fullmatch(text):
        return json.loads(text)
    if text in ("true", "false"):
        return text == "true"
    return text


def csv_rows(block: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The rows of one CSV block: numbers as numbers, nested values nested again.

    An empty cell is left out of its row, except a `value`, which is null.
    """
    reader = csv.reader(io.StringIO(str(block.get("csv", ""))))
    header = next(reader, [])
    listed = block.get("columns")
    paths: list[Path] = (
        [tuple(str(k) for k in c) for c in listed]
        if isinstance(listed, list) and len(listed) == len(header)
        else [(name,) for name in header]
    )
    rows = []
    for record in reader:
        row: dict[str, Any] = {}
        for path, text in zip(paths, record, strict=False):
            value = _parse_cell(text)
            node = row
            for key in path[:-1]:
                node = node.setdefault(key, {})
            if value is not None or path[-1] in _VALUE_KEYS:
                node[path[-1]] = value
        rows.append(row)
    return rows


def is_csv_block(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("format") == "csv"
        and isinstance(value.get("csv"), str)
    )


def expand_tables(node: Any) -> Any:
    """`node` with every CSV block turned back into a list of row objects."""
    if is_csv_block(node):
        return csv_rows(node)
    if isinstance(node, dict):
        return {k: expand_tables(v) for k, v in node.items()}
    if isinstance(node, list):
        return [expand_tables(v) for v in node]
    return node


def estimated_tokens(chars: int) -> int:
    """About four characters per token for JSON and CSV in English and French."""
    return (chars + 3) // 4
