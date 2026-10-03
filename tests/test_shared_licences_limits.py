"""Licence lookup, truncation notes, byte budgets and argument checks shared by every module."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest

from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.licences import (
    OGL_CANADA,
    PER_RECORD_LICENCE,
    SOURCE_LICENCES,
    STATCAN_LICENCE,
    licence_for,
)
from maplestats_mcp.shared.limits import fit_to_budget, join_limits, truncation_note
from maplestats_mcp.shared.validation import check_choice, check_range

MODULES = Path(__file__).resolve().parents[1] / "src" / "maplestats_mcp" / "modules"
NO_UPSTREAM = {"example", "maplestats-planner", "maplestats-reproduce", "maplestats-workbook"}


def _literal_sources() -> set[str]:
    """Every source name a module states as a string literal or a SOURCE constant."""
    found: set[str] = set()
    for path in MODULES.rglob("*.py"):
        if "__tests__" in path.parts or "_example" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.keyword)
                and node.arg == "source"
                or isinstance(node, ast.Assign)
                and any(
                    isinstance(t, ast.Name)
                    and t.id in {"SOURCE", "PROVENANCE_SOURCE", "SOURCE_NAME"}
                    for t in node.targets
                )
            ):
                value = node.value
            else:
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                found.add(value.value)
    return found - NO_UPSTREAM


def test_every_named_source_has_a_licence():
    missing = sorted(s for s in _literal_sources() if licence_for(s, "") is None)
    assert not missing, f"add these sources to shared/licences.py SOURCE_LICENCES: {missing}"


def test_licence_lookup_rules():
    assert licence_for("statcan-wds", "") == STATCAN_LICENCE
    assert licence_for("anything", "https://www150.statcan.gc.ca/x") == STATCAN_LICENCE
    assert licence_for("ckan-on", "") == PER_RECORD_LICENCE
    assert licence_for("arcgis-halifax", "") == PER_RECORD_LICENCE
    assert licence_for("transit:stm", "") == SOURCE_LICENCES["transit"]
    assert licence_for("cgc", "") == OGL_CANADA
    assert licence_for("unknown-source", "https://example.org") is None


def test_make_provenance_prefers_the_module_licence():
    auto = make_provenance(source="boc", url="https://x", cached=False, schema_name="s")
    assert "Bank of Canada" in (auto.licence or "")
    own = make_provenance(
        source="boc", url="https://x", cached=False, schema_name="s", licence="Own terms."
    )
    assert own.licence == "Own terms."


def test_truncation_note_and_join():
    assert truncation_note(returned=5, total=5) is None
    note = truncation_note(
        returned=50, total=1234, unit="rows", order="latest", how_to_get_more="raise limit"
    )
    assert note == "Returned the most recent 50 of 1,234 rows; raise limit."
    assert truncation_note(returned=10, total=None) == "Returned the first 10 of more rows."
    assert join_limits("a.", None, "", "b") == "a. b."
    assert join_limits(None, " ") is None


def test_fit_to_budget_keeps_a_prefix_and_at_least_one_item():
    rows = [{"text": "x" * 100} for _ in range(50)]
    kept = fit_to_budget(rows, max_bytes=1_000)
    assert 0 < len(kept) < 50
    assert kept == rows[: len(kept)]
    assert len(fit_to_budget([{"text": "x" * 5_000}], max_bytes=10)) == 1
    assert fit_to_budget([], max_bytes=10) == []


def test_check_range_and_choice():
    check_range(date(2020, 1, 1), date(2020, 1, 1))
    check_range(None, 2020)
    with pytest.raises(InvalidInput, match="year_from \\(2021\\) is after year_to \\(2020\\)"):
        check_range(2021, 2020, "year_from", "year_to")
    assert check_choice(" class i ", ["Class I", "Class II"], "recall_class") == "Class I"
    assert check_choice(None, ["a"], "x") is None
    with pytest.raises(InvalidInput, match="Valid values: Class I, Class II"):
        check_choice("Class IV", ["Class I", "Class II"], "recall_class")
