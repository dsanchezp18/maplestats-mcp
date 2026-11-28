"""wds_query_table: SQL over a slice of a whole table, read from its full-table CSV.

Checked live on 2026-11-20: the LFS table 14-10-0287 (5.5 million rows) streamed and
filtered in about 16 s at a 158 MB peak; the same slice read from the file and
rebuilt from WDS by coordinate (the route when the file answers with StatCan's
captcha) gave identical rows. The file here keeps the live CSV's columns, order and
quoting, with a two-province, two-characteristic table and its real member ids.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from maplestats_mcp.modules.statcan.wds import client, table_query, tools
from maplestats_mcp.modules.statcan.wds.schemas import ObservationRow, VectorData, VectorSeries
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable
from maplestats_mcp.shared.remote_zip import RangeRefused, ZipMember

PID = 14100287
HEADER = (
    '﻿"REF_DATE","GEO","DGUID","Labour force characteristics","Data type","UOM","UOM_ID",'
    '"SCALAR_FACTOR","SCALAR_ID","VECTOR","COORDINATE","VALUE","STATUS","SYMBOL","TERMINATED",'
    '"DECIMALS"'
)
# (geo id, geo, characteristic id, characteristic, unit, scalar id, vector)
SERIES = [
    (1, "Canada", 3, "Employment", "Persons in thousands", 3, 2062811),
    (7, "Ontario", 3, "Employment", "Persons in thousands", 3, 2063945),
    (10, "Alberta", 3, "Employment", "Persons in thousands", 3, 2064512),
    (7, "Ontario", 7, "Unemployment rate", "Percent", 0, 2063949),
    (10, "Alberta", 7, "Unemployment rate", "Percent", 0, 2064516),
]
VALUES = {2062811: 21000.0, 2063945: 8200.0, 2064512: 2600.0, 2063949: 7.5, 2064516: 7.0}


def _csv() -> bytes:
    lines = [HEADER]
    for month in ("2025-11", "2025-12", "2026-01"):
        for geo_id, geo, char_id, char, unit, scalar, vector in SERIES:
            scale = "thousands" if scalar == 3 else "units"
            status = "E" if (vector == 2064516 and month == "2026-01") else ""
            lines.append(
                f'"{month}","{geo}","2021A00011","{char}","Seasonally adjusted","{unit}","0",'
                f'"{scale}","{scalar}","v{vector}","{geo_id}.{char_id}.1","{VALUES[vector]}",'
                f'"{status}","","","1"'
            )
    return "\n".join(lines).encode("utf-8")


def _cube() -> dict:
    def dim(position, name, members, has_uom=False):
        return {
            "dimensionPositionId": position,
            "dimensionNameEn": name,
            "dimensionNameFr": name,
            "hasUom": has_uom,
            "member": [
                {
                    "memberId": mid,
                    "memberNameEn": label,
                    "parentMemberId": parent,
                    "memberUomCode": uom,
                }
                for mid, label, parent, uom in members
            ],
        }

    return {
        "productId": str(PID),
        "cubeTitleEn": "Labour force characteristics, monthly, seasonally adjusted and trend-cycle",
        "cubeTitleFr": "Caractéristiques de la population active",
        "cubeStartDate": "2025-11-01",
        "cubeEndDate": "2026-01-01",
        "releaseTime": "2026-11-06T08:30",
        "frequencyCode": 6,
        "dimension": [
            dim(
                1,
                "Geography",
                [(1, "Canada", None, None), (7, "Ontario", 1, None), (10, "Alberta", 1, None)],
            ),
            dim(
                2,
                "Labour force characteristics",
                [(3, "Employment", None, 428), (7, "Unemployment rate", None, 239)],
                has_uom=True,
            ),
            dim(3, "Data type", [(1, "Seasonally adjusted", None, None)]),
        ],
    }


class _FakeStream:
    """MemberStream's blocks() over an in-memory CSV, a few lines per block."""

    def __init__(self, url, member, **kwargs) -> None:
        self.lines = _csv().split(b"\n")

    async def blocks(self):
        for at in range(0, len(self.lines), 4):
            yield b"\n".join(self.lines[at : at + 4])


