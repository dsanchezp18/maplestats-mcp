"""Reading notes derived from WDS metadata (auto_notes), and their place in context.

Cube payloads are trimmed copies of live getCubeMetadata answers read on
2026-11-03: 14-10-0459 (three-month moving average), 36-10-0104 (chained
dollars, a terminated Chained (2012) member), 34-10-0292 (constant dollars
and an adjusted sibling), 12-10-0011 (a not-additive footnote), 14-10-0380
(archived, replaced by 14-10-0459) and 14-10-0287 (none of these issues).
"""

from __future__ import annotations

from datetime import date

from maplestats_mcp.modules.statcan.wds import auto_notes, context
from maplestats_mcp.modules.statcan.wds.schemas import ObservationRow, VectorSeries


def _dim(
    position: int, name: str, members: list[tuple[int, str]], extra: dict | None = None
) -> dict:
    extra = extra or {}
    return {
        "dimensionPositionId": position,
        "dimensionNameEn": name,
        "dimensionNameFr": name,
        "member": [
            {"memberId": mid, "memberNameEn": text, "memberNameFr": text, "terminated": 0}
            | extra.get(mid, {})
            for mid, text in members
        ],
    }


def _cube(title: str, dims: list[dict], frequency: int = 6, **fields) -> dict:
    return {
        "cubeTitleEn": title,
        "cubeTitleFr": title,
        "frequencyCode": frequency,
        "archiveStatusCode": "2",
        "dimension": dims,
        "footnote": [],
        **fields,
    }


def _footnote(text: str, position: int = 0, member: int = 0) -> dict:
    return {
        "footnoteId": 1,
        "footnotesEn": text,
        "footnotesFr": text,
        "link": {"footnoteId": 1, "dimensionPositionId": position, "memberId": member},
    }


LFS_CMA = _cube(
    "Labour force characteristics by census metropolitan area, three-month moving average, "
    "seasonally adjusted",
    [
        _dim(1, "Geography", [(1, "Canada"), (3, "St. John's, Newfoundland and Labrador")]),
        _dim(2, "Labour force characteristics", [(5, "Unemployment rate")]),
        _dim(3, "Statistics", [(1, "Estimate")]),
        _dim(4, "Data type", [(1, "Seasonally adjusted"), (2, "Unadjusted")]),
    ],
)
GDP = _cube(
    "Gross domestic product, expenditure-based, Canada, quarterly",
    [
        _dim(1, "Geography", [(1, "Canada")]),
        _dim(
            2,
            "Prices",
            [(1, "Chained (2017) dollars"), (2, "Current prices"), (6, "Chained (2012) dollars")],
            {6: {"terminated": 1}},
        ),
        _dim(3, "Seasonal adjustment", [(1, "Seasonally adjusted at annual rates")]),
        _dim(4, "Estimates", [(1, "Final consumption expenditure")]),
    ],
    frequency=9,
)
PERMITS = _cube(
    "Building permits, by type of structure and type of work",
    [
        _dim(1, "Geography", [(1, "Canada")]),
        _dim(
            5,
            "Seasonal adjustment, value type",
            [
                (1, "Unadjusted, current"),
                (2, "Seasonally adjusted, current"),
                (3, "Unadjusted, constant dollars"),
                (4, "Seasonally adjusted, constant dollars"),
            ],
        ),
    ],
)
TRADE = _cube(
    "International merchandise trade for all countries and by Principal Trading Partners, monthly",
    [
        _dim(1, "Geography", [(1, "Canada")]),
        _dim(2, "Seasonal adjustment", [(1, "Unadjusted"), (2, "Seasonally adjusted")]),
    ],
    footnote=[
        _footnote("This table replaces archived table 12-10-0070."),
        _footnote("Totals are not equal to the sum of their components."),
    ],
)
ARCHIVED = _cube(
    "Labour force characteristics, three-month moving average, seasonally adjusted, inactive",
    [_dim(1, "Geography", [(1, "Canada")])],
    archiveStatusCode="1",
    footnote=[_footnote("This table has been archived and replaced by table 14-10-0459-01.")],
)
CLEAN = _cube(
    "Labour force characteristics, monthly, seasonally adjusted and trend-cycle",
    [
        _dim(1, "Geography", [(1, "Canada")]),
        _dim(2, "Labour force characteristics", [(7, "Unemployment rate")]),
        _dim(6, "Data type", [(1, "Seasonally adjusted"), (2, "Trend-cycle")]),
    ],
)


def _notes(cube, coordinate, info=None, keys=frozenset(), lang="en"):
    return auto_notes.metadata_notes(cube, info, coordinate, lang, keys)


def test_a_series_without_issues_gets_no_note():
    assert _notes(CLEAN, "1.7.0.0.0.1") == ([], False)
    assert auto_notes.flag_notes([(date(2026, 9, 1), 0, 0)], 6, "en") == []


def test_moving_average_from_the_title():
    notes, _ = _notes(LFS_CMA, "3.5.1.1")
    assert notes == [
        (
            "Three-month moving average: each value averages three months, so compare it with "
            "the same months a year earlier, not with the previous month."
        )
    ]


