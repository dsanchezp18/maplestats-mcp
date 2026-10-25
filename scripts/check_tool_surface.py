"""Check the tool catalogue for breaking changes since the branch left main.

src/maplestats_mcp/tool_catalogue.json lists every tool's name, title, input
and output schema and annotations, the contract clients build against. This
compares that file in the working tree with its version at the merge base
of HEAD and origin/main, and sorts the differences into breaking changes (a
tool or parameter removed or renamed, a type narrowed, a required parameter
added, an output field removed or made nullable), additive ones, and others
to read by hand. tests/test_tool_surface.py fails while a breaking change's
tool is not named in a changelog.d/ fragment (or CHANGELOG.md's Unreleased
section); a `prefix_*` in backticks names a whole family. To see the full
list:

    uv run python scripts/check_tool_surface.py [--base REF]

REF defaults to origin/main, or TOOL_SURFACE_BASE when set (a release tag,
say). Descriptions are left out (tool docstrings and schema "description"
and "title" keys): they change with every wording edit and change nothing a
call accepts or returns.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = "src/maplestats_mcp/tool_catalogue.json"
CHANGELOG = ROOT / "CHANGELOG.md"
FRAGMENTS = ROOT / "changelog.d"
DEFAULT_BASE = "origin/main"

Kind = Literal["breaking", "additive", "other"]

_NOTE_KEYS = frozenset({"description", "title"})
# Values, not schemas: a default of {"title": ...} must survive the strip.
_LITERAL_KEYS = frozenset({"default", "const", "enum", "examples", "required"})
# Mappings from a name to a schema: the names are data, the values schemas.
_SCHEMA_MAPS = frozenset({"properties", "$defs", "definitions", "patternProperties"})
_LOWER_BOUNDS = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties")
_UPPER_BOUNDS = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties")


def strip_notes(schema: Any) -> Any:
    """The schema without its description and title keys."""
    if isinstance(schema, list):
        return [strip_notes(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    stripped: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _NOTE_KEYS:
            continue
        if key in _LITERAL_KEYS:
            stripped[key] = value
        elif key in _SCHEMA_MAPS and isinstance(value, dict):
            stripped[key] = {name: strip_notes(sub) for name, sub in value.items()}
        else:
            stripped[key] = strip_notes(value)
    return stripped


def surface(catalogue: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each catalogued tool's title, schemas and annotations, keyed and sorted by name."""
    tools: dict[str, dict[str, Any]] = {}
    for module in catalogue["modules"].values():
        for tool in module["tools"]:
            output = tool.get("output_schema")
            tools[tool["name"]] = {
                "title": tool.get("title"),
                "input_schema": strip_notes(tool.get("parameters", {})),
                "output_schema": strip_notes(output) if output is not None else None,
                "annotations": tool.get("annotations"),
            }
    return dict(sorted(tools.items()))


def read_catalogue() -> dict[str, Any]:
    return json.loads((ROOT / CATALOGUE).read_text(encoding="utf-8"))


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return done.stdout


def base_catalogue(ref: str) -> tuple[dict[str, Any] | None, str]:
    """The catalogue at the merge base of HEAD and ref, and that commit.

    None and the reason instead when there is no git, no repository (an
    sdist), no such ref (a shallow clone), or no catalogue at the base.
    """
    try:
        base = _git("merge-base", "HEAD", ref).strip()
    except FileNotFoundError:
        return None, "git is not installed"
    except subprocess.CalledProcessError as error:
        reason = error.stderr.strip().splitlines()[-1:] or ["no common commit"]
        return None, f"no merge base of HEAD and {ref} ({reason[0]})"
    try:
        text = _git("show", f"{base}:{CATALOGUE}")
    except subprocess.CalledProcessError:
        return None, f"{CATALOGUE} does not exist at the merge base {base[:12]}"
    return json.loads(text), base


def unreleased_notes(changelog: str) -> str:
    """The text of the changelog's Unreleased section."""
    match = re.search(
        r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## \[|\Z)", changelog, re.MULTILINE | re.DOTALL
    )
    return match.group(1) if match else ""


def pending_notes(changelog: str, fragments: Path = FRAGMENTS) -> str:
    """Everything the next release will say: the Unreleased section and the fragments.

    scripts/build_changelog.py assembles the same files; its README is not a fragment.
    """
    files = sorted(fragments.glob("*.md")) if fragments.is_dir() else []
    texts = [path.read_text(encoding="utf-8") for path in files if path.name != "README.md"]
    return "\n".join([unreleased_notes(changelog), *texts])