@pytest.fixture
def table(monkeypatch, httpx_mock):
    async def cube(pid):
        return _cube(), False

    real_get = client._get

    async def get(method, **kwargs):
        if method != "getFullTableDownloadCSV":
            return await real_get(method, **kwargs)
        return {
            "status": "SUCCESS",
            "object": "https://www150.statcan.gc.ca/n1/tbl/csv/14100287-eng.zip",
        }

    async def check(url):
        return "downloadable"

    async def members(url):
        return [ZipMember("14100287.csv", 1000, len(_csv()), 8, 0)], 2

    monkeypatch.setattr(client, "cube_metadata_raw", cube)
    monkeypatch.setattr(client, "_get", get)
    monkeypatch.setattr(client, "check_file", check)
    monkeypatch.setattr(table_query, "list_members", members)
    monkeypatch.setattr(table_query, "MemberStream", _FakeStream)


async def _query(sql: str, **kwargs):
    fn = getattr(tools.wds_query_table, "fn", tools.wds_query_table)
    return await fn(product_id=PID, sql=sql, **kwargs)


async def test_a_slice_is_queried_with_one_column_per_dimension(table):
    result = await _query(
        "SELECT geography, value FROM obs WHERE labour_force_characteristics = 'Unemployment rate' "
        "AND ref_period = DATE '2026-01-01' ORDER BY value DESC"
    )
    assert result.rows == [["Ontario", 7.5], ["Alberta", 7.0]]
    assert result.source == "full-table file"
    assert result.rows_read == 15 and result.input_rows == 15
    assert result.dimension_columns == {
        "Geography": "geography_member",
        "Labour force characteristics": "labour_force_characteristics",
        "Data type": "data_type",
    }
    assert result.citation.startswith("Statistics Canada. Table 14-10-0287-01, Labour force")


async def test_a_follow_up_query_on_the_same_slice_reads_it_from_memory(table, monkeypatch):
    # Agreed with the owner on 2026-11-21: the LFS slice took about 16 s to read, and a
    # second SQL over the same members and periods is common.
    opened: list[str] = []
    real = _FakeStream.blocks

    def counting(self):
        opened.append("file")
        return real(self)

    monkeypatch.setattr(_FakeStream, "blocks", counting)
    first = await _query("SELECT count(*) FROM obs", members={"Geography": ["Alberta"]})
    second = await _query(
        "SELECT count(DISTINCT vector_id) FROM obs", members={"Geography": ["Alberta"]}
    )
    assert opened == ["file"]
    assert first.provenance.cached is False and second.provenance.cached is True
    assert second.input_rows == first.input_rows and second.source == "full-table file"
    assert "earlier call" in (second.provenance.coverage or "")
    # Other members, other periods, a new release or an old slice: read again.
    await _query("SELECT 1 FROM obs", members={"Geography": ["Ontario"]})
    await _query("SELECT 1 FROM obs", members={"Geography": ["Alberta"]}, start_period="2026")
    assert len(opened) == 3
    monkeypatch.setattr(table_query, "SLICE_CACHE_SECONDS", -1)
    await _query("SELECT 1 FROM obs", members={"Geography": ["Alberta"]})
    assert len(opened) == 4


async def test_kept_slices_stay_under_the_row_limit(table, monkeypatch):
    monkeypatch.setattr(table_query, "SLICE_CACHE_ROWS", 6)
    await _query("SELECT 1 FROM obs", members={"Geography": ["Alberta"]})
    await _query("SELECT 1 FROM obs", members={"Geography": ["Ontario"]})
    kept = list(table_query._SLICES.values())
    assert sum(len(k.rows) for k in kept) <= 6
    # The newest stays; the oldest went first.
    assert kept and {r[-3] for r in kept[-1].rows} == {"Ontario"}


