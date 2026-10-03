"""Every source module, and every tool in it, must have a live smoke test.

Mocked unit tests share the assumptions of the code they test, so they
cannot catch a wrong assumption about a live API; the Earthquakes Canada
module passed all its mocked tests while every live call failed
(2026-09-24). A module is covered by its own scripts/smoke_test_<module>*.py
or by a step in scripts/smoke_test_modules.py.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "src" / "maplestats_mcp" / "modules"
SCRIPTS = ROOT / "scripts"


def _load_smoke_table():
    spec = importlib.util.spec_from_file_location(
        "smoke_modules", SCRIPTS / "smoke_test_modules.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their module through sys.modules while executing.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _covered_by_table() -> frozenset[str]:
    return _load_smoke_table().COVERED_MODULES


def test_every_module_has_a_live_smoke_test():
    modules = sorted(
        p.name for p in MODULES.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))
    )
    own_scripts = {p.stem.removeprefix("smoke_test_") for p in SCRIPTS.glob("smoke_test_*.py")}
    table = _covered_by_table()
    missing = [
        name
        for name in modules
        if name not in table and not any(s.startswith(name) for s in own_scripts)
    ]
    assert not missing, f"No live smoke test for: {missing}. Add steps to smoke_test_modules.py."


# StatCan is one module with 15 sub-APIs (modules/statcan/<sub>/), and a smoke
# script for any one of them used to satisfy the module-level test for all of
# them: statcan/wds had one tool in smoke_test.py and 12 with no live call
# (2026-10-02 review). A sub-API now needs its own smoke_test_statcan_<sub>*.py,
# or a step in smoke_test_modules.py for one of its tools (e.g. pumf).


def test_every_statcan_sub_api_has_its_own_live_smoke_test():
    statcan = MODULES / "statcan"
    subs = sorted(p.parent.name for p in statcan.glob("*/tools.py"))
    scripts = {p.stem for p in SCRIPTS.glob("smoke_test_statcan_*.py")}
    step_tools = {step.tool for step in _load_smoke_table().STEPS}
    missing = []
    for sub in subs:
        has_script = any(
            s == f"smoke_test_statcan_{sub}" or s.startswith(f"smoke_test_statcan_{sub}_")
            for s in scripts
        )
        has_step = any(t.startswith((f"{sub}_", f"statcan_{sub}_")) for t in step_tools)
        if not (has_script or has_step):
            missing.append(sub)
    assert not missing, f"StatCan sub-APIs with no live smoke test of their own: {missing}"


# A module-level script used to satisfy the check for every tool of its module,
# even tools it never called: on 2026-10-03, socrata_list_tags and
# elections_financial_returns_get_financial_return_part had no live call
# anywhere. Every tool now needs one of its own.

# Tools that answer from constants and never call a source, so a live call
# would check nothing the unit tests do not.
LOCAL_TOOLS = frozenset(
    {
        "arcgis_hub_list_portals",
        "ckan_list_portals",
        "socrata_list_portals",
        "elections_results_list_elections",
    }
)


def _tool_calls(tools_py: Path) -> dict[str, set[str]]:
    """Each @tool function in a tools.py and the imported functions it calls.

    `client.search_cubes(...)` counts, `", ".join(...)` does not: only calls
    on a name the file imports (its client module, mostly) are kept.
    """
    tree = ast.parse(tools_py.read_text(encoding="utf-8"))
    imported = {
        alias.asname or alias.name.split(".")[0]
        for node in tree.body
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    tools: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        decorators = [d.func if isinstance(d, ast.Call) else d for d in node.decorator_list]
        if not any(isinstance(d, ast.Name) and d.id == "tool" for d in decorators):
            continue
        tools[node.name] = {
            call.func.attr
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in imported
        }
    return tools


def _own_scripts(module: str, sub: str) -> str:
    """The text of the smoke scripts that belong to a module or StatCan sub-API."""
    prefix = f"smoke_test_statcan_{sub}" if module == "statcan" else f"smoke_test_{module}"
    paths = [p for p in SCRIPTS.glob("smoke_test*.py") if p.stem.startswith(prefix)]
    if module == "statcan":
        # smoke_test.py is the original StatCan check (WDS, SDMX, RDaaS).
        paths.append(SCRIPTS / "smoke_test.py")
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def test_every_tool_has_a_live_step():
    """Every tool is a step in smoke_test_modules.py or is called by its module's script.

    A script calls the client function behind a tool, so the tool counts as
    covered when its name or a client function it calls appears in one of
    its own module's (or StatCan sub-API's) smoke scripts.
    """
    stepped = {step.tool for step in _load_smoke_table().STEPS}
    missing: list[str] = []
    checked = 0
    for tools_py in sorted(MODULES.glob("*/**/tools.py")):
        parts = tools_py.relative_to(MODULES).parts
        if parts[0].startswith(("_", ".")) or "__tests__" in parts:
            continue
        module, sub = parts[0], parts[1] if len(parts) > 2 else ""
        own = _own_scripts(module, sub)
        for tool, calls in _tool_calls(tools_py).items():
            checked += 1
            if tool in stepped or tool in LOCAL_TOOLS or re.search(rf"\b{tool}\b", own):
                continue
            if not any(re.search(rf"\b{call}\b", own) for call in calls):
                missing.append(tool)
    assert checked > 300, f"found only {checked} tools; the tools.py scan is broken"
    assert not missing, f"Tools without a live smoke step: {missing}"


def test_local_tools_exist():
    """A renamed tool must not linger in LOCAL_TOOLS, exempting nothing."""
    names = {tool for tools_py in MODULES.glob("*/**/tools.py") for tool in _tool_calls(tools_py)}
    assert LOCAL_TOOLS <= names, sorted(LOCAL_TOOLS - names)
