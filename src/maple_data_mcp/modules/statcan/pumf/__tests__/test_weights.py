"""Main-weight selection, on the variables that fooled name matching (2026-09-24)."""

from __future__ import annotations

from maple_data_mcp.modules.statcan.pumf import client
from maple_data_mcp.modules.statcan.pumf.schemas import PumfVariable


def _v(name: str, label: str, width: int | None) -> PumfVariable:
    return PumfVariable(name=name, label=label, width=width, values=[])


def test_look_alikes_are_not_weights():
    variables = [
        _v("WTQ_05", "Working time - Works at night", 1),
        _v("WTCHANGE", "Employer changes schedule at short notice", 1),
        _v("DOHWT", "Height and weight - Inclusion Flag - (F)", 1),
        _v("CSWCWT", "Official PUMF survey weight", 12),
    ]
    assert client.weight_names(variables) == ["CSWCWT"]
    assert client.main_weight(variables) == "CSWCWT"


def test_replicates_follow_the_main_weight():
    variables = [
        _v("WT1", "replicate pumf weight", 16),
        _v("WEIGHT", "individuals weighting factor", 16),
        _v("WT2", "replicate pumf weight", 16),
    ]
    assert client.weight_names(variables)[0] == "WEIGHT"
    assert client.main_weight(variables) == "WEIGHT"
