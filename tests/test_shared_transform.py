"""shared/transform.py on hand-computed fixtures.

Each expected value below was worked out by hand from the fixture, not
produced by the code under test: monthly and quarterly levels, a gap in
the data (a missing row and a missing value), and the percentage rule.
"""

from __future__ import annotations

from datetime import date

import pytest

from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.transform import (
    aggregate,
    extra_months,
    infer_periods_per_year,
    is_rate_unit,
    parse_period,
    period_label,
    source_periods_needed,
    transform_series,
)


def _monthly(values: dict[str, float | None]) -> list[tuple[date, float | None]]:
    return [(date.fromisoformat(f"{month}-01"), value) for month, value in values.items()]


# 2024-02 has no row at all and 2024-08 has a row without a value.
MONTHLY = _monthly(
    {
        "2024-01": 100.0,
        "2024-03": 102.0,
        "2024-04": 103.0,
        "2024-05": 104.0,
        "2024-06": 105.0,
        "2024-07": 106.0,
        "2024-08": None,
        "2024-09": 108.0,
        "2024-10": 109.0,
        "2024-11": 110.0,
        "2024-12": 111.0,
        "2025-01": 110.0,
        "2025-02": 111.0,
        "2025-03": 112.2,
    }
)


def _values(result) -> dict[str, float | None]:
    return {p.period: p.value for p in result.points}


def test_yoy_uses_the_same_month_a_year_earlier_not_twelve_rows_back():
    result = transform_series(MONTHLY, source_ppy=12, transform="yoy_pct_change")
    values = _values(result)
    # 2025-01 against 2024-01: 100 * (110 / 100 - 1) = 10.
    assert values["2025-01"] == pytest.approx(10.0)
    # 2024-02 has no row: 2025-02 has no year-ago level. Counting 12 rows back
    # would have compared it with 2024-03 instead.
    assert values["2025-02"] is None
    # 2025-03 against 2024-03: 100 * (112.2 / 102 - 1) = 10.
    assert values["2025-03"] == pytest.approx(10.0)
    assert values["2024-12"] is None  # nothing a year before it
    assert result.formula == (
        "Computed by MapleStats: yoy_pct_change = 100 * (x_t / x_{t-12} - 1), t in months "
        "(the same period a year earlier, matched by date)"
    )
    assert result.unit == "percent"
    assert result.periods_per_year == 12 and result.source_periods_per_year == 12


def test_missing_values_propagate_as_none_never_zero():
    values = _values(transform_series(MONTHLY, source_ppy=12, transform="diff"))
    assert values["2024-07"] == pytest.approx(1.0)  # 106 - 105
    assert values["2024-08"] is None  # its own value is missing
    assert values["2024-09"] is None  # its previous month is missing
    assert values["2024-03"] is None  # the previous month (2024-02) has no row
    assert values["2024-10"] == pytest.approx(1.0)
    assert 0 not in [v for v in values.values() if v is None]


def test_pct_change_and_yoy_diff_by_hand():
    values = _values(transform_series(MONTHLY, source_ppy=12, transform="pct_change"))
    assert values["2025-03"] == pytest.approx(100 * (112.2 / 111 - 1))  # 1.081081...
    values = _values(transform_series(MONTHLY, source_ppy=12, transform="yoy_diff"))
    assert values["2025-03"] == pytest.approx(10.2)  # 112.2 - 102


QUARTERLY = [
    (date(2024, 1, 1), 100.0),
    (date(2024, 4, 1), 101.0),
    (date(2024, 7, 1), 102.01),
    (date(2024, 10, 1), None),
    (date(2025, 1, 1), 105.0),
]


def test_quarterly_annualized_and_yoy():
    values = _values(transform_series(QUARTERLY, source_ppy=4, transform="annualized_pct_change"))
    # (101 / 100)^4 = 1.04060401
    assert values["2024-Q2"] == pytest.approx(4.060401)
    assert values["2024-Q3"] == pytest.approx(4.060401)  # 102.01 / 101 = 1.01
    assert values["2024-Q4"] is None and values["2025-Q1"] is None
    values = _values(transform_series(QUARTERLY, source_ppy=4, transform="yoy_pct_change"))
    assert values["2025-Q1"] == pytest.approx(5.0)  # 105 / 100: four quarters back


def test_index_to_a_whole_year():
    points = _monthly({f"2020-{m:02d}": 90.0 + 2 * m for m in range(1, 13)})  # mean 103
    points.append((date(2021, 1, 1), 113.3))
    result = transform_series(points, source_ppy=12, transform="index", index_base="2020")
    values = _values(result)
    assert values["2021-01"] == pytest.approx(110.0)  # 100 * 113.3 / 103
    assert result.unit == "index, 2020=100"
    with pytest.raises(InvalidInput):  # 2019 is not in the data
        transform_series(points, source_ppy=12, transform="index", index_base="2019")
    with pytest.raises(InvalidInput):
        transform_series(points, source_ppy=12, transform="index")


