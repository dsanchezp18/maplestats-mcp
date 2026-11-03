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


def test_spills_go_to_the_configured_folder_not_the_working_directory(monkeypatch, tmp_path):
    # DuckDB's default is `.tmp` in the working directory, which is /app (owned
    # by root) in the Docker image, so spills failed there.
    spill_root = tmp_path / "spill"
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("MAPLE_DUCKDB_TEMP_DIR", str(spill_root))
    monkeypatch.setenv("MAPLE_DUCKDB_MEMORY_LIMIT", "32MB")
    seen: list[str] = []
    with duck.connect() as connection:
        temp = connection.execute("SELECT current_setting('temp_directory')").fetchone()[0]
        assert temp.startswith(str(spill_root))
        cap = connection.execute("SELECT current_setting('max_temp_directory_size')").fetchone()[0]
        assert cap in ("1.0 GiB", "1024.0 MiB")
        connection.execute("SET threads = 1")
        count = connection.execute(
            "SELECT count(*) FROM (SELECT i, md5(i::VARCHAR) AS h FROM range(1500000) t(i) "
            "ORDER BY h)"
        ).fetchone()[0]
        seen = [p.name for p in spill_root.iterdir()]
    assert count == 1_500_000
    assert seen, "the sort should have spilled under the configured folder"
    assert not (work / ".tmp").exists()
    # DuckDB removes the connection's own subfolder when it closes.
    assert list(spill_root.iterdir()) == []


def test_an_unwritable_temp_folder_turns_spilling_off(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    monkeypatch.setenv("MAPLE_DUCKDB_TEMP_DIR", str(blocker / "sub"))
    with duck.connect() as connection:
        temp = connection.execute("SELECT current_setting('temp_directory')").fetchone()[0]
    assert temp == ""