async def test_a_host_that_refuses_ranges_is_read_in_one_pass(table, monkeypatch):
    # After its outage of 2026-11-21 StatCan's file servers answered five ranged requests
    # in six with the whole file; the CSV is then read in one download (live: the CPI
    # and LFS slices came back identical by either route).
    async def refused(url):
        raise RangeRefused(f"{url} does not support range requests (HTTP 200).")

    class OnePass:
        length = None

        def __init__(self, url, wanted, **limits):
            assert wanted("14100287.csv") and not wanted("14100287_MetaData.csv")

        async def blocks(self):
            async for block in _FakeStream(None, None).blocks():
                yield block

    monkeypatch.setattr(table_query, "list_members", refused)
    monkeypatch.setattr(table_query, "OnePassMember", OnePass)
    result = await _query("SELECT count(*) FROM obs")
    assert result.rows == [[15]] and result.source == "full-table file"


async def test_members_and_periods_narrow_the_slice(table):
    result = await _query(
        "SELECT count(*), min(ref_period) FROM obs",
        members={"Geography": ["Alberta"]},
        start_period="2025-12",
    )
    assert result.rows == [[4, "2025-12-01"]]
    assert result.rows_read == 15


async def test_the_obs_columns_are_filled_from_the_file(table):
    result = await _query(
        "SELECT unit, scale, scale_multiplier, adjustment, quality, series_title FROM obs "
        "WHERE vector_id = 2064516 AND ref_period = DATE '2026-01-01'"
    )
    assert result.rows == [
        [
            "Percent",
            "units",
            1,
            "seasonally adjusted",
            "E",
            "Alberta;Unemployment rate;Seasonally adjusted",
        ]
    ]


async def test_the_checks_refuse_a_total_with_its_parts(table):
    with pytest.raises(InvalidInput, match="total_with_parts"):
        await _query(
            "SELECT ref_period, sum(value) FROM obs "
            "WHERE labour_force_characteristics = 'Employment' GROUP BY 1"
        )


async def test_the_checks_warn_about_an_average_of_rates(table):
    result = await _query(
        "SELECT ref_period, avg(value) FROM obs "
        "WHERE labour_force_characteristics = 'Unemployment rate' GROUP BY 1"
    )
    kinds = [w.split(":")[0] for w in result.warnings]
    assert kinds == ["average_of_rates", "quality"]


async def test_a_misspelled_member_fails_before_the_download(table, monkeypatch):
    async def no_download(*args, **kwargs):
        raise AssertionError("the file must not be read")

    monkeypatch.setattr(table_query, "_from_file", no_download)
    with pytest.raises(InvalidInput, match="did you mean 'Employment'"):
        await _query("SELECT avg(value) FROM obs WHERE labour_force_characteristics = 'Employmnt'")


async def test_unknown_members_and_bad_periods_are_refused(table):
    with pytest.raises(InvalidInput, match="saskatoon"):
        await _query("SELECT 1 FROM obs", members={"Geography": ["Saskatoon"]})
    with pytest.raises(InvalidInput, match="start_period"):
        await _query("SELECT 1 FROM obs", start_period="Jan 2025")


async def test_an_empty_slice_is_not_found(table):
    with pytest.raises(NotFound):
        await _query("SELECT 1 FROM obs", start_period="2030")


async def test_a_table_over_the_size_limit_is_refused(table, monkeypatch):
    async def big(url):
        return [ZipMember("14100287.csv", table_query.MAX_ZIP_BYTES + 1, 10**10, 8, 0)], 2

    monkeypatch.setattr(table_query, "list_members", big)
    with pytest.raises(InvalidInput, match="over the 200 MB"):
        await _query("SELECT 1 FROM obs")