def test_monthly_to_quarterly_needs_every_month():
    points = _monthly(
        {"2024-01": 1.0, "2024-02": 2.0, "2024-03": 3.0, "2024-04": 4.0, "2024-05": 5.0}
    )
    levels, incomplete = aggregate(points, 12, 4, "average")
    assert levels == [(date(2024, 1, 1), 2.0), (date(2024, 4, 1), None)]
    assert incomplete == {date(2024, 4, 1)}
    assert aggregate(points, 12, 4, "sum")[0][0] == (date(2024, 1, 1), 6.0)
    assert aggregate(points, 12, 4, "end_of_period")[0][0] == (date(2024, 1, 1), 3.0)
    # A missing value inside the quarter leaves it missing too.
    gap = _monthly({"2024-01": 1.0, "2024-02": None, "2024-03": 3.0})
    assert aggregate(gap, 12, 4, "average")[0] == [(date(2024, 1, 1), None)]
    result = transform_series(points, source_ppy=12, frequency="quarterly", transform="level")
    assert [p.level for p in result.points] == [2.0, None]
    assert "2024-Q2" in result.notes[0]
    with pytest.raises(InvalidInput):
        aggregate(points, 4, 12, "average")


def test_daily_to_monthly_drops_a_month_the_window_only_partly_covers():
    days = [(date(2026, 9, d), float(d)) for d in (1, 2, 3, 29, 30)]
    days += [(date(2026, 10, d), 1.0) for d in (1, 2, 5)]
    levels, incomplete = aggregate(days, None, 12, "average")
    assert levels[0] == (date(2026, 9, 1), pytest.approx(13.0))  # (1+2+3+29+30)/5
    assert levels[1] == (date(2026, 10, 1), None)  # data stop on Oct 5
    assert incomplete == {date(2026, 10, 1)}


def test_percent_change_of_a_rate_is_a_point_change():
    rates = _monthly({"2026-07": 6.4, "2026-08": 6.4, "2026-09": 6.5})
    result = transform_series(
        rates, source_ppy=12, transform="pct_change", rate_unit=True, units="Percent"
    )
    assert result.requested_transform == "pct_change"
    assert result.transform == "diff"
    assert result.unit == "percentage points"
    assert _values(result)["2026-09"] == pytest.approx(0.1)
    assert "percentage points" in result.notes[0]
    yoy = transform_series(rates, source_ppy=12, transform="yoy_pct_change", rate_unit=True)
    assert yoy.transform == "yoy_diff"
    french = transform_series(
        rates, source_ppy=12, transform="pct_change", rate_unit=True, lang="fr"
    )
    assert french.unit == "points de pourcentage"
    assert french.formula.startswith("Calculé par MapleStats")


def test_daily_series_need_a_frequency_for_yoy():
    days = [(date(2026, 9, d), 1.0) for d in range(1, 10)]
    with pytest.raises(InvalidInput, match="frequency"):
        transform_series(days, source_ppy=None, transform="yoy_pct_change")
    # A daily diff is against the previous observation.
    values = _values(
        transform_series(
            [(date(2026, 9, 4), 1.0), (date(2026, 9, 8), 1.5)], source_ppy=None, transform="diff"
        )
    )
    assert values == {"2026-09-04": None, "2026-09-08": 0.5}


def test_window_and_latest_n():
    result = transform_series(
        MONTHLY,
        source_ppy=12,
        transform="diff",
        window_start=date(2024, 10, 15),
        window_end=date(2025, 1, 31),
    )
    assert [p.period for p in result.points] == ["2024-10", "2024-11", "2024-12", "2025-01"]
    latest = transform_series(MONTHLY, source_ppy=12, transform="diff", latest_n=2)
    assert [p.period for p in latest.points] == ["2025-02", "2025-03"]


def test_division_by_zero_is_missing():
    values = _values(
        transform_series(
            _monthly({"2024-01": 0.0, "2024-02": 5.0}), source_ppy=12, transform="pct_change"
        )
    )
    assert values["2024-02"] is None


def test_history_needed():
    assert source_periods_needed(3, "yoy_pct_change", 12, 12) == 15
    assert source_periods_needed(3, "level", 12, 1) == 47  # 3 years + 11 months of slack
    assert source_periods_needed(4, "annualized_pct_change", 12, 4) == 17
    assert extra_months("yoy_pct_change", 12, aggregating=False) == 12
    assert extra_months("diff", 4, aggregating=True) == 6
    assert extra_months("level", None, aggregating=False) == 0


def test_periods_units_and_frequency():
    assert parse_period("2026-07") == (date(2026, 7, 1), 12)
    assert parse_period("2026-Q3") == (date(2026, 7, 1), 4)
    assert parse_period("2026-S2") == (date(2026, 7, 1), 2)
    assert parse_period("2026") == (date(2026, 1, 1), 1)
    assert parse_period("2026-07-15") == (date(2026, 7, 15), None)
    with pytest.raises(ValueError):
        parse_period("2026/07")
    assert period_label(date(2026, 7, 1), 4) == "2026-Q3"
    # getCodeSets uom descriptions and Valet units (checked live 2026-10-27).
    for unit in (
        "Percent",
        "Percentage",
        "Percentage of gross domestic product",
        "Rate",
        "Percentage point",
        "Basis points",
        "Pourcentage",
        "Average percentage",
    ):
        assert is_rate_unit(unit), unit
    for unit in (
        "2002=100",
        "Index (2002=100)",
        "Dollars",
        "Rate per 1,000 population",
        "Canadian dollars per US dollar",
        None,
        "",
    ):
        assert not is_rate_unit(unit), unit
    assert infer_periods_per_year([date(2026, m, 1) for m in range(1, 7)]) == 12
    assert infer_periods_per_year([date(2025, 1, 1), date(2025, 4, 1), date(2025, 7, 1)]) == 4
    assert infer_periods_per_year([date(2026, 9, d) for d in (1, 2, 3)]) is None
