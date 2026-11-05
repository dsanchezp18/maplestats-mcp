"""wds_query_series: one read-only SQL query over fetched WDS observations.

The data are mocked in the live shapes of getDataFromVectorsAndLatestNPeriods,
getDataFromVectorByReferencePeriodRange, getSeriesInfoFromVector and
getCubeMetadata for v41690973 (CPI all-items, Canada, 18-10-0004) and v2062815
(LFS unemployment rate, Canada, 14-10-0287); the values are made up so the
expected sums and averages are easy to check by hand.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

from maplestats_mcp.modules.statcan.wds import client, constants, query, tools
from maplestats_mcp.shared.errors import InvalidInput

CPI, UNEMP = 41690973, 2062815
CPI_PID, LFS_PID = 18100004, 14100287


def _fn(t):
    return getattr(t, "fn", t)


def _months(year_values: dict[int, list[float]]) -> list[tuple[str, float]]:
    return [
        (f"{year}-{month:02d}-01", value)
        for year, values in year_values.items()
        for month, value in enumerate(values, start=1)
    ]


# CPI: 2023 averages 150.5 (150, 151 alternating), 2024 averages 160.
CPI_POINTS = _months({2023: [150.0, 151.0] * 6, 2024: [160.0] * 12})
# Unemployment: 2023 averages 5.5, 2024 averages 6.5; peak 7.5 in 2024-12.
UNEMP_POINTS = _months({2023: [5.0, 6.0] * 6, 2024: [6.0] * 6 + [6.5] + [7.0] * 4 + [7.5]})


def _series(vector, pid, coord, points, scalar=0):
    return {
        "status": "SUCCESS",
        "object": {
            "responseStatusCode": 0,
            "productId": pid,
            "coordinate": coord,
            "vectorId": vector,
            "vectorDataPoint": [
                {
                    "refPer": day,
                    "value": value,
                    "decimals": 1,
                    "scalarFactorCode": scalar,
                    "symbolCode": 0,
                    "statusCode": 0,
                    "securityLevelCode": 0,
                    "releaseTime": "2025-01-21T08:30",
                }
                for day, value in points
            ],
        },
    }


DATA = [
    _series(CPI, CPI_PID, "2.2.0.0.0.0.0.0.0.0", CPI_POINTS),
    _series(UNEMP, LFS_PID, "1.1.1.1.1.0.0.0.0.0", UNEMP_POINTS),
]


def _info(vector, pid, coord, title, uom):
    return {
        "status": "SUCCESS",
        "object": {
            "responseStatusCode": 0,
            "productId": pid,
            "coordinate": coord,
            "vectorId": vector,
            "frequencyCode": 6,
            "scalarFactorCode": 0,
            "decimals": 1,
            "terminated": 0,
            "SeriesTitleEn": title,
            "SeriesTitleFr": title,
            "memberUomCode": uom,
        },
    }


def _cube(pid, title, dims):
    return {
        "productId": str(pid),
        "cubeTitleEn": title,
        "cubeTitleFr": title,
        "cubeStartDate": "1914-01-01",
        "cubeEndDate": "2024-12-01",
        "releaseTime": "2025-01-21T08:30",
        "frequencyCode": 6,
        "dimension": [
            {
                "dimensionPositionId": position,
                "dimensionNameEn": name,
                "dimensionNameFr": name,
                "member": [{"memberId": member_id, "memberNameEn": member, "memberNameFr": member}],
            }
            for position, (name, member, member_id) in enumerate(dims, start=1)
        ],
    }


CUBES = {
    CPI_PID: _cube(
        CPI_PID,
        "Consumer Price Index, monthly, not seasonally adjusted",
        [("Geography", "Canada", 2), ("Products and product groups", "All-items", 2)],
    ),
    LFS_PID: _cube(
        LFS_PID,
        "Labour force characteristics, monthly, seasonally adjusted",
        [
            ("Geography", "Canada", 1),
            ("Labour force characteristics", "Unemployment rate", 1),
            ("Gender", "Total - Gender", 1),
            ("Age group", "15 years and over", 1),
            ("Statistics", "Estimate", 1),
        ],
    ),
}


def _metadata(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}getSeriesInfoFromVector",
        json=[
            _info(UNEMP, LFS_PID, "1.1.1.1.1.0.0.0.0.0", "Canada;Unemployment rate", 239),
            _info(CPI, CPI_PID, "2.2.0.0.0.0.0.0.0.0", "Canada;All-items", 17),
        ],
        is_optional=True,
    )
    for pid, cube in CUBES.items():
        httpx_mock.add_response(
            url=f"{constants.BASE_URL}getCubeMetadata",
            match_json=[{"productId": pid}],
            json=[{"status": "SUCCESS", "object": cube}],
            is_optional=True,
        )


def _latest(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}getDataFromVectorsAndLatestNPeriods", json=DATA
    )
    _metadata(httpx_mock)


async def _query(sql, vector_ids=(CPI, UNEMP), **kwargs):
    return await _fn(tools.wds_query_series)(vector_ids=list(vector_ids), sql=sql, **kwargs)


async def test_sum(httpx_mock):
    _latest(httpx_mock)
    result = await _query(
        "SELECT vector_id, sum(value) AS total, count(*) AS n FROM obs "
        "GROUP BY vector_id ORDER BY vector_id",
        latest_n=24,
    )
    assert result.columns == ["vector_id", "total", "n"]
    assert result.rows == [[UNEMP, pytest.approx(144.0), 24], [CPI, pytest.approx(3726.0), 24]]
    assert result.input_rows == 48 and not result.truncated


async def test_average_by_year_with_context_columns(httpx_mock):
    _latest(httpx_mock)
    result = await _query(
        "SELECT unit, geography, year(ref_period) AS year, avg(value) AS annual_average "
        "FROM obs GROUP BY ALL ORDER BY unit, year",
        latest_n=24,
    )
    assert result.rows == [
        ["2002=100", "Canada", 2023, pytest.approx(150.5)],
        ["2002=100", "Canada", 2024, pytest.approx(160.0)],
        ["Percent", "Canada", 2023, pytest.approx(5.5)],
        ["Percent", "Canada", 2024, pytest.approx(6.5)],
    ]
    assert result.column_types[2] == "BIGINT"
    by_vector = {s.vector_id: s for s in result.series}
    assert by_vector[CPI].citation.startswith("Statistics Canada. Table 18-10-0004-01")
    assert f"v{UNEMP}" in by_vector[UNEMP].citation
    assert by_vector[CPI].context is not None
    assert by_vector[CPI].context.unit == "2002=100"
    assert by_vector[CPI].observation_count == 24
    limits = result.provenance.limits or ""
    assert "capped at 500" in limits and "read-only" in limits
    assert result.provenance.schema_name == "statcan.wds.SeriesQueryResult"
    assert "48 observations of 2 series" in (result.provenance.coverage or "")


async def test_ranking_with_cte_and_dates_as_text(httpx_mock):
    _latest(httpx_mock)
    result = await _query(
        "WITH ranked AS (SELECT ref_period, value, rank() OVER (ORDER BY value DESC) AS r "
        f"FROM obs WHERE vector_id = {UNEMP}) SELECT ref_period, value, r FROM ranked "
        "WHERE r <= 3 ORDER BY r, ref_period",
        latest_n=24,
    )
    assert result.rows[0] == ["2024-12-01", 7.5, 1]
    assert [row[2] for row in result.rows] == [1, 2, 2, 2, 2]
    assert result.column_types[0] == "DATE"


async def test_reference_period_range_uses_the_range_endpoint(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}getDataFromVectorByReferencePeriodRange"
            f"?vectorIds={CPI}&startRefPeriod=2023-01-01&endReferencePeriod=2024-12-31"
        ),
        json=[DATA[0]],
    )
    _metadata(httpx_mock)
    result = await _query(
        "SELECT max(value) FROM obs",
        vector_ids=[CPI],
        start_ref_period="2023-01",
        end_ref_period="2024-12",
    )
    assert result.rows == [[160.0]]
    assert "2023-01 to 2024-12" in (result.provenance.coverage or "")


async def test_row_cap(httpx_mock):
    _latest(httpx_mock)
    result = await _query("SELECT range AS i FROM range(600)")
    assert result.row_count == constants.QUERY_ROW_CAP == len(result.rows)
    assert result.truncated is True
    assert "more were returned and cut" in (result.provenance.limits or "")


@pytest.mark.parametrize(
    ("sql", "says"),
    [
        ("DROP TABLE obs", "DROP statement"),
        ("INSERT INTO obs (vector_id) VALUES (1)", "INSERT statement"),
        ("COPY obs TO 'out.csv'", "COPY statement"),
        ("ATTACH 'other.duckdb'", "ATTACH statement"),
        ("SET enable_external_access = true", "SET statement"),
        ("PRAGMA version", "PRAGMA statement"),
        ("UPDATE obs SET value = 0", "UPDATE statement"),
        ("SELECT 1; DROP TABLE obs", "2 statements"),
        ("SELECT 1; SELECT 2", "2 statements"),
        ("", "must not be empty"),
        ("PRAGMA import_database('/tmp')", "PRAGMA statement"),
        # Data-modifying CTEs: extract_statements calls these SELECTs.
        (
            "WITH x AS (INSERT INTO obs (vector_id) VALUES (1) RETURNING *) SELECT * FROM x",
            "INSERT statement (in a WITH",
        ),
        ("WITH x AS (DELETE FROM obs RETURNING *) SELECT count(*) FROM x", "DELETE statement"),
        (
            "SELECT * FROM (WITH y AS (UPDATE obs SET value = 0 RETURNING *) SELECT * FROM y)",
            "UPDATE statement",
        ),
    ],
)
async def test_non_select_is_rejected_before_any_fetch(httpx_mock, sql, says):
    # No response is registered: a rejected query must not reach WDS at all.
    with pytest.raises(InvalidInput) as caught:
        await _query(sql)
    assert says in str(caught.value)
    assert not httpx_mock.get_requests()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_text('/etc/hostname')",
        "SELECT * FROM 'https://example.com/data.csv'",
        "SELECT * FROM read_parquet('s3://bucket/x.parquet')",
        "SELECT * FROM glob('/*')",
    ],
)
async def test_file_and_network_access_is_disabled(httpx_mock, sql):
    _latest(httpx_mock)
    with pytest.raises(InvalidInput) as caught:
        await _query(sql)
    message = str(caught.value)
    assert "disabled" in message and "vector_id, product_id" in message
    # Only WDS was called: the URL in the SQL never was.
    assert all("statcan.gc.ca" in str(r.url) for r in httpx_mock.get_requests())


async def test_unknown_column_names_the_obs_columns(httpx_mock):
    _latest(httpx_mock)
    with pytest.raises(InvalidInput) as caught:
        await _query("SELECT refper, avg(value) FROM obs GROUP BY refper")
    message = str(caught.value)
    assert "refper" in message and "failed in DuckDB" in message
    assert "ref_period" in message and "Example: SELECT" in message


async def test_syntax_error_is_invalid_input():
    with pytest.raises(InvalidInput, match="does not parse"):
        await _query("SELEC value FROM obs")


async def test_runaway_query_is_interrupted(httpx_mock, monkeypatch):
    _latest(httpx_mock)
    monkeypatch.setattr(query, "query_time_limit", lambda: 0.3)
    with pytest.raises(InvalidInput, match="limit and was stopped"):
        await _query("SELECT sum(a.range * b.range) FROM range(200000) a, range(200000) b")


async def test_argument_checks():
    with pytest.raises(InvalidInput, match="limit is 20"):
        await _query("SELECT 1", vector_ids=range(1, 22))
    with pytest.raises(InvalidInput, match="both start_ref_period"):
        await _query("SELECT 1", start_ref_period="2024-01")
    with pytest.raises(InvalidInput, match="not both"):
        await _query("SELECT 1", start_ref_period="2024-01", end_ref_period="2024-02", latest_n=3)
    with pytest.raises(InvalidInput, match="latest_n must be between"):
        await _query("SELECT 1", latest_n=0)
    with pytest.raises(InvalidInput, match="must not be empty"):
        await _query("SELECT 1", vector_ids=[])


async def test_french_error():
    with pytest.raises(InvalidInput) as caught:
        await _query("DELETE FROM obs", lang="fr")
    assert "Une seule requête en lecture" in str(caught.value)
    client.use_lang("en")


def test_citation_prefers_the_context_citation():
    from maplestats_mcp.modules.statcan.wds.schemas import SeriesContext, VectorSeries

    ctx = SeriesContext(table_id="18-10-0004-01", table_url="https://x", table_title="CPI")
    series = VectorSeries(
        product_id=CPI_PID, coordinate="2.2", vector_id=CPI, observations=[], context=ctx
    )
    assert (
        query.citation(series) == "Statistics Canada. Table 18-10-0004-01, CPI. Vector v41690973."
    )
    with_ready = series.model_copy(
        update={"context": ctx.model_copy(update={"citation": "Ready."})}
    )
    # Pydantic keeps an unknown field on model_copy(update=...), which is how
    # this test stands in for SeriesContext.citation before that field merges.
    assert query.citation(with_ready) == "Ready."


# Denial of service, found in review on 2026-11-03 (duckdb 2.0.0, 256 MB
# memory_limit, in-process): each of these reached 1.4-9.6 GB or had the
# server killed, and ran 16-29 s past a 5 s limit. Now each runs in a child
# process capped at MAPLE_QUERY_MEMORY_MB and must fail fast with a typed error.
_MEMORY_ATTACKS = [
    "SELECT len(range(1000000000))",
    "SELECT len(range(100000000))",
    "SELECT length(repeat('x', 4000000000))",
    "SELECT repeat('x', 10000000) FROM range(500)",
    "SELECT sum(len(range(i))) FROM range(100000) t(i)",
]


def _peak_rss_mb() -> float:
    if sys.platform == "win32":
        return 0.0  # only called by the Linux-only test below
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="RLIMIT_AS is enforced on Linux only; elsewhere these would use the machine's memory",
)
@pytest.mark.parametrize("sql", _MEMORY_ATTACKS)
async def test_memory_attack_fails_fast_without_growing_the_server(httpx_mock, monkeypatch, sql):
    _latest(httpx_mock)
    monkeypatch.setenv("MAPLE_QUERY_MEMORY_MB", "64")
    monkeypatch.setattr(query, "query_time_limit", lambda: 3.0)
    before = _peak_rss_mb()
    started = time.monotonic()
    with pytest.raises(InvalidInput) as caught:
        await _query(sql)
    elapsed = time.monotonic() - started
    message = str(caught.value)
    assert "64 MB a query may use" in message or "limit and was stopped" in message
    assert elapsed < 3.0 + 2.0
    # The server's own peak barely moves: the work happened in the child.
    assert _peak_rss_mb() - before < 100


async def test_result_size_is_capped_in_characters_not_only_rows(httpx_mock):
    # 100 rows of 40,000 characters: under the row cap and the cell cap, past
    # the 1,000,000-character result cap.
    _latest(httpx_mock)
    with pytest.raises(InvalidInput, match="1,000,000 characters and was stopped"):
        await _query("SELECT repeat('x', 40000) AS s FROM range(100)")


async def test_one_long_cell_is_refused(httpx_mock):
    _latest(httpx_mock)
    with pytest.raises(InvalidInput) as caught:
        await _query("SELECT repeat('x', 60000) AS long_text")
    assert "'long_text'" in str(caught.value) and "50000 characters" in str(caught.value)


async def test_the_time_limit_kills_the_process_and_frees_the_event_loop(httpx_mock, monkeypatch):
    # A deadline shorter than the child's start: the parent kills it, and the
    # event loop keeps running meanwhile (no thread holds the call).
    import anyio

    from maplestats_mcp.shared import duck_sandbox

    _latest(httpx_mock)
    monkeypatch.setattr(query, "query_time_limit", lambda: 0.05)
    monkeypatch.setattr(duck_sandbox, "STARTUP_SECONDS", 0.0)
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        while True:
            await anyio.sleep(0.01)
            ticks += 1

    started = time.monotonic()
    async with anyio.create_task_group() as tg:
        tg.start_soon(tick)
        with pytest.raises(InvalidInput, match="limit and was stopped"):
            await _query("SELECT count(*) FROM range(100000) a, range(100000) b")
        tg.cancel_scope.cancel()
    assert time.monotonic() - started < 2.0
    assert ticks >= 1


async def test_duckdb_errors_are_one_line_without_paths(httpx_mock):
    _latest(httpx_mock)
    with pytest.raises(InvalidInput) as caught:
        await _query("SELECT extension_name, install_path FROM duckdb_extensions()")
    message = str(caught.value)
    assert "disabled" in message and "<path>" in message
    assert os.path.expanduser("~") not in message and ".duckdb" not in message


async def test_duckdb_errors_keep_only_their_first_line(httpx_mock):
    _latest(httpx_mock)
    with pytest.raises(InvalidInput) as caught:
        await _query("SELECT refper FROM obs")
    assert "LINE 1" not in str(caught.value)
