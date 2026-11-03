"""check_answer: only problems come back, each with a fix.

The WDS and Valet reads are replaced by fakes holding values read live on
2026-11-03: Canada's unemployment rate (v2062815, 14-10-0287) 6.4 for 2026-08
and 6.5 for 2026-09, Alberta's member 10 in the same table, LFS employment
21,104.8 thousand, 11-10-0090 (Canada only, Canadian Income Survey), the PEI
2024 MBM rate flagged E in 11-10-0135, 12-10-0011 exports unadjusted, the CPI
(v41690973, 18-10-0004) for each month of 2024 and 2026-09, and quarterly GDP
(v62305783, 36-10-0104) 3,437,720 million for 2026-Q2.
"""

from __future__ import annotations

import re
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
from maplestats_mcp.shared.errors import InvalidInput, UpstreamUnavailable


def _members(*names: tuple[int, str]) -> list[dict]:
    return [{"memberId": m, "memberNameEn": n, "memberNameFr": n} for m, n in names]


LFS = {
    "productId": "14100287",
    "cubeTitleEn": "Labour force characteristics by province, monthly, seasonally adjusted",
    "frequencyCode": 6,
    "surveyCode": ["3701"],
    "dimension": [
        {
            "dimensionPositionId": 1,
            "dimensionNameEn": "Geography",
            "member": _members((1, "Canada"), (7, "Ontario"), (10, "Alberta")),
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
CPI = {
    "productId": "18100004",
    "frequencyCode": 6,
    "surveyCode": ["2301"],
    "dimension": [
        {
            "dimensionPositionId": 1,
            "dimensionNameEn": "Geography",
            "member": _members((2, "Canada")),
        },
        {
            "dimensionPositionId": 2,
            "dimensionNameEn": "Products and product groups",
            "member": _members((2, "All-items")),
        },
    ],
    "footnote": [],
}
GDP = {
    "productId": "36100104",
    "frequencyCode": 9,
    "surveyCode": ["1901"],
    "dimension": [
        {
            "dimensionPositionId": 1,
            "dimensionNameEn": "Geography",
            "member": _members((1, "Canada")),
        }
    ],
    "footnote": [],
}
CUBES = {
    14100287: LFS,
    11100090: DISABILITY,
    12100011: TRADE,
    14100223: LFS,
    18100004: CPI,
    36100104: GDP,
}
CPI_2024 = (158.3, 158.8, 159.8, 160.6, 161.5, 161.4, 162.1, 161.8, 161.1, 161.8, 161.8, 161.2)

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
    41690973: (
        18100004,
        "2.2",
        0,
        "2002=100",
        [(date(2024, m + 1, 1), v, 0, 0) for m, v in enumerate(CPI_2024)]
        + [(date(2026, 9, 1), 170.0, 0, 0)],
    ),
    # A monthly series with one month flagged E (status 7) in 2024.
    12: (
        14100287,
        "1.7.0.0.0.1",
        0,
        "Percent",
        [(date(2024, m, 1), 6.0, 7 if m == 3 else 0, 0) for m in range(1, 13)],
    ),
    62305783: (36100104, "1", 6, "Dollars", [(date(2026, 4, 1), 3437720.0, 0, 0)]),
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
    # 11-10-0090 lacks Alberta for every question, but only disability poverty
    # is known to be published nowhere else: low income is looked for in other tables.
    problems, other = await _check(
        "What is the low income rate in Alberta?",
        {"value": 13.0, "period": "2024", "product_id": "11-10-0090", "coordinate": "1"},
    )
    assert problems == [(0, "geography")]
    assert "has no Alberta member" in other.problems[0].problem
    assert "wds_search_cubes" in other.problems[0].fix
    assert "custom tabulation" not in other.problems[0].fix
    _, french = await _check(
        "Taux de pauvreté des personnes handicapées en Alberta ?",
        {"value": 13.0, "period": "2024", "product_id": "11-10-0090", "coordinate": "1"},
        lang="fr",
    )
    assert "totalisation personnalisée" in french.problems[0].fix


async def test_known_unpublished_without_a_pumf_gap_points_to_the_codebook(monkeypatch):
    monkeypatch.setattr(client, "_KNOWN_UNPUBLISHED", {11100090: re.compile("low income")})
    problems, result = await _check(
        "What is the low income rate in Alberta?",
        {"value": 13.0, "period": "2024", "product_id": "11-10-0090", "coordinate": "1"},
    )
    assert problems == [(0, "not_published")]
    assert "statcan_pumf_get_codebook" in result.problems[0].fix


async def test_a_place_another_table_has_is_not_called_unpublished():
    # 14-10-0287 has no Toronto: 14-10-0459/0460 do (rule lfs-subprovincial-moving-averages).
    problems, result = await _check(
        "Unemployment rate in Toronto?",
        {"value": 6.5, "period": "2026-09", "vector_id": 2062815},
    )
    assert problems == [(0, "geography")]
    problem = result.problems[0]
    assert "Table 14-10-0287 has no Toronto member." in problem.problem
    query = "wds_search_cubes 'Labour force characteristics census metropolitan area'"
    assert query in problem.fix
    assert "14-10-0459" in problem.fix and "lfs-subprovincial-moving-averages" in problem.fix
    for words in ("custom tabulation", "RTRA", "not published and label"):
        assert words not in problem.fix


async def test_canadian_in_the_question_does_not_add_canada():
    problems, result = await _check(
        "What are the average weekly earnings of Canadian workers in Alberta?",
        {"value": 6.5, "period": "2026-09", "vector_id": 2062815},
    )
    assert problems == [(0, "geography")]
    assert "(Alberta)" in result.problems[0].fix
    problems, _ = await _check(
        "What is the unemployment rate for Canadians?",
        {"value": 6.5, "period": "2026-09", "vector_id": 2062815},
    )
    assert problems == []


async def test_each_figure_is_judged_against_its_own_place():
    question = "Unemployment rate in Ontario and employment in Toronto?"
    problems, result = await _check(
        question,
        {"value": 6.5, "period": "2026-09", "vector_id": 2062815, "geography": "Canada"},
        {"value": 6.5, "period": "2026-09", "vector_id": 2062815, "geography": "Toronto"},
        {"value": 6.5, "period": "2026-09", "vector_id": 2062815},
    )
    assert problems == [(1, "geography"), (2, "geography")]
    labelled, unlabelled = result.problems
    assert "labelled Toronto" in labelled.problem and "no Toronto member" in labelled.problem
    assert "Toronto" in unlabelled.problem and "Ontario" in unlabelled.problem
    assert "coordinate 7.7.0.0.0.1 (Ontario)" in unlabelled.fix
    assert "wds_search_cubes" in unlabelled.fix


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
    # Another source (CMHC rent) is not a problem to fix: a note says it was not checked.
    problems, result = await _check("Rent in Toronto?", {"value": 2500, "unit": "dollars"})
    assert problems == []
    assert result.checked == 0
    assert result.notes == [
        "Figure 0 not checked: check_answer covers StatCan and Bank of Canada figures."
    ]
    problems, _ = await _check("x", {"value": "abc", "vector_id": 2062815})
    assert problems == [(0, "value")]
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


async def test_whole_numbers_are_precise_to_the_unit():
    # 170 means 169.5 to 170.5: trailing zeros of a whole number are not rounding.
    def wrong(value, published, unit=None):
        figure = CitedFigure(value=value, unit=unit)
        return client._value_problems(0, figure, published, 1, None, "2024", None, "en")

    assert wrong(170, 174.9) and wrong(1000, 1400) and wrong(20000, 24000)
    assert not wrong(170, 169.8) and not wrong(170, 170.0)
    assert wrong("170.0", 169.8) and not wrong("170.0", 170.04)
    assert not wrong("6.50", 6.5) and wrong("6.50", 6.54)
    # A scale word does not widen the match beyond 5% of the value.
    assert wrong(2, 2.4e6, "million") and not wrong(2, 2.05e6, "million")
    assert not wrong(2.06, 2_056_453e6, "trillion dollars")
    problems, _ = await _check(
        "How many people are employed in Canada?",
        {"value": 20000, "unit": "thousands of persons", "period": "2026-09", "vector_id": 2062811},
    )
    assert problems == [(0, "value")]
    problems, _ = await _check(
        "How many people are employed in Canada?",
        {"value": "21,104.8", "unit": "thousands", "period": "2026-09", "vector_id": 2062811},
    )
    assert problems == []


def test_number_text_and_scale_words_by_language():
    assert client._number("2,06", "fr") == (2.06, 0.01)
    assert client._number("2,056", "en") == (2056.0, 1.0)
    assert client._number("1 234,5", "fr") == (1234.5, 0.1)
    assert client._number(6.5, "en") == (6.5, 0.1)
    with pytest.raises(ValueError):
        client._number("n/a", "en")
    assert client._scale_word("billion dollars", "en") == 1e9
    assert client._scale_word("billions de dollars", "fr") == 1e12
    assert client._scale_word("milliards de dollars", "fr") == 1e9
    assert client._scale_word("milliers de milliards", "fr") == 1e12
    assert client._scale_word("billions de milliards", "fr") == 1e21
    assert client._scale_word("M$", "fr") == 1e6
    assert client._scale_word("$M", "en") == 1e6
    assert client._scale_word("m", "en") is None
    assert client._scale_word("km", "en") is None


async def test_french_billion_is_ten_to_the_twelfth():
    problems, _ = await _check(
        "PIB du Canada au deuxième trimestre 2026 ?",
        {
            "value": "3,44",
            "unit": "billions de dollars",
            "period": "2026-Q2",
            "vector_id": 62305783,
        },
        lang="fr",
    )
    assert problems == []
    problems, _ = await _check(
        "Canada's GDP in 2026-Q2?",
        {"value": 3.44, "unit": "trillion dollars", "period": "2026-Q2", "vector_id": 62305783},
    )
    assert problems == []


async def test_a_year_cited_for_a_monthly_series_is_the_year():
    problems, result = await _check(
        "CPI in 2024?", {"value": 999, "period": "2024", "vector_id": 41690973}
    )
    assert problems == [(0, "value")]
    assert result.problems[0].problem == (
        "The 2024 average of the 12 published values (158.3 to 162.1) is 160.9, not 999."
    )
    assert "average of 12 values" in result.problems[0].fix
    problems, _ = await _check(
        "CPI in 2024?", {"value": 160.9, "period": "2024", "vector_id": 41690973}
    )
    assert problems == []
    problems, result = await _check(
        "CPI in 2024?", {"value": 161.2, "period": "2024", "vector_id": 41690973}
    )
    assert problems == [(0, "period")]
    assert result.problems[0].problem == (
        "161.2 is the value for 2024-12; the 2024 average is 160.9."
    )
    # The newer-period check works at the cited granularity: 2026 is newer than 2024.
    problems, result = await _check(
        "What is Canada's CPI?", {"value": 160.9, "period": "2024", "vector_id": 41690973}
    )
    assert problems == [(0, "newer_period")]
    assert "2026-09 (170)" in result.problems[0].problem


async def test_flags_are_read_for_every_month_of_a_cited_year():
    problems, result = await _check(
        "Unemployment rate in 2024", {"value": 6.0, "period": "2024", "vector_id": 12}
    )
    assert problems == [(0, "quality_flag")]
    assert "2024-03" in result.problems[0].problem


async def test_one_bad_vector_does_not_lose_the_others(monkeypatch):
    real = context.series_info_raw

    async def infos(ids):
        # WDS answers HTTP 500 for the whole batch when one id does not exist.
        if 999999999999 in ids:
            raise UpstreamUnavailable("getSeriesInfoFromVector failed with HTTP 500.")
        return await real(ids)

    monkeypatch.setattr(context, "series_info_raw", infos)
    problems, result = await _check(
        "What is Canada's unemployment rate?",
        {"value": 6.5, "period": "2026-09", "vector_id": 2062815},
        {"value": 1, "period": "2026-09", "vector_id": 999999999999},
    )
    assert problems == [(1, "series")]
    assert result.checked == 1
    with pytest.raises(UpstreamUnavailable):
        await _check("x", {"value": 1, "vector_id": 999999999999})