async def test_a_blocked_file_is_rebuilt_from_wds(table, monkeypatch):
    async def blocked(url):
        return "blocked"

    asked: list[list[str]] = []

    async def coords(pid, coordinates, latest_n):
        asked.append(coordinates)
        series = []
        for coordinate in coordinates:
            geo, char = (int(p) for p in coordinate.split(".")[:2])
            match = next(s for s in SERIES if s[0] == geo and s[2] == char)
            series.append(
                VectorSeries(
                    product_id=pid,
                    coordinate=coordinate,
                    vector_id=match[6],
                    observations=[
                        ObservationRow(
                            ref_period=date(2026, 1, 1),
                            value=VALUES[match[6]],
                            decimals=1,
                            scalar_factor_code=match[5],
                            scale_multiplier=10 ** match[5],
                            symbol_code=0,
                            status_code=0,
                            security_level_code=0,
                        )
                    ],
                )
            )
        return VectorData(
            product_id=pid,
            coordinate=coordinates[0],
            vector_id=0,
            observations=[],
            series=series,
            provenance=make_provenance(
                source="statcan-wds", url="https://x", cached=False, schema_name="s"
            ),
        )

    monkeypatch.setattr(client, "check_file", blocked)
    monkeypatch.setattr(client, "get_data_from_cube_pid_coords_and_latest_n_periods", coords)
    result = await _query(
        "SELECT geography, unit, scale, value FROM obs ORDER BY vector_id",
        members={"Geography": ["Ontario"]},
    )
    assert result.source == "WDS by coordinate"
    assert asked == [["7.3.1.0.0.0.0.0.0.0", "7.7.1.0.0.0.0.0.0.0"]]
    assert result.rows == [
        ["Ontario", "Persons in thousands", "thousands", 8200.0],
        ["Ontario", "Percent", "units", 7.5],
    ]


def test_dimension_columns_never_shadow_an_obs_column():
    taken = {"geography", "unit"}
    assert table_query.dimension_column("Geography", taken) == "geography_member"
    assert table_query.dimension_column("Age group", taken) == "age_group"
    assert table_query.dimension_column("2021 boundaries", taken) == "d_2021_boundaries"


# A fiscal-year table: the CSV writes its periods "2019/2020" (35-10-0044, as
# reproduce/wds_table.py's wds_ref_date documents), and WDS dates the same period by
# its first day, refPer 2019-04-01. "2021-Q3" is not a form StatCan writes: it stands
# for any REF_DATE the tool cannot read.
FISCAL = ["2018/2019", "2019/2020", "2020/2021", "2021-Q3"]


def _fiscal_csv() -> bytes:
    lines = [HEADER]
    for n, period in enumerate(FISCAL):
        lines.append(
            f'"{period}","Canada","2021A00011","Employment","Seasonally adjusted",'
            f'"Persons in thousands","0","thousands","3","v2062811","1.3.1","{100.0 + n}",'
            '"","","","1"'
        )
    return "\n".join(lines).encode("utf-8")


@pytest.fixture
def fiscal_table(table, monkeypatch):
    async def cube(pid):
        return {**_cube(), "frequencyCode": 12}, False

    class FiscalStream(_FakeStream):
        def __init__(self, url, member, **kwargs) -> None:
            self.lines = _fiscal_csv().split(b"\n")

    monkeypatch.setattr(client, "cube_metadata_raw", cube)
    monkeypatch.setattr(table_query, "MemberStream", FiscalStream)


def test_ref_date_with_two_ends_is_dated_by_its_first_year():
    assert table_query._ref_period("2019/2020") == date(2019, 1, 1)
    assert table_query._ref_period("1994/1998") == date(1994, 1, 1)
    # Any span is dated by its first side (wds_ref_date's other forms too).
    assert table_query._ref_period("2019-04/2020-03") == date(2019, 4, 1)
    assert table_query._ref_period("2019-04-01/2020-03-31") == date(2019, 4, 1)
    assert table_query._ref_period("2019/20") == date(2019, 1, 1)
    assert table_query._ref_period("x/2020") is None
    assert table_query._ref_period("2019") == date(2019, 1, 1)
    # As text "2019/2020" sorted after "2019-06" ('/' > '-') and was kept.
    first, last = table_query._bounds("2019-06", "2020")
    assert (first, last) == (date(2019, 6, 1), date(2020, 12, 31))
    assert not table_query._in_window(date(2019, 1, 1), first, last)
    assert table_query._in_window(date(2020, 1, 1), first, last)


