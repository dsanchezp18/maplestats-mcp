"""shared/sdmx_query.py: SQL over a slice of an SDMX dataset, with query_checks' checks.

No network: the slices are built here. The hierarchy rules were checked live on
2026-11-20 (eurostat_query_dataset and oecd_query_dataset refused a sum of the EU27
with Germany, of the G7 with the United States, of a country with its NUTS regions, of
a total sex or age band with its parts, and of seasonally adjusted with unadjusted
values, and answered the same queries once narrowed).
"""

from __future__ import annotations

from datetime import date

import pytest

from maplestats_mcp.modules.statcan.wds import query_checks
from maplestats_mcp.shared import sdmx_query
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.sdmx_query import SliceDimension, SliceObservation, SliceSeries


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2024", date(2024, 1, 1)),
        ("2024-Q3", date(2024, 7, 1)),
        ("2024-S2", date(2024, 7, 1)),
        ("2024-05", date(2024, 5, 1)),
        ("2024-M05", date(2024, 5, 1)),
        ("2024-05-15", date(2024, 5, 15)),
        ("2024-W02", date(2024, 1, 8)),
        ("2024-A1", date(2024, 1, 1)),
        ("1994/1998", None),
    ],
)
def test_period_start(text, expected):
    assert sdmx_query.period_start(text) == expected


def _ancestors(dim: SliceDimension, code: str) -> set[str]:
    places = {c: i for i, c in enumerate(dim.labels, start=1)}
    names = {i: c for c, i in places.items()}
    tree = sdmx_query.hierarchy([dim])[1]
    return {names[i] for i in query_checks._ancestors(tree, places[code])}


def _dim(dim_id: str, codes: str, role: str | None = None, **parents: str) -> SliceDimension:
    return SliceDimension(
        id=dim_id, name=dim_id, labels={c: c for c in codes.split()}, parents=parents, role=role
    )


def test_eurostat_geography_regions_and_aggregates():
    geo = _dim("geo", "EU27_2020 EA21 EA20 EU28 DE DE1 DE11 DEZZ FR SE UK US", "geo")
    assert _ancestors(geo, "DE11") == {"DE1", "DE", "EA21", "EA20", "EU27_2020", "EU28"}
    assert _ancestors(geo, "DEZZ") >= {"DE"}
    assert _ancestors(geo, "SE") == {"EU27_2020", "EU28"}
    assert _ancestors(geo, "EA20") == {"EA21", "EU27_2020", "EU28"}
    assert _ancestors(geo, "UK") == {"EU28"}
    assert _ancestors(geo, "US") == set()


def test_oecd_area_aggregates_in_iso3():
    # The OECD's area codelist gives members and aggregates no parent (live 2026-11-20).
    area = _dim("REF_AREA", "OECD G7 EU27_2020 EA20 CAN DEU MEX CHN", "geo")
    assert _ancestors(area, "CAN") == {"OECD", "G7"}
    assert _ancestors(area, "DEU") == {"OECD", "G7", "EU27_2020", "EA20"}
    assert _ancestors(area, "MEX") == {"OECD"}
    assert _ancestors(area, "CHN") == set()


def test_age_bands_and_totals():
    eurostat = _dim("age", "TOTAL Y15-64 Y15-24 Y25-54 Y_GE65 Y_LT15 Y20")
    assert _ancestors(eurostat, "Y15-24") == {"Y15-64", "TOTAL"}
    assert _ancestors(eurostat, "Y20") == {"Y15-24", "Y15-64", "TOTAL"}
    assert _ancestors(eurostat, "Y_GE65") == {"TOTAL"}
    oecd = _dim("AGE", "_T Y15T64 Y15T24 Y_GE15 Y_GE25")
    assert _ancestors(oecd, "Y15T24") == {"Y15T64", "Y_GE15", "_T"}
    assert _ancestors(oecd, "Y_GE25") == {"Y_GE15", "_T"}


def test_activity_sections_divisions_and_ranges():
    nace = _dim("nace_r2", "TOTAL B-E C C10-C12 C10 F M_N M T")
    assert _ancestors(nace, "C10") == {"C10-C12", "C", "B-E", "TOTAL"}
    assert _ancestors(nace, "M") == {"M_N", "TOTAL"}
    # T is a NACE section (households as employers), not a total.
    assert _ancestors(nace, "T") == {"TOTAL"}
    isic = _dim("ACTIVITY", "_T BTE C F", C="_T")
    assert _ancestors(isic, "C") == {"BTE", "_T"}


def test_sex_total_is_t_only_for_sex():
    assert _ancestors(_dim("sex", "T M F"), "F") == {"T"}
    assert _ancestors(_dim("unit", "T PC"), "PC") == set()


