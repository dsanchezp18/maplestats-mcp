"""Every @tool docstring and signature must follow AGENTS.md step 5.

BM25SearchTransform indexes tool docstrings, so a tool without a
`Use for:` line, 8+ `Keywords:` or 8+ `Mots-clés :` terms is harder
(or, for French queries, impossible) to discover. Every tool also takes
a `lang` parameter so callers can pass it uniformly.

The check parses each modules/**/tools.py with `ast` instead of importing
the server, so it runs fast and reports every offending tool at once.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

MODULES = Path(__file__).resolve().parent.parent / "src" / "maplestats_mcp" / "modules"
MIN_TERMS = 8

# Tools allowed to omit the `lang` parameter, each with the reason.
LANG_EXEMPT = {
    # Its arguments name another tool and that tool's own arguments (which
    # may include lang), and `language` already picks the programming
    # language; a separate `lang` would be ambiguous and change nothing.
    "reproduce_code",
}

# A keyword list runs from its label until a blank line, the other list's
# label, another docstring section, or the end of the docstring. Lists
# wrap across lines and sometimes start mid-line ("... Keywords: a, b").
_STOP = (
    r"(?=\n[ \t]*\n|Mots-clés\s*:|Keywords:"
    r"|\n\s*(?:Args|Returns|Raises|Use for|Examples?|Notes?)\s*:|\Z)"
)


def _is_tool_decorator(node: ast.expr) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id == "tool"
    return isinstance(target, ast.Attribute) and target.attr == "tool"


def _tool_functions() -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    found = []
    for path in sorted(MODULES.rglob("tools.py")):
        rel = path.relative_to(MODULES)
        if "_example" in rel.parts or "__tests__" in rel.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                _is_tool_decorator(d) for d in node.decorator_list
            ):
                found.append((str(rel), node))
    return found


def _terms(doc: str, label: str) -> list[str] | None:
    match = re.search(label + r"\s*(.*?)" + _STOP, doc, re.DOTALL)
    if match is None:
        return None
    text = " ".join(match.group(1).split()).rstrip(".").strip()
    return [term.strip() for term in text.split(",") if term.strip()]


TOOLS = _tool_functions()


def _docstring(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    return inspect.cleandoc(ast.get_docstring(node) or "")


def test_tools_were_found() -> None:
    # Guards against the scan silently matching nothing (e.g. a renamed
    # decorator), which would make every other test here pass vacuously.
    assert len(TOOLS) > 100


def test_every_tool_has_use_for_line() -> None:
    missing = [f"{path}::{node.name}" for path, node in TOOLS if "Use for:" not in _docstring(node)]
    assert not missing, "Tools missing a `Use for:` line:\n" + "\n".join(missing)


@pytest.mark.parametrize(
    ("label", "name"),
    [("Keywords:", "Keywords:"), (r"Mots-clés\s*:", "Mots-clés :")],
)
def test_every_tool_has_enough_keywords(label: str, name: str) -> None:
    bad = []
    for path, node in TOOLS:
        terms = _terms(_docstring(node), label)
        if terms is None:
            bad.append(f"{path}::{node.name}: no `{name}` line")
        elif len(terms) < MIN_TERMS:
            bad.append(f"{path}::{node.name}: {len(terms)} terms {terms}")
    assert not bad, f"Tools with fewer than {MIN_TERMS} `{name}` terms:\n" + "\n".join(bad)


def test_every_tool_takes_lang() -> None:
    missing = []
    for path, node in TOOLS:
        if node.name in LANG_EXEMPT:
            continue
        params = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        if "lang" not in {a.arg for a in params}:
            missing.append(f"{path}::{node.name}")
    assert not missing, "Tools without a `lang` parameter:\n" + "\n".join(missing)


def test_lang_exemptions_are_current() -> None:
    names = {node.name for _, node in TOOLS}
    stale = sorted(LANG_EXEMPT - names)
    assert not stale, f"LANG_EXEMPT names tools that no longer exist: {stale}"
