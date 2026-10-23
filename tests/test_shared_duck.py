"""shared/duck.py: DuckDB connections that honour MAPLE_DUCKDB_MEMORY_LIMIT."""

from __future__ import annotations

import pytest

from maplestats_mcp.shared import duck


def test_no_limit_is_set_by_default(monkeypatch):
    monkeypatch.delenv("MAPLE_DUCKDB_MEMORY_LIMIT", raising=False)
    with duck.connect() as connection:
        limit = connection.execute("SELECT current_setting('memory_limit')").fetchone()[0]
    assert limit != "244.1 MiB"


def test_the_configured_limit_is_applied(monkeypatch):
    monkeypatch.setenv("MAPLE_DUCKDB_MEMORY_LIMIT", "256MB")
    with duck.connect() as connection:
        limit = connection.execute("SELECT current_setting('memory_limit')").fetchone()[0]
    assert limit.startswith("244.")  # 256 MB in MiB


def test_a_bad_limit_is_refused_before_it_reaches_sql(monkeypatch):
    monkeypatch.setenv("MAPLE_DUCKDB_MEMORY_LIMIT", "1GB'; DROP TABLE x; --")
    with pytest.raises(ValueError, match="MAPLE_DUCKDB_MEMORY_LIMIT"):
        duck.connect()