async def test_a_fiscal_year_table_has_dated_rows_and_warns_about_the_rest(fiscal_table):
    result = await _query(
        "SELECT ref_period, value FROM obs WHERE ref_period >= DATE '2019-01-01' "
        "ORDER BY ref_period DESC",
        start_period="2019",
    )
    assert result.rows == [["2020-01-01", 102.0], ["2019-01-01", 101.0]]
    # 2018/2019 is outside the window; the unreadable row is kept, undated, and named.
    assert result.input_rows == 3
    undated = [w for w in result.warnings if w.startswith("undated_rows")]
    expected = (
        "undated_rows: 1 row of obs has a REF_DATE this tool could not read as a date, so "
        "its ref_period is NULL: a filter on ref_period leaves it out, and ORDER BY "
        "ref_period puts it last."
    )
    assert undated == [expected]
    spans = [w for w in result.warnings if w.startswith("span_periods")]
    assert len(spans) == 1 and "1 January 2019" in spans[0] and "2019-04-01" in spans[0]
    # A follow-up query on the kept slice says the same.
    again = await _query("SELECT count(*) FROM obs", start_period="2019")
    assert again.provenance.cached and any(w.startswith("span_periods") for w in again.warnings)
    french = await _query("SELECT count(*) FROM obs", start_period="2019", lang="fr")
    assert any("1er janvier 2019" in w for w in french.warnings)
    assert any(w.startswith("undated_rows") and "1 ligne de obs a" in w for w in french.warnings)


async def test_a_table_without_spans_gets_no_span_warning(table):
    result = await _query("SELECT count(*) FROM obs")
    assert not any(w.startswith(("span_periods", "undated_rows")) for w in result.warnings)


async def test_an_impossible_period_is_named_as_not_a_date(table):
    with pytest.raises(InvalidInput, match=r"not a valid date \(like 2020-13 or 2020-02-30\)"):
        await _query("SELECT 1 FROM obs", start_period="2020-13")


async def test_both_routes_date_a_fiscal_year_alike(fiscal_table, monkeypatch):
    async def blocked(url):
        return "blocked"

    async def coords(pid, coordinates, latest_n):
        rows = [
            ObservationRow(
                ref_period=date(year, 4, 1),
                value=100.0 + n,
                decimals=1,
                scalar_factor_code=3,
                scale_multiplier=1000,
                symbol_code=0,
                status_code=0,
                security_level_code=0,
            )
            for n, year in enumerate((2018, 2019, 2020))
        ]
        return VectorData(
            product_id=pid,
            coordinate=coordinates[0],
            vector_id=2062811,
            observations=rows,
            provenance=make_provenance(
                source="statcan-wds", url="https://x", cached=False, schema_name="s"
            ),
        )

    sql = "SELECT ref_period, value FROM obs ORDER BY ref_period"
    members = {"Geography": ["Canada"], "Labour force characteristics": ["Employment"]}
    from_file = await _query(sql, members=members, start_period="2019")
    monkeypatch.setattr(client, "check_file", blocked)
    monkeypatch.setattr(client, "get_data_from_cube_pid_coords_and_latest_n_periods", coords)
    table_query.clear_slice_cache()
    from_wds = await _query(sql, members=members, start_period="2019")
    assert from_wds.source == "WDS by coordinate"
    assert from_wds.rows == [["2019-01-01", 101.0], ["2020-01-01", 102.0]]
    assert [r for r in from_file.rows if r[0] is not None] == from_wds.rows


# The WDS rebuild (the route when the file is blocked). Its helper refuses a call of more
# than INLINE_MAX_OBSERVATIONS observations (coordinates x latest_n), so the rebuild has to
# size its batches by the periods it asks for, as the script from
# wds_get_full_table_download does, and not by a fixed 300 coordinates.
def _wds_series(pid, coordinate, vector, value=1.0, when=date(2026, 1, 1), periods=1):
    """A series of `periods` consecutive months from `when`."""
    return VectorSeries(
        product_id=pid,
        coordinate=coordinate,
        vector_id=vector,
        observations=[
            ObservationRow(
                ref_period=date(
                    when.year + (when.month - 1 + n) // 12, (when.month - 1 + n) % 12 + 1, 1
                ),
                value=value,
                decimals=1,
                scalar_factor_code=0,
                scale_multiplier=1,
                symbol_code=0,
                status_code=0,
                security_level_code=0,
            )
            for n in range(periods)
        ],
    )


def _wds_data(pid, series):
    return VectorData(
        product_id=pid,
        coordinate=series[0].coordinate,
        vector_id=0,
        observations=[],
        series=series,
        provenance=make_provenance(
            source="statcan-wds", url="https://x", cached=False, schema_name="s"
        ),
    )


