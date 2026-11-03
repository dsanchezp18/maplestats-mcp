"""shared/duck_sandbox.py and shared/duck_worker.py: SQL in a capped child process.

wds_query_series's tests (modules/statcan/wds/__tests__/test_query.py) cover the
attacks end to end; these cover the pieces.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from maplestats_mcp.shared import duck_sandbox, duck_worker


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "FROM obs",
        "DESCRIBE obs",
        "SUMMARIZE obs",
        "VALUES (1)",
        "SELECT 1 UNION ALL SELECT 2 EXCEPT SELECT 3",
        (
            "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 3) "
            "SELECT * FROM r"
        ),
        "WITH m AS MATERIALIZED (SELECT 1 AS a) SELECT * FROM m",
        "SELECT * FROM (PIVOT obs ON unit IN ('x', 'y') USING sum(value))",
        "SELECT * FROM (UNPIVOT obs ON value INTO NAME n VALUE v)",
        (
            "SELECT value, rank() OVER (ORDER BY value) FROM obs QUALIFY rank() OVER "
            "(ORDER BY value) < 3"
        ),
        "SELECT list_transform([1, 2], x -> x + 1)",
        "SELECT 1 WHERE EXISTS (SELECT 1 FROM obs)",
    ],
)
def test_plain_selects_pass(sql):
    assert duck_sandbox.select_problem(sql) is None


@pytest.mark.parametrize(
    ("sql", "problem"),
    [
        ("SELEC 1", "parse"),
        ("SELECT 1; SELECT 2", ("count", "2")),
        ("PRAGMA import_database('/tmp')", ("type", "PRAGMA")),
        ("COPY (SELECT 1) TO 'x.csv'", ("type", "COPY")),
        (
            "WITH x AS (INSERT INTO obs VALUES (1) RETURNING *) SELECT * FROM x",
            ("modifying", "INSERT"),
        ),
        ("WITH x AS (DELETE FROM obs RETURNING *) SELECT * FROM x", ("modifying", "DELETE")),
        (
            "SELECT 1 WHERE 1 IN (WITH z AS (DELETE FROM obs RETURNING value) SELECT 1 FROM z)",
            ("modifying", "DELETE"),
        ),
        (
            "SELECT * FROM (WITH y AS (UPDATE obs SET value = 0 RETURNING *) SELECT * FROM y)",
            ("modifying", "UPDATE"),
        ),
    ],
)
def test_everything_else_is_named(sql, problem):
    found = duck_sandbox.select_problem(sql)
    assert found is not None
    if isinstance(problem, str):
        assert found[0] == problem
    else:
        assert found == problem


def test_clean_error_keeps_one_line_and_drops_paths():
    text = (
        'Permission Error: Cannot access directory "/home/someone/.duckdb/extensions/v2.0.0" '
        "- disabled\nLINE 1: SELECT ..."
    )
    assert duck_worker.clean_error(text) == (
        'Permission Error: Cannot access directory "<path>" - disabled'
    )
    assert "<path>" in duck_worker.clean_error(r"IO Error: C:\Users\someone\x.csv missing")
    # Not paths: a date with slashes, a division.
    assert duck_worker.clean_error("Conversion Error: '2024/01/02' to DATE") == (
        "Conversion Error: '2024/01/02' to DATE"
    )
    assert duck_worker.clean_error("x" * 1000).endswith("...")


def test_child_environment_carries_no_secrets(monkeypatch):
    monkeypatch.setenv("MAPLE_AUTH_TOKEN", "secret")
    monkeypatch.setenv("HOME", "/home/someone")
    env = duck_sandbox._child_env()
    assert "MAPLE_AUTH_TOKEN" not in env and "HOME" not in env
    assert env["MALLOC_ARENA_MAX"] == "2"


def test_repeated_columns_are_run_length_encoded():
    assert duck_sandbox._encode(["a"] * 5 + ["b"] * 5) == {"runs": [["a", 5], ["b", 5]]}
    assert duck_sandbox._encode([1, 2, 3]) == {"values": [1, 2, 3]}
    # 1 and True are equal in Python but not the same value.
    assert duck_sandbox._encode([1, True, 1, True]) == {"values": [1, True, 1, True]}


async def test_run_query_round_trips_types():
    table = duck_sandbox.Table(
        name="t",
        columns=[("d", "DATE"), ("ts", "TIMESTAMP"), ("v", "DOUBLE"), ("s", "VARCHAR")],
        values=[
            [date(2024, 1, 1), None],
            [datetime(2025, 1, 21, 8, 30), None],
            [1.5, None],
            ["é", "é"],
        ],
    )
    result = await duck_sandbox.run_query(
        [table],
        "SELECT d, ts, v, s, 1::DECIMAL(4,1) AS dec, 'nan'::DOUBLE AS nan FROM t ORDER BY d",
        seconds=5.0,
        row_cap=10,
        max_chars=10_000,
        max_cell_chars=100,
    )
    assert result.columns == ["d", "ts", "v", "s", "dec", "nan"]
    assert result.types[:3] == ["DATE", "TIMESTAMP", "DOUBLE"]
    assert result.rows == [
        ["2024-01-01", "2025-01-21T08:30:00", 1.5, "é", 1.0, None],
        [None, None, None, "é", 1.0, None],
    ]
    assert result.truncated is False


async def test_run_query_reports_the_row_cap():
    result = await duck_sandbox.run_query(
        [], "SELECT * FROM range(30)", seconds=5.0, row_cap=10, max_chars=10_000, max_cell_chars=100
    )
    assert len(result.rows) == 10 and result.truncated is True


async def test_the_child_checks_the_statement_again():
    # The parent's check is skipped here; the child refuses on its own.
    with pytest.raises(duck_sandbox.SandboxError) as caught:
        await duck_sandbox.run_query(
            [],
            "COPY (SELECT 1) TO 'x.csv'",
            seconds=5.0,
            row_cap=1,
            max_chars=100,
            max_cell_chars=10,
        )
    assert caught.value.kind == "statement" and "COPY" in caught.value.detail