def acknowledged(tool: str, notes: str) -> bool:
    """Whether the notes name the tool, or a `prefix_*` family it belongs to."""
    if re.search(rf"(?<!\w){re.escape(tool)}(?!\w)", notes):
        return True
    return any(tool.startswith(prefix) for prefix in re.findall(r"`(\w+)\*`", notes))


def unacknowledged(changes: list[Change], notes: str) -> list[Change]:
    """Breaking changes whose tool the notes do not name."""
    return [c for c in changes if c.kind == "breaking" and not acknowledged(c.tool, notes)]


@dataclass(frozen=True)
class Change:
    kind: Kind
    tool: str
    detail: str


class _SchemaDiff:
    """Compares one tool's old and new input (or output) schema.

    A breaking input change is one that rejects a call the old schema
    accepted (narrowing); a breaking output change is one that returns
    something the old schema ruled out (widening). Any difference this
    class cannot name is reported as "other", so none goes unmentioned.
    """

    def __init__(
        self, tool: str, side: Literal["input", "output"], old_root: Any, new_root: Any
    ) -> None:
        self.tool = tool
        self.side = side
        self.old_root = old_root
        self.new_root = new_root
        self.changes: list[Change] = []

    def _add(self, kind: Kind, path: str, detail: str) -> None:
        if path:
            noun = "parameter" if self.side == "input" else "output field"
            label = f"{noun} `{path}`"
        else:
            label = self.side
        self.changes.append(Change(kind, self.tool, f"{label}: {detail}"))

    def _kind(self, *, narrowing: bool) -> Kind:
        """Narrowing (fewer values allowed) breaks inputs; widening breaks outputs."""
        return "breaking" if narrowing == (self.side == "input") else "additive"

    def compare(self, old: Any, new: Any, path: str = "", seen: frozenset = frozenset()) -> None:
        old, old_ref = _resolve(old, self.old_root)
        new, new_ref = _resolve(new, self.new_root)
        # Recursive models refer back to themselves; stop at the second visit.
        if old_ref or new_ref:
            if (old_ref, new_ref) in seen:
                return
            seen = seen | {(old_ref, new_ref)}
        before = len(self.changes)
        if old.get("default") != new.get("default"):
            self._add(
                "other",
                path,
                f"default changed from {_show(old.get('default'))} to {_show(new.get('default'))}",
            )
        old_branches = _branches(old, self.old_root)
        new_branches = _branches(new, self.new_root)
        old_kinds = _kinds(old_branches)
        new_kinds = _kinds(new_branches)
        shown = f"from {_show_kinds(old_kinds)} to {_show_kinds(new_kinds)}"
        if not _covers(new_kinds, old_kinds):
            self._add(self._kind(narrowing=True), path, f"type narrowed {shown}")
        elif not _covers(old_kinds, new_kinds):
            self._add(self._kind(narrowing=False), path, f"type widened {shown}")
        self._compare_values(old_branches, new_branches, path)
        for kind in sorted((old_kinds & new_kinds) - {"null"}):
            old_branch = _single(old_branches, kind)
            new_branch = _single(new_branches, kind)
            if old_branch is not None and new_branch is not None:
                self._compare_branch(old_branch, new_branch, path, seen)
        if len(self.changes) == before and old != new:
            self._add("other", path, "schema changed in a way this check does not name")

    def _compare_values(self, old_branches, new_branches, path: str) -> None:
        old_values = _values(old_branches)
        new_values = _values(new_branches)
        if old_values == new_values:
            return
        if old_values is not None and new_values is not None:
            removed = sorted(old_values - new_values)
            added = sorted(new_values - old_values)
            if removed:
                self._add(
                    self._kind(narrowing=True),
                    path,
                    f"values removed: {', '.join(removed)}",
                )
            if added:
                self._add(
                    self._kind(narrowing=False),
                    path,
                    f"values added: {', '.join(added)}",
                )
        elif new_values is not None:
            limited = ", ".join(sorted(new_values))
            self._add(self._kind(narrowing=True), path, f"now limited to {limited}")
        else:
            assert old_values is not None
            limited = ", ".join(sorted(old_values))
            self._add(self._kind(narrowing=False), path, f"no longer limited to {limited}")

    def _compare_branch(self, old: dict, new: dict, path: str, seen: frozenset) -> None:
        for key in _LOWER_BOUNDS + _UPPER_BOUNDS:
            if old.get(key) == new.get(key):
                continue
            lower = key in _LOWER_BOUNDS
            if old.get(key) is None:
                narrows = True
            elif new.get(key) is None:
                narrows = False
            else:
                narrows = new[key] > old[key] if lower else new[key] < old[key]
            self._add(
                self._kind(narrowing=narrows),
                path,
                f"{key} changed from {_show(old.get(key))} to {_show(new.get(key))}",
            )
        for key in ("pattern", "format"):
            if old.get(key) != new.get(key):
                self._add(
                    "other",
                    path,
                    f"{key} changed from {_show(old.get(key))} to {_show(new.get(key))}",
                )
        if "items" in old and "items" in new:
            self.compare(old["items"], new["items"], f"{path}[]", seen)
        old_extra = old.get("additionalProperties", True)
        new_extra = new.get("additionalProperties", True)
        if isinstance(old_extra, dict) and isinstance(new_extra, dict):
            self.compare(old_extra, new_extra, _join(path, "*"), seen)
        elif old_extra is not False and new_extra is False:
            self._add(self._kind(narrowing=True), path, "extra keys no longer allowed")
        elif old_extra is False and new_extra is not False:
            self._add(self._kind(narrowing=False), path, "extra keys now allowed")
        if "properties" in old or "properties" in new:
            self._compare_properties(old, new, path, seen)

    def _compare_properties(self, old: dict, new: dict, path: str, seen: frozenset) -> None:
        old_props = old.get("properties", {})
        new_props = new.get("properties", {})
        old_required = set(old.get("required", []))
        new_required = set(new.get("required", []))
        removed = [name for name in old_props if name not in new_props]
        added = [name for name in new_props if name not in old_props]
        # A removed and an added property with the same schema read as a rename.
        for old_name in list(removed):
            old_schema = _resolve(old_props[old_name], self.old_root)[0]
            for new_name in added:
                if _resolve(new_props[new_name], self.new_root)[0] == old_schema:
                    removed.remove(old_name)
                    added.remove(new_name)
                    self._add("breaking", _join(path, old_name), f"renamed to `{new_name}`")
                    break
        for name in removed:
            self._add("breaking", _join(path, name), "removed")
        for name in added:
            if self.side == "input" and name in new_required:
                self._add("breaking", _join(path, name), "added as required")
            else:
                self._add("additive", _join(path, name), "added")
        for name in old_props:
            if name not in new_props:
                continue
            child = _join(path, name)
            if self.side == "input" and name in new_required and name not in old_required:
                self._add("breaking", child, "now required")
            elif self.side == "input" and name in old_required and name not in new_required:
                self._add("additive", child, "now optional")
            elif self.side == "output" and (name in old_required) != (name in new_required):
                state = "now" if name in new_required else "no longer"
                self._add("other", child, f"{state} marked required")
            self.compare(old_props[name], new_props[name], child, seen)


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def _resolve(schema: Any, root: Any) -> tuple[dict, str | None]:
    """Follow a local $ref ("#/$defs/Name"); return the schema and the ref followed."""
    if not isinstance(schema, dict):
        # JSON Schema allows true/false as a schema: anything / nothing.
        return ({} if schema else {"not": {}}), None
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return schema, None
    target: Any = root
    for part in ref[2:].split("/"):
        target = target.get(part, {}) if isinstance(target, dict) else {}
    merged = {**target, **{k: v for k, v in schema.items() if k != "$ref"}}
    return merged, ref