@pytest.fixture
def blocked_table(table, monkeypatch):
    async def blocked(url):
        return "blocked"

    monkeypatch.setattr(client, "check_file", blocked)


def _places_cube(count: int, start: str, frequency: int = 6) -> dict:
    """The test table with `count` places (one measure), a history from `start`."""
    base = _cube()
    return {
        **base,
        "cubeStartDate": start,
        "frequencyCode": frequency,
        "dimension": [
            {
                **base["dimension"][0],
                "member": [
                    {
                        "memberId": n,
                        "memberNameEn": f"Place {n}",
                        "parentMemberId": None,
                        "memberUomCode": None,
                    }
                    for n in range(1, count + 1)
                ],
            },
            {**base["dimension"][1], "member": base["dimension"][1]["member"][:1]},
            base["dimension"][2],
        ],
    }


async def test_a_long_history_is_rebuilt_in_batches_the_inline_limit_accepts(
    blocked_table, monkeypatch
):
    # 150 places x one measure: 150 coordinates, far under WDS_MAX_COORDINATES, but a
    # monthly history from 1990 asks 434 periods each, so one call of 150 would carry
    # 65,100 observations, over the 60,000 the helper accepts.
    cube = _places_cube(150, "1990-01-01")

    async def cube_metadata(pid):
        return cube, False

    batches: list[int] = []

    async def coords(pid, coordinates, latest_n):
        # The helper's own limit, which the rebuild used to trip.
        client.check_coordinates(coordinates, latest_n)
        batches.append(len(coordinates) * latest_n)
        return _wds_data(
            pid,
            [_wds_series(pid, c, 1000 + int(c.split(".")[0])) for c in coordinates],
        )

    monkeypatch.setattr(client, "cube_metadata_raw", cube_metadata)
    monkeypatch.setattr(client, "get_data_from_cube_pid_coords_and_latest_n_periods", coords)

    result = await _query("SELECT count(DISTINCT vector_id) FROM obs")

    assert result.source == "WDS by coordinate"
    assert result.rows == [[150]]
    assert len(batches) > 1 and max(batches) <= client.constants.INLINE_MAX_OBSERVATIONS


async def test_a_batch_of_unpublished_combinations_does_not_sink_the_rebuild(
    blocked_table, monkeypatch
):
    # Canada x Unemployment rate is not a series of this table. A call whose coordinates
    # are all unpublished raises NotFound (a lone one included); the rebuild keeps what the
    # other calls return instead of failing the whole query.
    monkeypatch.setattr(table_query, "_WDS_BATCH", 1)

    async def coords(pid, coordinates, latest_n):
        published = [c for c in coordinates if c == "1.3.1.0.0.0.0.0.0.0"]
        if not published:
            raise NotFound("Statistics Canada does not publish a series for this combination")
        return _wds_data(pid, [_wds_series(pid, c, 2062811, 21000.0) for c in published])

    monkeypatch.setattr(client, "get_data_from_cube_pid_coords_and_latest_n_periods", coords)

    result = await _query("SELECT value FROM obs", members={"Geography": ["Canada"]})

    assert result.source == "WDS by coordinate"
    assert result.rows == [[21000.0]]


async def test_a_slice_with_no_published_series_still_says_so(blocked_table, monkeypatch):
    async def coords(pid, coordinates, latest_n):
        raise NotFound("Statistics Canada does not publish a series for this combination")

    monkeypatch.setattr(client, "get_data_from_cube_pid_coords_and_latest_n_periods", coords)

    with pytest.raises(NotFound, match="does not publish"):
        await _query(
            "SELECT value FROM obs",
            members={
                "Geography": ["Canada"],
                "Labour force characteristics": ["Unemployment rate"],
            },
        )


