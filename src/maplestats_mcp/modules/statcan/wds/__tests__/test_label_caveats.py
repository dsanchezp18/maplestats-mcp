"""Caveats on StatCan labels that agents misread, from live WDS payloads.

Cube payloads are trimmed copies of live getCubeMetadata answers read on
2026-11-09 (member ids, parentMemberId links and names as sent), and the
values quoted in comments are the live observations of the same day:

- 36-10-0104: "Chained (2017) dollars percentage change" under "Seasonally
  adjusted at annual rates" is quarter over quarter (2026-Q2 GDP 0.8 =
  2,524,127 / 2,503,604 - 1), and "Less: imports of goods and services" has a
  positive contribution (+0.364 annualized) while imports rose.
- 36-10-0711: current-dollar "All industries" is ".." for 2024 and 2025 in
  every province; 36-10-0222 has current-price GDP at market prices for both.
- 14-10-0287: the title says "seasonally adjusted and trend-cycle" for its
  Unadjusted series too.
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
            {
                "memberId": mid,
                "parentMemberId": None,
                "memberNameEn": text,
                "memberNameFr": text,
                "terminated": 0,
            }
            | extra.get(mid, {})
            for mid, text in members
        ],
    }


def _cube(title: str, dims: list[dict], frequency: int) -> dict:
    return {
        "cubeTitleEn": title,
        "cubeTitleFr": title,
        "frequencyCode": frequency,
        "archiveStatusCode": "2",
        "dimension": dims,
        "footnote": [],
    }


GDP_SAAR = _cube(
    "Gross domestic product, expenditure-based, Canada, quarterly",
    [
        _dim(1, "Geography", [(1, "Canada")]),
        _dim(
            2,
            "Prices",
            [
                (1, "Chained (2017) dollars"),
                (2, "Current prices"),
                (7, "Chained (2017) dollars percentage change"),
                (3, "Contributions to percent change"),
                (4, "Contributions to percent change, annualized"),
            ],
        ),
        _dim(
            3,
            "Seasonal adjustment",
            [(1, "Seasonally adjusted at annual rates"), (2, "Unadjusted")],
        ),
        _dim(
            4,
            "Estimates",
            [
                (23, "Exports of goods and services"),
                (26, "Less: imports of goods and services"),
                (27, "Imports of goods"),
                (28, "Imports of services"),
                (30, "Gross domestic product at market prices"),
            ],
            {
                26: {"memberNameFr": "Moins : importations de biens et services"},
                27: {"parentMemberId": 26, "memberNameFr": "Importations de biens"},
                28: {"parentMemberId": 26},
            },
        ),
    ],
    frequency=9,
)
PROVINCIAL_GDP = _cube(
    "Gross domestic product (GDP) at basic prices, by industry, provinces and territories",
    [
        _dim(1, "Geography", [(9, "Alberta"), (10, "British Columbia")]),
        _dim(2, "Prices", [(1, "Current dollars"), (2, "Chained (2017) dollars")]),
        _dim(
            3,
            "North American Industry Classification System (NAICS)",
            [(1, "All industries"), (2, "Goods-producing industries")],
        ),
    ],
    frequency=12,
)
LFS_MONTHLY = _cube(
    "Labour force characteristics, monthly, seasonally adjusted and trend-cycle",
    [
        _dim(1, "Geography", [(1, "Canada")]),
        _dim(2, "Labour force characteristics", [(3, "Employment")]),
        _dim(3, "Gender", [(1, "Total - Gender")]),
        _dim(4, "Age group", [(1, "15 years and over")]),
        _dim(5, "Statistics", [(1, "Estimate")]),
        _dim(6, "Data type", [(1, "Seasonally adjusted"), (3, "Trend-cycle"), (2, "Unadjusted")]),
    ],
    frequency=6,
)
CODES = {
    "uom": [{"memberUomCode": 81, "memberUomEn": "Dollars", "memberUomFr": "Dollars"}],
    "scalar": [],
    "frequency": [],
}
CHAINED = frozenset({auto_notes.CHAINED_RULE})


def _notes(cube: dict, coordinate: str, keys=frozenset(), lang: str = "en") -> list[str]:
    return auto_notes.metadata_notes(cube, None, coordinate, lang, keys)[0]


def _plain(text: str) -> str:
    return text.replace(" ", " ").replace(" ", " ")


def test_percentage_change_at_annual_rates_is_period_over_period():
    # v1594571783: 2026-Q2 0.8 = 2,524,127 / 2,503,604 - 1, not annualized.
    notes = _notes(GDP_SAAR, "1.7.1.30", keys=CHAINED)
    assert notes[-1] == (
        "'Chained (2017) dollars percentage change' is the change from the previous quarter, "
        "not an annualized rate: 'at annual rates' describes the levels only. An annualized "
        "rate compounds it: ((1 + x/100)^4 - 1) x 100; say which one you report."
    )
    # Contributions (GDP 0.82) are quarterly too; the annualized member (3.316) is named.
    assert _notes(GDP_SAAR, "1.3.1.30") == [
        (
            "'Contributions to percent change' is the change from the previous quarter, not "
            "an annualized rate: 'at annual rates' describes the levels only. The table's "
            "'Contributions to percent change, annualized' member is the annualized figure."
        )
    ]
    # French notes get no-break spaces from pick(); compare on plain ones.
    assert _plain(_notes(GDP_SAAR, "1.3.1.30", lang="fr")[0]).startswith(
        "« Contributions to percent change » est la variation par rapport au trimestre"
    )
    # Annualized, unadjusted or a level: no note.
    assert _notes(GDP_SAAR, "1.4.1.30") == []
    assert not any("previous quarter" in n for n in _notes(GDP_SAAR, "1.7.2.30", keys=CHAINED))
    assert _notes(GDP_SAAR, "1.2.1.30") == []


def test_contributions_on_a_less_line_are_published_positive():
    # v79448576 was +0.364 for 2026-Q2 while imports rose; GDP's 3.316 needs it subtracted.
    assert _notes(GDP_SAAR, "1.4.1.26") == [
        (
            "Contribution on a 'Less:' line ('Less: imports of goods and services'): StatCan "
            "publishes it with the sign of the change in imports of goods and services, so a "
            "positive value means imports of goods and services rose, which lowered growth. "
            "Subtract it when adding the components up to the total."
        )
    ]
    # Its children (imports of goods +0.143, services -0.053) follow the same sign.
    assert any("'Less: imports of goods and services'" in n for n in _notes(GDP_SAAR, "1.3.1.27"))
    french = _notes(GDP_SAAR, "1.4.1.26", lang="fr")
    assert _plain(french[0]).startswith(
        "Contribution d'une ligne « Moins : » (« Moins : importations de biens et services »)"
    )
    # Exports, and the import level, get no sign note.
    assert not any("Less:" in n for n in _notes(GDP_SAAR, "1.4.1.23"))
    assert not any("Less:" in n for n in _notes(GDP_SAAR, "1.1.1.26", keys=CHAINED))


def test_unadjusted_member_wins_over_the_table_title():
    # v2064890: "Canada;Employment;Total - Gender;15 years and over;Estimate;Unadjusted".
    assert _notes(LFS_MONTHLY, "1.3.1.1.1.2") == [
        (
            "Unadjusted series (Data type: 'Unadjusted'), although the table title says "
            "seasonally adjusted; the table also has 'Seasonally adjusted', usually the "
            "headline for change from one period to the next."
        )
    ]
    title = str(LFS_MONTHLY["cubeTitleEn"])
    assert auto_notes.seasonally_adjusted([title, "Employment", "Unadjusted"]) is False
    assert _notes(LFS_MONTHLY, "1.3.1.1.1.3") == [
        (
            "Trend-cycle series: a smoothed version of the seasonally adjusted series, "
            "revised as new periods arrive; the headline is 'Seasonally adjusted'."
        )
    ]
    assert _notes(LFS_MONTHLY, "1.3.1.1.1.1") == []


def test_trailing_not_available_periods_are_named():
    flags = [
        (date(2022, 1, 1), 0, 0),
        (date(2023, 1, 1), 0, 0),
        (date(2024, 1, 1), 1, 0),
        (date(2025, 1, 1), 1, 0),
    ]
    assert auto_notes.trailing_unavailable(flags) == [date(2024, 1, 1), date(2025, 1, 1)]
    assert auto_notes.flag_notes(flags, 12, "en") == [
        (
            "Not available (..) for 2024, 2025: StatCan has not published a value for these "
            "latest periods in this series (status 'not available for a specific reference "
            "period'). Do not estimate one; say it is not published, and look for another "
            "series or table that has it."
        )
    ]
    # Rows before a series starts are ".." too: no note for those.
    assert auto_notes.trailing_unavailable([(date(2019, 1, 1), 1, 0), *flags[:2]]) == []


def _provincial(coordinate: str, statuses: list[int]) -> VectorSeries:
    return VectorSeries(
        product_id=36100711,
        coordinate=coordinate,
        vector_id=1793287722,
        observations=[
            ObservationRow(
                ref_period=date(2022 + i, 1, 1),
                value=None if s == 1 else 400000.0,
                decimals=1,
                scalar_factor_code=6,
                symbol_code=0,
                status_code=s,
                security_level_code=0,
            )
            for i, s in enumerate(statuses)
        ],
    )


def test_unavailable_current_dollar_gdp_points_to_the_expenditure_table():
    # v1793287722, Alberta current dollars, All industries: 2024 and 2025 are "..".
    ctx = context._context_for(
        _provincial("9.1.1", [0, 0, 1, 1]), {"memberUomCode": 81}, PROVINCIAL_GDP, CODES, "en"
    )
    assert any(n.startswith("Not available (..) for 2024, 2025") for n in ctx.notes)
    assert ctx.notes[-1].startswith(
        "StatCan publishes current-price GDP for these years in table 36-10-0222-01"
    )
    assert "market prices, not basic prices" in ctx.notes[-1]
    # Another industry, or a series with every year published, gets no pointer.
    other = context._context_for(
        _provincial("9.1.2", [0, 0, 1, 1]), None, PROVINCIAL_GDP, CODES, "en"
    )
    assert not any("36-10-0222" in n for n in other.notes)
    full = context._context_for(
        _provincial("9.1.1", [0, 0, 0, 0]), None, PROVINCIAL_GDP, CODES, "en"
    )
    assert not any("36-10-0222" in n or "Not available" in n for n in full.notes)
    french = context._context_for(
        _provincial("9.1.1", [0, 0, 1, 1]), None, PROVINCIAL_GDP, CODES, "fr"
    )
    assert _plain(french.notes[-1]).startswith(
        "Statistique Canada publie le PIB en dollars courants"
    )
