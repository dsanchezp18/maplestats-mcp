"""check_answer: only problems come back, each with a fix.

The WDS and Valet reads are replaced by fakes holding values read live on
2026-11-03: Canada's unemployment rate (v2062815, 14-10-0287) 6.4 for 2026-08
and 6.5 for 2026-09, Alberta's member 10 in the same table, LFS employment
21,104.8 thousand, 11-10-0090 (Canada only, Canadian Income Survey), the PEI
2024 MBM rate flagged E in 11-10-0135, and 12-10-0011 exports unadjusted.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from maplestats_mcp.modules.answer_check import client
from maplestats_mcp.modules.answer_check.schemas import CitedFigure
from maplestats_mcp.modules.statcan.wds import client as wds
from maplestats_mcp.modules.statcan.wds import context
from maplestats_mcp.modules.statcan.wds.schemas import (
    ObservationRow,
    SeriesContext,
    VectorDataSet,
    VectorSeries,
)
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput


def _members(*names: tuple[int, str]) -> list[dict]:
    return [{"memberId": m, "memberNameEn": n, "memberNameFr": n} for m, n in names]


LFS = {
    "productId": "14100287",
    "frequencyCode": 6,
    "surveyCode": ["3701"],
    "dimension": [
        {
            "dimensionPositionId": 1,
            "dimensionNameEn": "Geography",
            "member": _members((1, "Canada"), (10, "Alberta")),
        },
        {
            "dimensionPositionId": 2,
            "dimensionNameEn": "Labour force characteristics",
            "member": _members((3, "Employment"), (7, "Unemployment rate")),
        },
        {
            "dimensionPositionId": 6,
            "dimensionNameEn": "Data type",
            "member": _members((1, "Seasonally adjusted"), (2, "Trend-cycle")),
        },
    ],
    "footnote": [],
}
DISABILITY = {
    "productId": "11100090",
    "frequencyCode": 12,
    "surveyCode": ["5200"],
    "dimension": [
        {
            "dimensionPositionId": 1,
            "dimensionNameEn": "Geography",
            "member": _members((1, "Canada")),
        }
    ],
    "footnote": [],
}
TRADE = {
    "productId": "12100011",
    "frequencyCode": 6,
    "surveyCode": ["2201"],
    "dimension": [
        {
            "dimensionPositionId": 1,
            "dimensionNameEn": "Geography",
            "member": _members((1, "Canada")),
        },
        {
            "dimensionPositionId": 4,
            "dimensionNameEn": "Seasonal adjustment",
            "member": _members((1, "Unadjusted"), (2, "Seasonally adjusted")),
        },
    ],
    "footnote": [],
}
CUBES = {14100287: LFS, 11100090: DISABILITY, 12100011: TRADE, 14100223: LFS}

# vector -> (product id, coordinate, scalar code, unit, [(period, value, status, security)])
SERIES = {
    2062815: (
        14100287,
        "1.7.0.0.0.1",
        0,
        "Percent",
        [(date(2026, 8, 1), 6.4, 0, 0), (date(2026, 9, 1), 6.5, 0, 0)],
    ),
    2062811: (14100287, "1.3.0.0.0.1", 3, "Persons", [(date(2026, 9, 1), 21104.8, 0, 0)]),
    1: (11100090, "1", 0, "Percent", [(date(2024, 1, 1), 13.0, 0, 0)]),
    2: (11100090, "1", 0, "Percent", [(date(2024, 1, 1), 4.7, 7, 0)]),
    3: (11100090, "1", 0, "Percent", [(date(2024, 1, 1), None, 8, 0)]),
    87008868: (12100011, "1.0.0.1", 6, "Dollars", [(date(2026, 8, 1), 73826.3, 0, 0)]),
    9: (14100223, "1", 0, "Persons", [(date(2026, 8, 1), 18368488.0, 0, 0)]),
}


def _prov():
    return make_provenance(source="statcan-wds", url="https://x", cached=False, schema_name="t")


def _rows(vector: int, start: date | None = None, end: date | None = None):
    _, _, scalar, _, points = SERIES[vector]
    return [
        ObservationRow(
            ref_period=day,
            value=value,
            decimals=1,
            scalar_factor_code=scalar,
            scale_multiplier=10**scalar,
            symbol_code=0,
            status_code=status,
            security_level_code=security,
        )
        for day, value, status, security in points
        if (start is None or day >= start) and (end is None or day <= end)
    ]


def _set(series: list[VectorSeries]) -> VectorDataSet:
    return VectorDataSet(series=series, provenance=_prov())


@pytest.fixture(autouse=True)
def _fake_sources(monkeypatch):
    async def infos(ids):
        return {
            v: {"productId": SERIES[v][0], "coordinate": SERIES[v][1], "terminated": 0}
            for v in ids
            if v in SERIES
        }

    async def cube(pid):
        return CUBES[pid], True

    async def latest(ids, n):
        return _set(
            [
                VectorSeries(
                    product_id=SERIES[v][0],
                    coordinate=SERIES[v][1],
                    vector_id=v,
                    observations=_rows(v)[-n:],
                )
                for v in ids
            ]
        )

    async def window(ids, start, end):
        lo, hi = date.fromisoformat(start), date.fromisoformat(end)
        return _set(
            [
                VectorSeries(
                    product_id=SERIES[v][0],
                    coordinate=SERIES[v][1],
                    vector_id=v,
                    observations=_rows(v, lo, hi),
                )
                for v in ids
            ]
        )

    async def describe(ids, empty, flags=None):
        return {
            v: SeriesContext(
                table_id="x",
                table_url="x",
                unit=SERIES[v][3],
                scale={0: "units", 3: "thousands", 6: "millions"}[SERIES[v][2]],
            )
            for v in ids
        }, None

    async def codes():
        return {
            "survey": [
                {"surveyCode": "5200", "surveyEn": "Canadian Income Survey", "surveyFr": "ECR"}
            ]
        }, True

    async def by_coord(pid, coordinate):
        found = next(v for v, s in SERIES.items() if str(s[0]) in str(pid).replace("-", ""))
        return SimpleNamespace(vector_id=found)

    monkeypatch.setattr(context, "series_info_raw", infos)
    monkeypatch.setattr(context, "describe_vectors", describe)
    monkeypatch.setattr(wds, "cube_metadata_raw", cube)
    monkeypatch.setattr(wds, "get_data_from_vectors_and_latest_n_periods", latest)
    monkeypatch.setattr(wds, "get_data_from_vector_by_reference_period_range", window)
    monkeypatch.setattr(wds, "_code_sets_raw", codes)
    monkeypatch.setattr(wds, "get_series_info_from_cube_pid_coord", by_coord)


async def _check(question: str, *figures: dict, summed: bool = False, lang: str = "en"):
    result = await client.check_answer(question, [CitedFigure(**f) for f in figures], summed, lang)
    return [(p.figure, p.check) for p in result.problems], result


async def test_a_correct_answer_returns_nothing():
    problems, result = await _check(
        "What is Canada's unemployment rate?",
        {"value": 6.5, "unit": "percent", "period": "2026-09", "vector_id": 2062815},
    )
    assert problems == []
    assert result.checked == 1


async def test_rounding_to_the_cited_precision_is_not_an_error():
    problems, _ = await _check(
        "What is Canada's unemployment rate?",
        {"value": 7, "period": "2026-09", "vector_id": 2062815},
    )
    assert problems == []


async def test_wrong_value_and_stale_period():
    problems, result = await _check(
        "What is Canada's unemployment rate?",
        {"value": 6.9, "period": "2026-09", "vector_id": 2062815},
    )
    assert problems == [(0, "value")]
    assert "is 6.5, not 6.9" in result.problems[0].problem
    problems, result = await _check(
        "What is Canada's unemployment rate?",
        {"value": 6.4, "period": "2026-08", "vector_id": 2062815},
    )
    assert problems == [(0, "newer_period")]
    assert result.problems[0].problem == "A newer period is published: 2026-09 (6.5)."


async def test_a_question_naming_the_year_is_not_stale():
    problems, _ = await _check(
        "What was Canada's unemployment rate in August 2026?",
        {"value": 6.4, "period": "2026-08", "vector_id": 2062815},
    )
    assert problems == []


async def test_missed_scale_factor_and_declared_scale():
    problems, result = await _check(
        "How many people are employed in Canada?",
        {"value": 21104.8, "unit": "people", "period": "2026-09", "vector_id": 2062811},
    )
    assert problems == [(0, "scale")]
    assert "21,104,800" in result.problems[0].fix
    problems, _ = await _check(
        "How many people are employed in Canada?",
        {"value": 21.1, "unit": "million people", "period": "2026-09", "vector_id": 2062811},
    )
    assert problems == []


async def test_geography_mismatch_offers_the_right_member():
    problems, result = await _check(
        "What is the unemployment rate in Alberta?",
        {"value": 6.5, "period": "2026-09", "vector_id": 2062815},
    )
    assert problems == [(0, "geography")]
    assert "coordinate 10.7.0.0.0.1 (Alberta)" in result.problems[0].fix


async def test_not_published_gives_the_access_ladder():
    problems, result = await _check(
        "What is the poverty rate for persons with disabilities in Alberta?",
        {"value": 13.0, "period": "2024", "product_id": "11-10-0090", "coordinate": "1"},
    )
    assert problems == [(0, "not_published")]
    fix = result.problems[0].fix
    assert "72M0003X" in fix and "no disability variable" in fix
    for words in ("custom tabulation", "RTRA", "RDC", "MapleStats cannot run them"):
        assert words in fix
    assert "statcan_surveys_search_rdc_holdings" in fix
    # Without a known gap, the next step is the PUMF codebook.
    _, other = await _check(
        "What is the low income rate in Alberta?",
        {"value": 13.0, "period": "2024", "product_id": "11-10-0090", "coordinate": "1"},
    )
    assert "statcan_pumf_get_codebook" in other.problems[0].fix
    _, french = await _check(
        "Taux de pauvreté des personnes handicapées en Alberta ?",
        {"value": 13.0, "period": "2024", "product_id": "11-10-0090", "coordinate": "1"},
        lang="fr",
    )
    assert "totalisation personnalisée" in french.problems[0].fix


async def test_quality_flags():
    problems, _ = await _check(
        "Poverty rate in 2024", {"value": 4.7, "period": "2024", "vector_id": 2}
    )
    assert problems == [(0, "quality_flag")]
    problems, result = await _check(
        "Poverty rate in 2024", {"value": 4.0, "period": "2024", "vector_id": 3}
    )
    assert problems == [(0, "quality_flag")]
    assert "too unreliable" in result.problems[0].problem


async def test_unadjusted_monthly_series():
    problems, result = await _check(
        "Canada's merchandise exports last month?",
        {"value": 73.8, "unit": "billion dollars", "period": "2026-08", "vector_id": 87008868},
    )
    assert problems == [(0, "seasonal_adjustment")]
    assert "1.0.0.2" in result.problems[0].fix
    problems, _ = await _check(
        "Exports, unadjusted, last month?",
        {"value": 73.8, "unit": "billion dollars", "period": "2026-08", "vector_id": 87008868},
    )
    assert problems == []


async def test_surveys_a_rule_says_not_to_compare():
    problems, result = await _check(
        "LFS vs SEPH employment",
        {"value": 21.1, "unit": "million", "period": "2026-09", "vector_id": 2062811},
        {"value": 18368488, "period": "2026-08", "vector_id": 9},
    )
    assert (None, "fitness_rule") in problems
    rule = next(p for p in result.problems if p.check == "fitness_rule")
    assert "lfs-vs-seph" in rule.fix and len(rule.problem) < 120


async def test_figure_without_source_and_bad_input():
    problems, _ = await _check("x", {"value": 1.0})
    assert problems == [(0, "series")]
    with pytest.raises(InvalidInput):
        await client.check_answer("x", [], False, "en")
    with pytest.raises(InvalidInput):
        await client.check_answer(" ", [CitedFigure(vector_id=1)], False, "en")


async def test_bank_of_canada_series(monkeypatch):
    async def observations(names, start_date=None, end_date=None, recent=None, lang="en"):
        rows = [
            SimpleNamespace(ref_date=date(2026, 10, 1), values={"FXUSDCAD": 1.4243}),
            SimpleNamespace(ref_date=date(2026, 11, 2), values={"FXUSDCAD": 1.3978}),
        ]
        if recent:
            rows = rows[-recent:]
        if start_date:
            rows = [r for r in rows if start_date <= r.ref_date.isoformat() <= str(end_date)]
        return SimpleNamespace(observations=rows)

    monkeypatch.setattr(client.boc, "get_observations", observations)
    problems, _ = await _check(
        "USD/CAD today?", {"value": 1.3978, "period": "2026-11-02", "boc_series": "FXUSDCAD"}
    )
    assert problems == []
    problems, _ = await _check(
        "USD/CAD today?", {"value": 1.30, "period": "2026-10-01", "boc_series": "FXUSDCAD"}
    )
    assert problems == [(0, "value"), (0, "newer_period")]