# The WDS rebuild refuses a slice on the rows it collects, as the file route does, not on an
# estimate of them: members combine into many more coordinates than the table has series,
# and a series that starts late holds fewer periods than the table's history asks for.
async def test_a_sparse_slice_is_not_refused_by_the_upper_bound_on_its_rows(
    blocked_table, monkeypatch
):
    # 1,000 combinations of members x 434 monthly periods since 1990 would be 434,000 rows,
    # over the 300,000 cap, but the table publishes 150 series (and the helper answers
    # NotFound for a call with none), so the slice holds 150 rows: read by the file route
    # without trouble, and refused here before any call until 2026-11-28.
    cube = _places_cube(1000, "1990-01-01")

    async def cube_metadata(pid):
        return cube, False

    async def coords(pid, coordinates, latest_n):
        published = [c for c in coordinates if int(c.split(".")[0]) <= 150]
        if not published:
            raise NotFound("Statistics Canada does not publish a series for this combination")
        return _wds_data(pid, [_wds_series(pid, c, 1000 + int(c.split(".")[0])) for c in published])

    monkeypatch.setattr(client, "cube_metadata_raw", cube_metadata)
    monkeypatch.setattr(client, "get_data_from_cube_pid_coords_and_latest_n_periods", coords)

    result = await _query("SELECT count(*) FROM obs")

    assert result.source == "WDS by coordinate"
    assert result.rows == [[150]]


async def test_a_slice_over_the_row_cap_is_refused_on_the_rows_collected(
    blocked_table, monkeypatch
):
    # The cap, lowered for the test, is crossed in the third call (10 rows per series, one
    # series per call): the rebuild stops there, with the file route's message, and not
    # before the first call or after the last.
    monkeypatch.setattr(table_query, "MAX_ROWS", 25)
    monkeypatch.setattr(table_query, "_WDS_BATCH", 1)
    cube = _places_cube(5, "1990-01-01")

    async def cube_metadata(pid):
        return cube, False

    asked: list[int] = []

    async def coords(pid, coordinates, latest_n):
        asked.append(len(coordinates))
        return _wds_data(pid, [_wds_series(pid, c, 1, periods=10) for c in coordinates])

    monkeypatch.setattr(client, "cube_metadata_raw", cube_metadata)
    monkeypatch.setattr(client, "get_data_from_cube_pid_coords_and_latest_n_periods", coords)

    with pytest.raises(InvalidInput, match="more than 25 rows"):
        await _query("SELECT count(*) FROM obs")
    assert asked == [1, 1, 1]


@pytest.mark.parametrize("latest_n", [1, 199, 200, 201, 434, 2999, 3000, 3001, 9600])
def test_every_rebuild_batch_passes_the_helpers_observation_limit(latest_n):
    # client.check_coordinates refuses a call of several coordinates over
    # INLINE_MAX_OBSERVATIONS observations or over QUERY_MAX_LATEST_N periods; a lone
    # coordinate has no such limit, which is why a longer history is read one per call.
    step = table_query._batch_size(latest_n)
    batch = [f"{n}.1.1.0.0.0.0.0.0.0" for n in range(1, step + 1)]
    assert len(client.check_coordinates(batch, latest_n)) == step
    assert step <= client.constants.WDS_MAX_LIST


async def test_a_rebuild_past_the_time_budget_stops_with_the_took_too_long_error(
    blocked_table, monkeypatch
):
    cube = _places_cube(150, "1990-01-01")

    async def cube_metadata(pid):
        return cube, False

    # One series per call, each call "taking" 30 s of a clock the test moves by hand: the
    # budget (the tool timeout less 40 s, 80 s by default) is gone after three calls.
    monkeypatch.setattr(table_query, "_WDS_BATCH", 1)
    now = [1000.0]
    monkeypatch.setattr(table_query, "time", SimpleNamespace(monotonic=lambda: now[0]))
    calls: list[int] = []

    async def coords(pid, coordinates, latest_n):
        calls.append(len(coordinates))
        now[0] += 30.0
        return _wds_data(pid, [_wds_series(pid, c, 1) for c in coordinates])

    monkeypatch.setattr(client, "cube_metadata_raw", cube_metadata)
    monkeypatch.setattr(client, "get_data_from_cube_pid_coords_and_latest_n_periods", coords)

    with pytest.raises(UpstreamUnavailable, match="took longer than this tool's 80 s"):
        await _query("SELECT count(*) FROM obs")
    assert len(calls) == 3
