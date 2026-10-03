"""Every source module must have a live smoke test.

Mocked unit tests share the assumptions of the code they test, so they
cannot catch a wrong assumption about a live API; the Earthquakes Canada
module passed all its mocked tests while every live call failed
(2026-09-24). A module is covered by its own scripts/smoke_test_<module>*.py
or by a step in scripts/smoke_test_modules.py.
"""

from __future__ import annotations

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


# Sub-APIs where every tool, not only one, needs its own live step.
STATCAN_TOOL_LEVEL_SUB_APIS = ("wds", "sdmx", "rdaas")


def test_statcan_wds_sdmx_and_rdaas_tools_each_have_a_live_step():
    stepped = {step.tool for step in _load_smoke_table().STEPS}
    missing: list[str] = []
    for sub in STATCAN_TOOL_LEVEL_SUB_APIS:
        source = (MODULES / "statcan" / sub / "tools.py").read_text(encoding="utf-8")
        tools = re.findall(r"@tool\s+async def (\w+)\(", source)
        assert tools, f"no tools found in statcan/{sub}/tools.py"
        # A step is a row in smoke_test_modules.py or, for a sub-API with its own
        # script (wds), a block of smoke_test_statcan_<sub>*.py headed by the
        # tool's name (those scripts call the client functions behind each tool).
        own = "\n".join(
            path.read_text(encoding="utf-8")
            for path in SCRIPTS.glob(f"smoke_test_statcan_{sub}*.py")
        )
        missing += [
            name for name in tools if name not in stepped and not re.search(rf"\b{name}\b", own)
        ]
    assert not missing, f"StatCan tools without a live smoke step: {missing}"