def test_unadjusted_member_points_to_its_adjusted_sibling():
    notes, _ = _notes(LFS_CMA, "3.5.1.2")
    assert "'Seasonally adjusted', usually the headline" in notes[-1]
    # The sibling keeps the text after the comma: current with current.
    notes, overrides = _notes(PERMITS, "1.0.0.0.3")
    assert overrides
    assert notes[0].startswith("Constant dollars: inflation-adjusted")
    assert "'Seasonally adjusted, constant dollars'" in notes[1]
    # Annual tables get no seasonal note.
    annual = {**TRADE, "frequencyCode": 12}
    assert not any("Unadjusted" in n for n in _notes(annual, "1.1")[0])


def test_chained_dollars_and_the_rule_that_already_explains_them():
    notes, overrides = _notes(GDP, "1.1.1.1")
    assert overrides
    assert notes == [
        (
            "Chained (2017) dollars: real values that are not additive, so components do not "
            "sum to totals."
        )
    ]
    short, _ = _notes(GDP, "1.1.1.1", keys=frozenset({auto_notes.CHAINED_RULE}))
    assert short == ["Chained (2017) dollars: real (inflation-adjusted) values."]


def test_terminated_member_and_series():
    notes, _ = _notes(GDP, "1.6.1.1", keys=frozenset({auto_notes.CHAINED_RULE}))
    assert notes[-1] == "Series terminated: StatCan no longer updates it."
    notes, _ = _notes(CLEAN, "1.7.0.0.0.1", info={"terminated": 1})
    assert notes == ["Series terminated: StatCan no longer updates it."]


def test_not_additive_footnote_and_unadjusted_trade():
    notes, _ = _notes(TRADE, "1.1")
    assert notes[0].startswith("StatCan footnote: totals are not equal to the sum")
    assert "Seasonally adjusted" in notes[1]
    # A footnote on another member does not apply.
    other = {
        **CLEAN,
        "footnote": [
            _footnote("Totals are not equal to the sum of their components.", position=2, member=99)
        ],
    }
    assert _notes(other, "1.7.0.0.0.1")[0] == []


def test_archived_table_names_its_replacement():
    notes, _ = _notes(ARCHIVED, "1")
    assert notes[-1] == (
        "Table archived, no longer updated: StatCan replaced it with table 14-10-0459."
    )
    bare = {**ARCHIVED, "footnote": []}
    assert "look for its current replacement" in _notes(bare, "1")[0][-1]


def test_flag_notes_name_the_periods():
    flags = [
        (date(2019, 1, 1), 1, 0),
        (date(2020, 1, 1), 8, 0),
        (date(2021, 1, 1), 8, 0),
        (date(2023, 1, 1), 7, 0),
        (date(2024, 1, 1), 7, 0),
        (date(2025, 1, 1), 0, 1),
    ]
    assert auto_notes.flag_notes(flags, 12, "en") == [
        "Use with caution (E) for 2023, 2024: high sampling variability; say so when citing.",
        (
            "Too unreliable to be published (F) for 2020, 2021; suppressed for confidentiality "
            "(x) for 2025: do not report a figure for those periods."
        ),
    ]
    french = auto_notes.flag_notes(flags[:2], 12, "fr")
    assert french[0].startswith("Trop peu fiable pour être publié (F) pour 2020")
    many = [(date(2020, m, 1), 7, 0) for m in range(1, 10)]
    assert "and 3 more" in auto_notes.flag_notes(many, 6, "en")[0]
    assert auto_notes.format_period(date(2026, 4, 1), 9) == "2026-Q2"


def test_french_notes():
    notes, _ = _notes(LFS_CMA, "3.5.1.1", lang="fr")
    assert notes[0].startswith("Moyenne mobile de trois mois")


def _series(product_id: int, coordinate: str, statuses: list[int]) -> VectorSeries:
    return VectorSeries(
        product_id=product_id,
        coordinate=coordinate,
        vector_id=1,
        observations=[
            ObservationRow(
                ref_period=date(2020 + i, 1, 1),
                value=None if s == 8 else 1.0,
                decimals=1,
                scalar_factor_code=0,
                symbol_code=0,
                status_code=s,
                security_level_code=0,
            )
            for i, s in enumerate(statuses)
        ],
    )


CODES = {
    "uom": [{"memberUomCode": 81, "memberUomEn": "Dollars", "memberUomFr": "Dollars"}],
    "scalar": [],
    "frequency": [],
}


def test_chained_member_replaces_the_current_dollar_unit_note():
    # 36-10-0104's chained series carry memberUomCode 81, "Dollars".
    ctx = context._context_for(
        _series(36100104, "1.1.1.1", [0]), {"memberUomCode": 81}, GDP, CODES, "en"
    )
    assert ctx.unit == "Dollars"
    assert not any("current (nominal)" in n for n in ctx.notes)
    # 36-10-0104 has the gdp-industry-vs-expenditure rule, so the note is short.
    assert ctx.notes[0] == "Chained (2017) dollars: real (inflation-adjusted) values."


def test_context_adds_flag_notes_from_observations():
    ctx = context._context_for(_series(11100135, "1", [7, 8]), None, CLEAN, CODES, "en")
    assert ctx.notes == [
        "Use with caution (E) for 2020-01: high sampling variability; say so when citing.",
        "Too unreliable to be published (F) for 2021-01: do not report a figure for those periods.",
    ]