def test_dimension_columns_never_shadow_obs():
    dims = [_dim("unit", "X"), _dim("geo", "X"), _dim("REF_AREA", "X"), _dim("ADJUSTMENT", "X")]
    assert sdmx_query.dimension_columns(dims) == {
        "unit": "unit_code",
        "geo": "geo",
        "REF_AREA": "ref_area",
        "ADJUSTMENT": "adjustment_code",
    }


def _slice() -> tuple[list[SliceDimension], list[SliceSeries]]:
    dims = [
        SliceDimension("freq", "Frequency", {"A": "Annual"}, role="freq"),
        SliceDimension(
            "unit", "Unit", {"MIO_EUR": "Million euro", "PC": "Percentage"}, role="unit"
        ),
        SliceDimension(
            "geo",
            "Geo",
            {"EU27_2020": "European Union", "DE": "Germany", "FR": "France"},
            role="geo",
        ),
    ]

    def series(unit: str, geo: str, values: list[float | None]) -> SliceSeries:
        return SliceSeries(
            codes=("A", unit, geo),
            observations=[
                SliceObservation(str(2022 + i), v, "provisional" if v is None else None)
                for i, v in enumerate(values)
            ],
        )

    return dims, [
        series("MIO_EUR", "EU27_2020", [100.0, 110.0]),
        series("MIO_EUR", "DE", [30.0, 33.0]),
        series("MIO_EUR", "FR", [20.0, None]),
        series("PC", "DE", [1.5, 1.6]),
    ]


async def _run(sql: str):
    dims, series = _slice()
    return await sdmx_query.run(
        sql=sql, dataset="test", dataset_title="Test", dims=dims, series=series, lang="en"
    )


async def test_a_query_runs_over_obs_with_code_and_label_columns():
    outcome = await _run(
        "SELECT geo, geo_label, unit_code, value FROM obs WHERE period = '2022' "
        "AND unit_code = 'MIO_EUR' ORDER BY value DESC"
    )
    assert outcome.rows == [
        ["EU27_2020", "European Union", "MIO_EUR", 100.0],
        ["DE", "Germany", "MIO_EUR", 30.0],
        ["FR", "France", "MIO_EUR", 20.0],
    ]
    assert outcome.input_rows == 8
    assert outcome.dimension_columns["unit"] == "unit_code"


async def test_a_total_summed_with_its_parts_is_refused():
    with pytest.raises(InvalidInput, match="total_with_parts.*'Annual; Million euro; European"):
        await _run("SELECT period, sum(value) FROM obs WHERE unit_code = 'MIO_EUR' GROUP BY period")


async def test_mixed_units_are_refused_and_name_series_id():
    with pytest.raises(InvalidInput, match=r"mixed_units.*\(or series_id\)"):
        await _run("SELECT geo, avg(value) FROM obs WHERE geo = 'DE' GROUP BY geo")


async def test_a_filtered_aggregate_is_judged_by_its_query_not_refused():
    # The diagnostic cannot see FILTER (WHERE ...), so it does not judge such a query;
    # sum(value) FILTER (WHERE geo = 'DE') beside the EU was refused until 2026-11-20.
    outcome = await _run(
        "SELECT period, sum(value) FILTER (WHERE geo = 'DE' AND unit_code = 'MIO_EUR') "
        "FROM obs GROUP BY period ORDER BY period"
    )
    assert outcome.rows == [["2022", 30.0], ["2023", 33.0]]


async def test_parts_alone_are_summed_with_a_nulls_warning():
    outcome = await _run(
        "SELECT period, sum(value) FROM obs WHERE unit_code = 'MIO_EUR' "
        "AND geo IN ('DE', 'FR') GROUP BY period ORDER BY period"
    )
    assert outcome.rows == [["2022", 50.0], ["2023", 33.0]]
    assert any(w.startswith("nulls: 1 of 4") for w in outcome.warnings)


async def test_a_label_no_row_holds_is_refused_with_the_closest():
    with pytest.raises(InvalidInput, match="did you mean 'Germany'"):
        await _run("SELECT * FROM obs WHERE geo_label = 'Germny'")


def test_codes_are_checked_before_the_download():
    dims, _ = _slice()
    columns = sdmx_query.dimension_columns(dims)
    sdmx_query.check_codes("SELECT * FROM obs WHERE geo = 'DE'", dims, columns, "en")
    with pytest.raises(InvalidInput, match="geo = 'XX' matches no row"):
        sdmx_query.check_codes("SELECT * FROM obs WHERE geo = 'XX'", dims, columns, "en")


@pytest.mark.parametrize("sql", ["", "DROP TABLE obs", "SELECT 1; SELECT 2", "SELEC * FROM obs"])
def test_only_one_read_only_select_is_accepted(sql):
    with pytest.raises(InvalidInput):
        sdmx_query.check_sql(sql)
