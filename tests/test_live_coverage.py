"""Every source module must have a live smoke test.

Mocked unit tests share the assumptions of the code they test, so they
cannot catch a wrong assumption about a live API; the Earthquakes Canada
module passed all its mocked tests while every live call failed
(2026-09-24). A module is covered by its own scripts/smoke_test_<module>*.py
or by a step in scripts/smoke_test_modules.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "src" / "maple_data_mcp" / "modules"
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
