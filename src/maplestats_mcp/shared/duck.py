"""DuckDB connections that honour MAPLE_DUCKDB_MEMORY_LIMIT."""

from __future__ import annotations

import re
from typing import Any

from maplestats_mcp import config

_LIMIT = re.compile(r"[0-9]+(\.[0-9]+)?\s*(KB|MB|GB|TB|KiB|MiB|GiB|TiB)", re.IGNORECASE)


def connect() -> Any:
    """A new in-memory DuckDB connection, with the configured memory limit set.

    Imported on first use: duckdb takes about 0.5 s to import.
    """
    import duckdb

    connection = duckdb.connect()
    limit = config.get_duckdb_memory_limit()
    if limit:
        if not _LIMIT.fullmatch(limit):
            connection.close()
            raise ValueError(f"MAPLE_DUCKDB_MEMORY_LIMIT={limit!r} is not a size such as '256MB'.")
        connection.execute(f"SET memory_limit='{limit}'")
    return connection