def _branches(schema: dict, root: Any) -> list[dict]:
    """The alternatives an anyOf/oneOf lists, flattened; otherwise the schema itself."""
    alternatives = schema.get("anyOf") or schema.get("oneOf")
    if not alternatives:
        return [schema]
    flat: list[dict] = []
    for alternative in alternatives:
        flat.extend(_branches(_resolve(alternative, root)[0], root))
    return flat


def _branch_kinds(branch: dict) -> set[str]:
    declared = branch.get("type")
    if isinstance(declared, str):
        return {declared}
    if isinstance(declared, list):
        return set(declared)
    values = [branch["const"]] if "const" in branch else branch.get("enum")
    if values is not None:
        return {_json_type(value) for value in values}
    if "properties" in branch:
        return {"object"}
    if "items" in branch:
        return {"array"}
    return {"any"}


def _kinds(branches: list[dict]) -> set[str]:
    kinds: set[str] = set()
    for branch in branches:
        kinds |= _branch_kinds(branch)
    return kinds


def _covers(wider: set[str], narrower: set[str]) -> bool:
    if "any" in wider:
        return True
    return all(kind in wider or (kind == "integer" and "number" in wider) for kind in narrower)


def _single(branches: list[dict], kind: str) -> dict | None:
    """The one branch of this JSON type, or None when there are several."""
    matches = [branch for branch in branches if kind in _branch_kinds(branch)]
    return matches[0] if len(matches) == 1 else None


