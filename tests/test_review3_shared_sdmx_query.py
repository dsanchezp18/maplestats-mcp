"""Review fix in shared/sdmx_query.py: Eurostat's s_adj code CA is calendar adjusted."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maplestats_mcp.modules.eurostat import client as eurostat_client
from maplestats_mcp.shared import sdmx_query
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.sdmx_query import SliceDimension, SliceObservation, SliceSeries

FIXTURES = (
    Path(__file__).resolve().parents[1] / "src/maplestats_mcp/modules/eurostat/__tests__/fixtures"
)

# Eurostat's s_adj codes: NSA is unadjusted, CA is calendar adjusted and not seasonally
# adjusted, SCA is both. The adjustment is read from the code, so the labels here do
# not matter to the result; the fixture's own labels are used below.
ADJUSTMENT = SliceDimension(
    "s_adj",
    "Seasonal adjustment",
    {
        "NSA": "Unadjusted data (i.e. neither seasonally adjusted nor calendar adjusted data)",
        "CA": "Calendar adjusted data, not seasonally adjusted data",
        "SCA": "Seasonally and calendar adjusted data",
    },
    role="adjustment",
)


def _series() -> list[SliceSeries]:
    return [
        SliceSeries(
            codes=(code,),
            observations=[SliceObservation("2024", value), SliceObservation("2025", value + 1)],
        )
        for code, value in (("NSA", 100.0), ("CA", 101.0), ("SCA", 102.0))
    ]


async def _run(sql: str):
    return await sdmx_query.run(
        sql=sql,
        dataset="namq_10_gdp",
        dataset_title="GDP",
        dims=[ADJUSTMENT],
        series=_series(),
        lang="en",
    )


async def test_calendar_adjusted_is_its_own_adjustment():
    outcome = await _run("SELECT s_adj, adjustment FROM obs GROUP BY ALL ORDER BY 1")
    assert outcome.rows == [
        ["CA", "calendar adjusted"],
        ["NSA", "unadjusted"],
        ["SCA", "seasonally adjusted"],
    ]


async def test_averaging_calendar_adjusted_with_unadjusted_values_is_refused():
    # Both used to read "unadjusted", so the mix went through unflagged.
    with pytest.raises(InvalidInput, match="mixed_adjustment") as refused:
        await _run(
            "SELECT period, avg(value) FROM obs WHERE s_adj IN ('NSA', 'CA') GROUP BY period"
        )
    # The refusal lists the calendar adjustment among the kinds it refuses to mix.
    assert "calendar adjusted" in str(refused.value)
    outcome = await _run(
        "SELECT period, avg(value) FROM obs WHERE s_adj = 'CA' GROUP BY period ORDER BY period"
    )
    assert outcome.rows == [["2024", 101.0], ["2025", 102.0]]


async def test_the_mixed_adjustment_refusal_names_calendar_adjusted_in_french_too():
    with pytest.raises(InvalidInput, match="mixed_adjustment") as refused:
        await sdmx_query.run(
            sql="SELECT period, avg(value) FROM obs WHERE s_adj IN ('NSA', 'CA') GROUP BY period",
            dataset="namq_10_gdp",
            dataset_title="PIB",
            dims=[ADJUSTMENT],
            series=_series(),
            lang="fr",
        )
    message = str(refused.value).replace(" ", " ")
    assert "corrigées des effets de calendrier" in message


def _fixture_labels() -> dict[str, dict[str, str]]:
    """Eurostat's s_adj codes with their English and French names, from the structure
    answer the Eurostat tests use (ESTAT:S_ADJ 1.12, namq_10_gdp)."""
    structure = eurostat_client._parse_structure(
        (FIXTURES / "structure_namq_10_gdp.xml").read_bytes()
    )
    s_adj = next(d for d in structure["dimensions"] if d["id"] == "s_adj")
    return dict(s_adj["codes"])


def _adjustment_of(label: str) -> str | None:
    # A code the map does not know, so that only the label can say what it is.
    dim = SliceDimension("s_adj", "Adjustment", {"ZZ": label}, role="adjustment")
    return sdmx_query._adjustment([dim], ("ZZ",), "title")


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_the_fixtures_ca_label_reads_calendar_adjusted_without_the_code_map(lang):
    # CA's label says "not seasonally adjusted" (French: "non désaisonnalisées"), which
    # the label reader took for unadjusted.
    labels = _fixture_labels()
    assert _adjustment_of(labels["CA"][lang]) == "calendar adjusted"


@pytest.mark.parametrize("lang", ["en", "fr"])
@pytest.mark.parametrize("code", ["NSA", "SA", "SCA"])
def test_the_other_s_adj_labels_are_not_taken_for_calendar_adjusted(code, lang):
    # The negations in these labels ("neither ... nor calendar adjusted", "not calendar
    # adjusted") and SCA's "seasonally and calendar adjusted" must not match.
    assert _adjustment_of(_fixture_labels()[code][lang]) != "calendar adjusted"


@pytest.mark.parametrize(
    "label",
    [
        "Calendar adjusted data, not seasonally adjusted data",
        "Working day adjusted, not seasonally adjusted",
        "Working-day adjusted data",
        "Données corrigées des effets de calendrier, données non désaisonnalisées",
        "Données corrigées des jours ouvrables",
    ],
)
def test_a_label_that_says_calendar_or_working_day_adjusted_alone_is_calendar_adjusted(label):
    assert _adjustment_of(label) == "calendar adjusted"


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Seasonally adjusted data, not calendar adjusted data", "seasonally adjusted"),
        ("Trend-cycle, calendar adjusted", "trend-cycle"),
        ("Unadjusted data", "unadjusted"),
        ("Données non corrigées des effets de calendrier, non désaisonnalisées", "unadjusted"),
    ],
)
def test_labels_that_say_something_else_keep_their_reading(label, expected):
    assert _adjustment_of(label) == expected


@pytest.mark.parametrize(
    "label", ["Neither seasonally nor calendar adjusted", "Not calendar adjusted"]
)
def test_a_negated_calendar_label_is_not_calendar_adjusted(label):
    assert _adjustment_of(label) != "calendar adjusted"


def test_oecd_k_is_left_as_it_was_because_its_label_is_a_component_not_an_adjustment():
    # structure_eo.json and structure_house_prices.json (CL_ADJUSTMENT 1.0): K is
    # "Calendar component", a part of a decomposition like "Irregular component", not a
    # calendar adjusted series. That is not clear enough to map it to either reading.
    oecd = FIXTURES.parents[2] / "oecd/__tests__/fixtures"
    for name in ("structure_eo.json", "structure_house_prices.json"):
        data = json.loads((oecd / name).read_text(encoding="utf-8"))["data"]
        codelist = next(c for c in data["codelists"] if c["id"] == "CL_ADJUSTMENT")
        assert {c["id"]: c["name"] for c in codelist["codes"]}["K"] == "Calendar component"
    assert sdmx_query._ADJUSTMENT_CODES["K"] == "unadjusted"
