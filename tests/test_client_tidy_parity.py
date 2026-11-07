"""The Python client's row rule matches reproduce_workbook's, on the recorded responses.

clients/python/src/maplestats/tidy.py ports workbook.rows_and_left_out line
for line (docs/clients.md); the R and Julia clients port the same rule. This
fails when the two Python copies give different rows for a recorded result.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from maplestats_mcp.modules.reproduce import workbook

CLIENT = Path(__file__).parents[1] / "clients" / "python"
FIXTURES = CLIENT / "tests" / "fixtures"


def _load_tidy():
    spec = importlib.util.spec_from_file_location(
        "maplestats_client_tidy", CLIENT / "src" / "maplestats" / "tidy.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(name: str):
    text = (FIXTURES / f"{name}.sse").read_text(encoding="utf-8")
    data = next(line[5:] for line in text.splitlines() if line.startswith("data:"))
    result = json.loads(data)["result"]
    return result.get("structuredContent")


@pytest.mark.parametrize("name", ["boc", "wds", "plan_query", "reproduce", "search_tools"])
def test_client_rows_match_the_workbook_rows(name: str) -> None:
    tidy = _load_tidy()
    payload = _payload(name)
    assert tidy.rows_and_left_out(payload) == workbook.rows_and_left_out(payload)
    assert tidy.provenance(payload) == workbook.payload_provenance(payload)


def test_client_names_match_the_workbook_names() -> None:
    tidy = _load_tidy()
    names = ["context.citation", "values.FXUSDCAD", "refPer", "Année", "a.b", "a_b"]
    assert tidy.clean_names(names) == workbook.clean_names(names)
