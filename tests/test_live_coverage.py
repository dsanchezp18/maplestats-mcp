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


def _covered_by_table() -> frozenset[str]:
    spec = importlib.util.spec_from_file_location(
        "smoke_modules", SCRIPTS / "smoke_test_modules.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their module through sys.modules while executing.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.COVERED_MODULES


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


# StatCan is a dozen services on different hosts (WDS, SDMX, RDaaS, the census
# APIs, ...), so a smoke step for one of them must not count for the rest. A
# sub-API is covered by scripts/smoke_test_statcan_<sub>.py or by a
# smoke_test_modules.py step whose module is "statcan/<sub>". Gaps below are
# known; an entry must be removed as soon as it is covered (the stale-entry
# test fails otherwise).
STATCAN_SUB_APIS_WITHOUT_LIVE_STEPS: dict[str, str] = {
    "wds": "only wds_search_cubes is exercised (scripts/smoke_test.py); 12 tools have no step",
    "census_profile_2016": "step removed 2026-10-01 while www12.statcan.gc.ca blocks clients",
    "census_tables": "step removed 2026-10-01 while www12.statcan.gc.ca blocks clients",
}

# Sub-APIs where every tool, not only one, needs its own live step.
STATCAN_TOOL_LEVEL_SUB_APIS = ("sdmx", "rdaas")


def _statcan_sub_apis() -> list[str]:
    root = MODULES / "statcan"
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "client.py").exists())


def _statcan_sub_api_covered(sub: str, table: frozenset[str]) -> bool:
    return f"statcan/{sub}" in table or (SCRIPTS / f"smoke_test_statcan_{sub}.py").exists()


def test_every_statcan_sub_api_has_its_own_live_smoke_test():
    table = _covered_by_table()
    missing = [
        sub
        for sub in _statcan_sub_apis()
        if not _statcan_sub_api_covered(sub, table)
        and sub not in STATCAN_SUB_APIS_WITHOUT_LIVE_STEPS
    ]
    assert not missing, (
        f"No live smoke test for StatCan sub-API(s): {missing}. Add a smoke_test_modules.py "
        "step with module 'statcan/<sub>' or scripts/smoke_test_statcan_<sub>.py."
    )


def test_statcan_live_gap_list_has_no_stale_entries():
    table = _covered_by_table()
    stale = [
        sub
        for sub in STATCAN_SUB_APIS_WITHOUT_LIVE_STEPS
        if _statcan_sub_api_covered(sub, table) or sub not in _statcan_sub_apis()
    ]
    assert not stale, f"Remove from STATCAN_SUB_APIS_WITHOUT_LIVE_STEPS: {stale}"


def test_statcan_sdmx_and_rdaas_tools_each_have_a_live_step():
    spec = importlib.util.spec_from_file_location(
        "smoke_modules_steps", SCRIPTS / "smoke_test_modules.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    stepped = {step.tool for step in module.STEPS}
    missing: list[str] = []
    for sub in STATCAN_TOOL_LEVEL_SUB_APIS:
        source = (MODULES / "statcan" / sub / "tools.py").read_text(encoding="utf-8")
        tools = re.findall(r"@tool\s+async def (\w+)\(", source)
        assert tools, f"no tools found in statcan/{sub}/tools.py"
        missing += [name for name in tools if name not in stepped]
    assert not missing, f"StatCan tools without a live smoke step: {missing}"
