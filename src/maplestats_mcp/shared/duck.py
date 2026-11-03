"""DuckDB connections that honour MAPLE_DUCKDB_MEMORY_LIMIT and spill to a known folder."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from maplestats_mcp import config

_LIMIT = re.compile(r"[0-9]+(\.[0-9]+)?\s*(KB|MB|GB|TB|KiB|MiB|GiB|TiB)", re.IGNORECASE)


logger = logging.getLogger("maplestats_mcp.duck")
_warned: set[str] = set()


def _warn_once(message: str) -> None:
    if message not in _warned:
        _warned.add(message)
        logger.warning(message)


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def connect() -> Any:
    """A new in-memory DuckDB connection, with the configured memory limit set.

    Past the limit DuckDB spills to disk. Its default folder is `.tmp` in the
    working directory, which in the Docker image is /app, owned by root, so
    spills failed there; each connection now spills to its own subfolder of
    config.get_duckdb_temp_dir() (the system temp folder by default), capped at
    MAPLE_DUCKDB_TEMP_MAX_GB. DuckDB creates the subfolder on the first spill
    and removes it when the connection closes (checked on duckdb 2.0.0); one
    folder per connection keeps two connections' files apart.

    Imported on first use: duckdb takes about 0.5 s to import.
    """
    import duckdb

    limit = config.get_duckdb_memory_limit()
    if limit and not _LIMIT.fullmatch(limit):
        raise ValueError(f"MAPLE_DUCKDB_MEMORY_LIMIT={limit!r} is not a size such as '256MB'.")
    connection = duckdb.connect()
    try:
        if limit:
            connection.execute(f"SET memory_limit='{limit}'")
        base = config.get_duckdb_temp_dir()
        try:
            base.mkdir(parents=True, exist_ok=True, mode=0o700)
            spill = str(base / uuid.uuid4().hex)
        except OSError as exc:
            # No spilling rather than DuckDB's `.tmp` in the working directory:
            # a query past the memory limit then fails with DuckDB's own error.
            _warn_once(f"DuckDB temp folder {base} is not writable ({exc}); spilling is off.")
            spill = ""
        connection.execute(f"SET temp_directory={_literal(spill)}")
        max_mb = config.get_duckdb_temp_max_bytes() // (1024 * 1024)
        connection.execute(f"SET max_temp_directory_size='{max_mb}MiB'")
    except BaseException:
        connection.close()
        raise
    return connection
