"""The arithmetic of the calc_ tools, without a network.

Values are the ones read live on 2026-11-07 and checked by hand: Alberta
employment 2,608.5 and Canada's 21,009.9 thousand (14-10-0287, 2025-09), the
CPI's 2015 and 2025 annual averages 126.5667 and 164.1833 (18-10-0004), and the
policy rate's 2024 moves (Valet V39079).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pytest

from maplestats_mcp.modules.calc import compute
from maplestats_mcp.modules.calc.compute import Loaded
from maplestats_mcp.modules.calc.schemas import InputSeries
from maplestats_mcp.shared.errors import InvalidInput, NotFound


def _series(
    sid: str,
    points: list[tuple[date, float | None]],
    *,
    ppy: int | None = 12,
    unit: str | None = "Persons",
    scale: float = 1.0,
    rate: bool = False,
    geography: str | None = None,
) -> Loaded:
    info = InputSeries(
        source="statcan",
        id=sid,
        geography=geography,
        citation=f"Statistics Canada. Vector {sid}.",
        url="https://www150.statcan.gc.ca/",
        unit=unit,
        scale_multiplier=scale,
        frequency="Monthly",
        periods_per_year=ppy,
    )
    return Loaded(info=info, points=points, rate=rate)


def _monthly(year: int, values: Sequence[float | None]) -> list[tuple[date, float | None]]:
    return [(date(year, m + 1, 1), v) for m, v in enumerate(values)]


# Ratio --------------------------------------------------------------------------


def test_ratio_aligns_by_period_and_uses_full_units():
    alberta = _series(
        "v2064512",
        [(date(2025, 8, 1), 2_600_000.0), (date(2025, 9, 1), 2_608_500.0)],
        unit="Persons in thousands",
        scale=1000,
    )
    # Canada is missing 2025-08: the August Alberta value must not pair with anything.
    canada = _series(
        "v2062811", [(date(2025, 9, 1), 21_009_900.0)], unit="Persons in thousands", scale=1000
    )
    points, ppy, formula, notes = compute.ratio(
        alberta,
        canada,
        multiplier=100,
        frequency=None,
        aggregation="average",
        first=None,
        last=None,
        latest_n=3,
        lang="en",
    )
    assert ppy == 12
    assert [p.period for p in points] == ["2025-09"]
    assert points[0].value == pytest.approx(12.415575514)
    assert "v2064512 × 1,000" in formula and "× 100" in formula
    assert any("scale factor" in n for n in notes)
    assert compute.ratio_unit(alberta, canada, 100, "en") == "percent"


def test_ratio_window_keeps_missing_points_as_null():
    a = _series("v1", _monthly(2024, [1.0, 2.0, 3.0]))
    b = _series("v2", _monthly(2024, [2.0, None, 0.0]))
    points, *_ = compute.ratio(
        a,
        b,
        multiplier=1,
        frequency=None,
        aggregation="average",
        first=date(2024, 1, 1),
        last=date(2024, 3, 31),
        latest_n=1,
        lang="en",
    )
    assert [p.value for p in points] == [0.5, None, None]


def test_ratio_refuses_mixed_frequencies_unless_named():
    monthly = _series("v1", _monthly(2024, [1.0] * 12), unit="Dollars")
    annual = _series("v2", [(date(2024, 1, 1), 24.0)], ppy=1, unit="Dollars")
    with pytest.raises(InvalidInput, match="do not share a frequency"):
        compute.ratio(
            monthly,
            annual,
            multiplier=1,
            frequency=None,
            aggregation="average",
            first=None,
            last=None,
            latest_n=1,
            lang="en",
        )
    points, ppy, formula, _ = compute.ratio(
        monthly,
        annual,
        multiplier=12,
        frequency="annual",
        aggregation="average",
        first=None,
        last=None,
        latest_n=1,
        lang="en",
    )
    assert ppy == 1
    assert points[0].period == "2024" and points[0].value == pytest.approx(0.5)
    assert "average" in formula


def test_ratio_refuses_a_frequency_finer_than_a_series():
    annual = _series("v2", [(date(2024, 1, 1), 24.0)], ppy=1)
    monthly = _series("v1", _monthly(2024, [1.0] * 12))
    with pytest.raises(InvalidInput, match="cannot be converted"):
        compute.check_frequencies([monthly, annual], "monthly", "en")


@pytest.mark.parametrize(
    ("a", "b", "match"),
    [
        ("2002=100", "Dollars", "an index"),
        ("Dollars", "Chained (2017) dollars", "current and"),
        ("2017 constant dollars", "2012 constant dollars", "current and"),
    ],
)
def test_ratio_refuses_units_that_do_not_divide(a, b, match):
    x = _series("v1", _monthly(2024, [1.0]), unit=a)
    y = _series("v2", _monthly(2024, [1.0]), unit=b)
    with pytest.raises(InvalidInput, match=match):
        compute.unit_clash(x, y, "en")


def test_ratio_unit_of_different_units_and_french_refusal():
    dollars = _series("v1", _monthly(2024, [1.0]), unit="Dollars")
    persons = _series("v2", _monthly(2024, [1.0]), unit="Persons")
    assert compute.ratio_unit(dollars, persons, 1, "en") == "Dollars per Persons"
    assert compute.ratio_unit(dollars, persons, 1, "fr") == "Dollars par Persons"
    index = _series("v3", _monthly(2024, [1.0]), unit="2002=100")
    with pytest.raises(InvalidInput, match="indice"):
        compute.unit_clash(index, dollars, "fr")


def test_ratio_with_nothing_in_common_is_not_found():
    a = _series("v1", _monthly(2023, [1.0]))
    b = _series("v2", _monthly(2024, [1.0]))
    with pytest.raises(NotFound):
        compute.ratio(
            a,
            b,
            multiplier=1,
            frequency=None,
            aggregation="average",
            first=None,
            last=None,
            latest_n=1,
            lang="en",
        )


# Ranking ------------------------------------------------------------------------------


def _rate(geo: str, values: Sequence[float | None]) -> Loaded:
    return _series(geo, _monthly(2025, values), unit="Percent", rate=True, geography=geo)


def test_rank_shares_ranks_on_ties_and_lists_missing_last():
    places = [
        _rate("Ontario", [7.9]),
        _rate("Alberta", [7.7]),
        _rate("New Brunswick", [7.9]),
        _rate("Newfoundland and Labrador", [10.5]),
        _rate("Yukon", [None]),
    ]
    period, entries, _, notes = compute.rank(
        places,
        period="2025-01",
        descending=True,
        frequency=None,
        aggregation="average",
        lang="en",
    )
    assert period == "2025-01"
    assert [(e.rank, e.label) for e in entries] == [
        (1, "Newfoundland and Labrador"),
        (2, "Ontario"),
        (2, "New Brunswick"),
        (4, "Alberta"),
        (None, "Yukon"),
    ]
    assert entries[0].series.values_used[0].value == 10.5
    assert any("Yukon" in n for n in notes)


def test_rank_default_period_is_latest_most_series_have():
    places = [
        _rate("A", [5.0, 6.0, 7.0]),
        _rate("B", [4.0, 3.0, None]),
        _rate("C", [1.0, 2.0, None]),
    ]
    period, entries, _, notes = compute.rank(
        places, period=None, descending=False, frequency=None, aggregation="average", lang="en"
    )
    assert period == "2025-02"
    assert [e.label for e in entries] == ["C", "B", "A"]
    assert notes


def test_rank_refuses_mixed_units_and_wrong_period_frequency():
    with pytest.raises(InvalidInput, match="not in one unit"):
        compute.check_units([_rate("A", [1.0]), _series("B", _monthly(2025, [1.0]))], "en")
    with pytest.raises(InvalidInput, match="annual"):
        compute.rank(
            [_rate("A", [1.0]), _rate("B", [2.0])],
            period="2025",
            descending=True,
            frequency=None,
            aggregation="average",
            lang="en",
        )


def test_rank_annual_averages():
    places = [_rate("A", [1.0] * 12), _rate("B", [2.0] * 6 + [4.0] * 6)]
    period, entries, ppy, _ = compute.rank(
        places, period="2025", descending=True, frequency="annual", aggregation="average", lang="en"
    )
    assert (period, ppy) == ("2025", 1)
    assert [(e.label, e.value) for e in entries] == [("B", 3.0), ("A", 1.0)]


# Compound annual growth ------------------------------------------------------------------


def test_cagr_of_annual_averages_matches_hand_computation():
    cpi = _series(
        "v41690973",
        _monthly(2015, [126.5666666667] * 12) + _monthly(2025, [164.1833333333] * 12),
        unit="2002=100",
    )
    first, last, a, b, years, ppy, notes = compute.cagr(
        cpi, start="2015", end="2025", frequency="annual", aggregation="average", lang="en"
    )
    assert (first, last, years, ppy) == (date(2015, 1, 1), date(2025, 1, 1), 10.0, 1)
    assert compute.growth_rate(a, b, years) == pytest.approx(2.6363, abs=1e-4)
    assert not notes
    assert "years apart" in compute.cagr_formula(cpi, "2015", "2025", years, ppy, "en")


def test_cagr_counts_quarters_and_days():
    quarterly = _series("v1", [(date(2020, 1, 1), 100.0), (date(2021, 7, 1), 121.0)], ppy=4)
    *_, years, _, _ = compute.cagr(
        quarterly, start="2020-Q1", end="2021-Q3", frequency=None, aggregation="average", lang="en"
    )
    assert years == 1.5
    daily = _series("FX", [(date(2020, 1, 2), 1.0), (date(2022, 1, 2), 1.21)], ppy=None)
    *_, years, _, notes = compute.cagr(
        daily,
        start="2020-01-02",
        end="2022-01-02",
        frequency=None,
        aggregation="average",
        lang="en",
    )
    assert years == pytest.approx(731 / 365.25)
    assert not notes


def test_cagr_refuses_rates_mismatched_periods_missing_and_non_positive():
    rate = _rate("A", [5.0])
    with pytest.raises(InvalidInput, match="compound growth of a rate"):
        compute.cagr(
            rate, start="2025-01", end="2025-01", frequency=None, aggregation="average", lang="en"
        )
    monthly = _series("v1", _monthly(2024, [1.0] * 12))
    with pytest.raises(InvalidInput, match="frequency='annual'"):
        compute.cagr(
            monthly, start="2024", end="2025", frequency=None, aggregation="average", lang="en"
        )
    with pytest.raises(NotFound):
        compute.cagr(
            monthly,
            start="2024-01",
            end="2026-01",
            frequency=None,
            aggregation="average",
            lang="en",
        )
    with pytest.raises(InvalidInput, match="after start"):
        compute.cagr(
            monthly,
            start="2024-05",
            end="2024-02",
            frequency=None,
            aggregation="average",
            lang="en",
        )
    negative = _series("v2", _monthly(2024, [-1.0, 2.0]))
    with pytest.raises(InvalidInput, match="positive"):
        compute.cagr(
            negative,
            start="2024-01",
            end="2024-02",
            frequency=None,
            aggregation="average",
            lang="en",
        )


def test_cagr_under_a_year_says_it_extrapolates():
    monthly = _series("v1", _monthly(2024, [100.0, 101.0]))
    *_, years, _, notes = compute.cagr(
        monthly, start="2024-01", end="2024-02", frequency=None, aggregation="average", lang="en"
    )
    assert years == pytest.approx(1 / 12)
    assert notes and "extrapolates" in notes[0]


# Count of changes -----------------------------------------------------------------------


def _policy_rate() -> Loaded:
    days = [
        (date(2023, 12, 29), 5.0),
        (date(2024, 1, 2), 5.0),
        (date(2024, 6, 5), 5.0),
        (date(2024, 6, 6), 4.75),
        (date(2024, 7, 24), None),
        (date(2024, 7, 25), 4.5),
        (date(2024, 9, 5), 4.25),
        (date(2024, 10, 24), 3.75),
        (date(2024, 12, 12), 3.25),
        (date(2025, 1, 30), 3.0),
    ]
    return _series("V39079", days, ppy=None, unit="Percent", rate=True)


def test_count_changes_compares_with_baseline_and_skips_missing():
    baseline, events, skipped, notes = compute.count_changes(
        _policy_rate(), first=date(2024, 1, 1), last=date(2024, 12, 31), threshold=0, lang="en"
    )
    assert baseline is not None and baseline.period == "2023-12-29"
    assert [e.period for e in events] == [
        "2024-06-06",
        "2024-07-25",
        "2024-09-05",
        "2024-10-24",
        "2024-12-12",
    ]
    assert [e.change for e in events] == [-0.25, -0.25, -0.25, -0.5, -0.5]
    assert skipped == 1 and any("skipped" in n for n in notes)


def test_count_changes_threshold_and_first_day_move():
    # A move on the window's first day counts: it differs from the baseline.
    _, events, _, _ = compute.count_changes(
        _policy_rate(), first=date(2024, 6, 6), last=date(2024, 12, 31), threshold=0.25, lang="en"
    )
    assert [e.period for e in events] == ["2024-10-24", "2024-12-12"]
    _, events, _, _ = compute.count_changes(
        _policy_rate(), first=date(2024, 6, 6), last=date(2024, 6, 6), threshold=0, lang="en"
    )
    assert [e.period for e in events] == ["2024-06-06"]


def test_count_changes_without_baseline_says_so():
    monthly = _series("v1", _monthly(2024, [1.0, 1.0, 2.0]))
    baseline, events, _, notes = compute.count_changes(
        monthly, first=date(2024, 1, 1), last=date(2024, 12, 31), threshold=0, lang="fr"
    )
    assert baseline is None
    assert [e.period for e in events] == ["2024-03"]
    assert "Aucune valeur" in notes[0]


def test_window_parses_periods_and_rejects_bad_ones():
    assert compute.window("2024-Q2", "2024-Q3", "en") == (date(2024, 4, 1), date(2024, 9, 30))
    with pytest.raises(InvalidInput, match="not a period"):
        compute.window("June 2024", None, "en")
    with pytest.raises(InvalidInput, match="after end"):
        compute.window("2025", "2024", "en")