def _values(branches: list[dict]) -> set[str] | None:
    """Every allowed non-null value, as JSON text; None when any value of its type is allowed."""
    values: set[str] = set()
    for branch in branches:
        if branch.get("type") == "null":
            continue
        if "const" in branch:
            values.add(_show(branch["const"]))
        elif "enum" in branch:
            values.update(_show(value) for value in branch["enum"] if value is not None)
        else:
            return None
    return values


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "array" if isinstance(value, list) else "object"


def _show(value: Any) -> str:
    return "none" if value is None else json.dumps(value, sort_keys=True, ensure_ascii=False)


def _show_kinds(kinds: set[str]) -> str:
    return " | ".join(sorted(kinds))


def _diff_tool(name: str, old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    changes: list[Change] = []
    if old.get("title") != new.get("title"):
        detail = f"title changed from {_show(old.get('title'))} to {_show(new.get('title'))}"
        changes.append(Change("other", name, detail))
    old_hints = old.get("annotations") or {}
    new_hints = new.get("annotations") or {}
    for hint in sorted(old_hints.keys() | new_hints.keys()):
        if old_hints.get(hint) != new_hints.get(hint):
            detail = (
                f"annotation {hint} changed from {_show(old_hints.get(hint))} "
                f"to {_show(new_hints.get(hint))}"
            )
            changes.append(Change("other", name, detail))
    inputs = _SchemaDiff(name, "input", old["input_schema"], new["input_schema"])
    inputs.compare(old["input_schema"], new["input_schema"])
    changes += inputs.changes
    old_output = old.get("output_schema")
    new_output = new.get("output_schema")
    if old_output is not None and new_output is None:
        changes.append(Change("breaking", name, "output schema removed"))
    elif old_output is None and new_output is not None:
        changes.append(Change("additive", name, "output schema added"))
    elif old_output is not None and new_output is not None:
        outputs = _SchemaDiff(name, "output", old_output, new_output)
        outputs.compare(old_output, new_output)
        changes += outputs.changes
    return changes


def diff_surfaces(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]) -> list[Change]:
    """Every difference between two surfaces, in tool order."""
    changes: list[Change] = []
    for name in sorted(old.keys() | new.keys()):
        if name not in new:
            changes.append(Change("breaking", name, "tool removed"))
        elif name not in old:
            changes.append(Change("additive", name, "tool added"))
        else:
            changes += _diff_tool(name, old[name], new[name])
    return changes


def format_changes(changes: list[Change], missing: list[Change], base: str) -> str:
    sections = (
        ("breaking", "Breaking changes"),
        ("additive", "Additive changes"),
        ("other", "Other changes (read them in the catalogue diff)"),
    )
    lines = [f"Tool surface changes in {CATALOGUE} since {base[:12]}:"]
    for kind, heading in sections:
        found = [change for change in changes if change.kind == kind]
        if found:
            lines += ["", f"{heading}: {len(found)}"]
            for change in found:
                flag = "  [not in CHANGELOG]" if change in missing else ""
                lines.append(f"  - {change.tool}: {change.detail}{flag}")
    if missing:
        tools = ", ".join(sorted({change.tool for change in missing}))
        lines += [
            "",
            f"Name these tools in a changelog.d/ fragment, with what replaces them: {tools}.",
            "A `prefix_*` in backticks covers a family of tools.",
        ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Breaking changes to the tool catalogue.")
    parser.add_argument("--base", default=os.environ.get("TOOL_SURFACE_BASE", DEFAULT_BASE))
    args = parser.parse_args()
    old, base = base_catalogue(args.base)
    if old is None:
        print(f"Cannot compare: {base}.")
        return 2
    changes = diff_surfaces(surface(old), surface(read_catalogue()))
    if not changes:
        print(f"No tool surface changes since {base[:12]}.")
        return 0
    missing = unacknowledged(changes, pending_notes(CHANGELOG.read_text(encoding="utf-8")))
    print(format_changes(changes, missing, base))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
