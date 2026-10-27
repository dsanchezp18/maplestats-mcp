"""Fitness-for-use notes: the cautions that apply to one tool call.

notes_for(tool, arguments, lang) returns the notes of every rule in
fitness_rules.RULES that the call matches, by tool-name prefix or by a
Statistics Canada table named in its arguments, in the rules' order. It is
pure and does no I/O: the index is built once at import, and a call only
walks its arguments.

A table counts in either spelling. The dashed table number ("14-10-0287",
"14-10-0287-01") is found in any string argument, since nothing else has that
shape. A bare number (14100287, "1410028701") counts only under an argument
that holds a product id: a run of 8 digits elsewhere could be a vector id,
which cannot be mapped to its table without a call.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from maplestats_mcp.shared.fitness_rules import RULES, FitnessRule
from maplestats_mcp.shared.i18n import french_text, normalize_lang

# Argument names that hold a StatCan product id, across the wds_, sdmx_ and
# statcan_ tools (checked in tool_catalogue.json on 2026-10-27).
_PRODUCT_ID_KEYS = frozenset(
    {
        "product_id",
        "product_ids",
        "productid",
        "pid",
        "statcan_pid",
        "real_time_product_id",
        "regular_product_id",
        "table",
        "table_id",
        "table_number",
    }
)

# Same shapes as the planner's table-number cue (modules/planner/topics.py):
# every WDS table is SS10NNNN with a subject of 10 to 46 or 98; a sequence that
# reads as a year is a date ("10-10-2023"), not a table.
_SUBJECT = r"(?:[1-3]\d|4[0-6]|98)"
_SEQUENCE = r"(?!(?:19|20)\d{2})\d{4}"
_TABLE_NUMBER = re.compile(rf"(?<![0-9-])({_SUBJECT})-10-({_SEQUENCE})(?:-\d{{2}})?(?![0-9-])")
_PRODUCT_ID = re.compile(rf"^({_SUBJECT}10{_SEQUENCE})(?:\d{{2}})?$")
# Arguments nest at most a level or two (a list of ids, a filters dict); the
# cap only guards against a pathological payload.
_MAX_DEPTH = 4


def _index() -> tuple[dict[int, tuple[int, ...]], tuple[tuple[str, int], ...]]:
    by_product: dict[int, list[int]] = {}
    prefixes: list[tuple[str, int]] = []
    for position, rule in enumerate(RULES):
        for product_id in rule.product_ids:
            by_product.setdefault(product_id, []).append(position)
        prefixes.extend((prefix, position) for prefix in rule.tool_prefixes)
    return {pid: tuple(rules) for pid, rules in by_product.items()}, tuple(prefixes)


_BY_PRODUCT, _PREFIXES = _index()


def _bare_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    match = _PRODUCT_ID.match(text) or _PRODUCT_ID.match(text.replace("-", ""))
    return int(match.group(1)) if match else None


def _collect(value: Any, product_key: bool, found: set[int], depth: int) -> None:
    if depth > _MAX_DEPTH:
        return
    if isinstance(value, str):
        found.update(int(subject + "10" + seq) for subject, seq in _TABLE_NUMBER.findall(value))
    if product_key:
        bare = _bare_id(value)
        if bare is not None:
            found.add(bare)
    if isinstance(value, Mapping):
        for key, item in value.items():
            _collect(item, str(key).lower() in _PRODUCT_ID_KEYS, found, depth + 1)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _collect(item, product_key, found, depth + 1)


def product_ids_in(arguments: Mapping[str, Any]) -> set[int]:
    """The 8-digit StatCan product ids named in a tool call's arguments."""
    found: set[int] = set()
    _collect(arguments, False, found, 0)
    return found


def rules_for(tool: str, arguments: Mapping[str, Any]) -> list[FitnessRule]:
    """The rules a call matches, in RULES order, each once."""
    positions: set[int] = set()
    for prefix, position in _PREFIXES:
        if tool.startswith(prefix) and not tool.startswith(RULES[position].exclude_prefixes):
            positions.add(position)
    for product_id in product_ids_in(arguments or {}):
        positions.update(_BY_PRODUCT.get(product_id, ()))
    return [RULES[position] for position in sorted(positions)]


def note_text(rule: FitnessRule, lang: str) -> str:
    """The rule's note in `lang`, French with its no-break spaces."""
    return french_text(rule.note_fr) if normalize_lang(lang) == "fr" else rule.note_en


def notes_for(tool: str, arguments: Mapping[str, Any], lang: str) -> list[str]:
    """Fitness-for-use notes for one tool call; [] when no rule applies."""
    return [note_text(rule, lang) for rule in rules_for(tool, arguments)]
