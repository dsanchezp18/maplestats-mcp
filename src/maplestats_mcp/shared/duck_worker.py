"""The child process that runs a caller's SQL in DuckDB (shared/duck_sandbox.py starts it).

Run as `python -I -m maplestats_mcp.shared.duck_worker`: one JSON job on stdin,
one JSON answer on stdout, then exit. It imports only the standard library and
duckdb, so it starts in about 0.15 s.

Why a separate process: DuckDB's memory_limit covers its buffer manager, not
the scalar functions that build one value. On duckdb 2.0.0 with a 256 MB limit
(2026-11-03), `SELECT len(range(100000000))` reached 7.0 GB in 16 s, `SELECT
length(repeat('x', 4000000000))` 7.7 GB, and `SELECT len(range(1000000000))`
had the server killed. connection.interrupt() acts only between operators, so
the time limit did not stop them either. Here the address space is capped with
RLIMIT_AS after the data are loaded (Linux, and other Unix systems that enforce
it), so those queries fail in about 0.1 s with DuckDB's own out-of-memory error,
and the parent kills the process at its deadline whatever DuckDB is doing.
Windows has no RLIMIT_AS: there the time limit, the result caps and DuckDB's
memory_limit still apply, but a single huge value is bounded only by the machine.

The classifier and the error cleaner live here too, so the parent's early
check and the child's own check are one function.
"""

from __future__ import annotations

import json
import math
import re
import sys
import threading
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any

# Applied in order after connecting; the lock must come last, since once it is
# set no statement can change a setting. Checked against duckdb 2.0.0: with
# external access off, read_csv, read_text, glob, 'https://...' and 's3://...'
# raise PermissionException, and LOAD httpfs fails with autoload off.
SANDBOX = (
    "SET autoinstall_known_extensions = false",
    "SET autoload_known_extensions = false",
    "SET allow_community_extensions = false",
    "SET enable_external_access = false",
    "SET lock_configuration = true",
)

# Query nodes a pure SELECT is made of. json_serialize_sql (duckdb 2.0.0) shows a
# data-modifying CTE as INSERT_QUERY_NODE, DELETE_QUERY_NODE or UPDATE_QUERY_NODE
# inside a statement that extract_statements still calls a SELECT.
_SELECT_NODES = frozenset({"SELECT_NODE", "SET_OPERATION_NODE", "RECURSIVE_CTE_NODE", "CTE_NODE"})

# An absolute path (/home/x/.duckdb, C:\Users\x, \\server\share) after a non-word
# character: duckdb_extensions() named the home folder in its error.
_PATH = re.compile(r"(?<![\w.])(?:[A-Za-z]:[\\/]|\\\\|~[\\/]|/)(?:[^\s'\"`\\/]+[\\/])+[^\s'\"`]*")
_ERROR_CHARS = 300
_LOAD_CHUNK = 5_000


def clean_error(text: str) -> str:
    """DuckDB's message cut to its first line, with filesystem paths removed."""
    first = next((line.strip() for line in str(text).splitlines() if line.strip()), "")
    first = _PATH.sub("<path>", first)
    return first if len(first) <= _ERROR_CHARS else first[: _ERROR_CHARS - 3] + "..."


def open_sandbox(memory_mb: int) -> Any:
    """An in-memory connection: one thread, a memory limit, no spilling, no files, locked."""
    import duckdb

    # temp_directory '' turns spilling off: `obs` is small, so a query that needs
    # disk is one to stop, not to serve. Set at connect time because
    # enable_external_access=false forbids changing it afterwards.
    connection = duckdb.connect(
        config={"threads": 1, "memory_limit": f"{max(16, memory_mb)}MB", "temp_directory": ""}
    )
    for statement in SANDBOX:
        connection.execute(statement)
    return connection


def _node_types(tree: Any) -> Iterator[str]:
    stack = [tree]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            kind = value.get("type")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if isinstance(kind, str) and kind.endswith("_NODE"):
                yield kind
            stack.extend(value.values())  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        elif isinstance(value, list):
            stack.extend(value)  # pyright: ignore[reportUnknownArgumentType]


def select_problem(connection: Any, sql: str) -> tuple[str, str] | None:
    """None when `sql` is exactly one pure SELECT, else (kind, detail).

    kind is "parse" (detail: DuckDB's message), "count" (the number of
    statements), "type" (the statement type, e.g. DROP) or "modifying" (the
    INSERT, DELETE or UPDATE found inside it). Parsed on `connection`, which
    the caller has locked down: the module-level duckdb.extract_statements uses
    the default connection, where duckdb 1.5.5 read a file for PRAGMA
    import_database('<dir>') while classifying it.
    """
    import duckdb

    try:
        statements = connection.extract_statements(sql)
    except duckdb.Error as exc:
        return ("parse", clean_error(str(exc)))
    if len(statements) != 1:
        return ("count", str(len(statements)))
    kind = statements[0].type
    if kind != duckdb.StatementType.SELECT:
        return ("type", str(getattr(kind, "name", kind)))
    row = connection.execute("SELECT json_serialize_sql($1::VARCHAR)", [sql]).fetchone()
    tree = json.loads(row[0]) if row else {"error": True}
    if tree.get("error"):
        # Every SELECT tried serialises; one that does not (a MERGE ... RETURNING
        # in a CTE) is not a plain SELECT.
        return ("modifying", "MERGE")
    for node in _node_types(tree):
        if node not in _SELECT_NODES:
            return ("modifying", node.removesuffix("_NODE").removesuffix("_QUERY"))
    return None


def cell(value: Any) -> Any:
    """A JSON-safe cell: dates as ISO text, decimals as floats, NaN as null, the rest as text."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


class _Fail(Exception):
    def __init__(self, kind: str, message: str = "") -> None:
        super().__init__(kind)
        self.kind = kind
        self.message = message


def _expand(column: dict[str, Any]) -> list[Any]:
    if "runs" in column:
        return [value for value, count in column["runs"] for _ in range(count)]
    return list(column["values"])


def _limit_resources(memory_mb: int, seconds: float) -> bool:
    """Cap the address space at its current size plus `memory_mb`, and CPU time.

    The baseline is measured, not assumed: DuckDB and its allocator reserve
    about 1.2 GB of address space at connect (duckdb 2.0.0, Linux x86-64), most
    of it never touched. True when the address-space cap was set.
    """
    try:
        import resource
    except ImportError:  # Windows
        return False
    try:
        used = resource.getrusage(resource.RUSAGE_SELF)
        cpu = int(used.ru_utime + used.ru_stime + seconds) + 2
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    except (ValueError, OSError):
        pass
    try:
        with open("/proc/self/statm", encoding="ascii") as statm:
            pages = int(statm.read().split()[0])
        import os

        base = pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return False  # macOS and others without /proc: RLIMIT_AS is not enforced there anyway
    limit = base + memory_mb * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ValueError, OSError):
        return False
    return True


def run(job: dict[str, Any]) -> dict[str, Any]:
    """Load the tables, run the job's SQL under the limits, return the capped result."""
    import duckdb

    memory_mb = int(job["memory_mb"])
    seconds = float(job["seconds"])
    row_cap = int(job["row_cap"])
    max_chars = int(job["max_chars"])
    max_cell = int(job["max_cell_chars"])
    sql = str(job["sql"])

    # DuckDB's own limit sits under the address-space cap, so a query that
    # outgrows the buffer pool fails inside DuckDB with a clear message first.
    connection = open_sandbox(memory_mb // 2)
    problem = select_problem(connection, sql)
    if problem is not None:
        raise _Fail("statement", ": ".join(problem))
    for statement in job.get("setup", []):
        connection.execute(statement)
    for load in job.get("load", []):
        columns = [_expand(column) for column in load["columns"]]
        loaded = len(columns[0]) if columns else 0
        # In chunks: DuckDB turns each list parameter into one Value per item, and
        # 20 series x 3,000 periods in one INSERT took the process to 269 MB.
        for start in range(0, loaded, _LOAD_CHUNK):
            chunk = [column[start : start + _LOAD_CHUNK] for column in columns]
            connection.execute(load["sql"], chunk)
        del columns
    job.clear()

    timer = threading.Timer(seconds, connection.interrupt)
    timer.daemon = True
    timer.start()
    _limit_resources(memory_mb, seconds)
    try:
        cursor = connection.execute(sql)
        description = cursor.description or []
        names = [str(d[0]) for d in description]
        rows: list[list[Any]] = []
        size = 0
        truncated = False
        while len(rows) <= row_cap:
            batch = cursor.fetchmany(min(100, row_cap + 1 - len(rows)))
            if not batch:
                break
            for raw in batch:
                if len(rows) == row_cap:
                    truncated = True
                    break
                cells = [cell(value) for value in raw]
                for name, value in zip(names, cells, strict=False):
                    if isinstance(value, str) and len(value) > max_cell:
                        raise _Fail("cell_too_large", name)
                size += len(json.dumps(cells)) + 1
                if size > max_chars:
                    raise _Fail("too_large", str(len(rows)))
                rows.append(cells)
            if truncated:
                break
    except duckdb.InterruptException as exc:
        raise _Fail("timeout") from exc
    except duckdb.OutOfMemoryException as exc:
        raise _Fail("memory", clean_error(str(exc))) from exc
    except duckdb.PermissionException as exc:
        raise _Fail("permission", clean_error(str(exc))) from exc
    except duckdb.Error as exc:
        raise _Fail("sql", clean_error(str(exc))) from exc
    finally:
        timer.cancel()
    return {
        "ok": True,
        "columns": names,
        "types": [str(d[1]) for d in description],
        "rows": rows,
        "truncated": truncated,
    }


def main() -> int:
    try:
        job = json.loads(sys.stdin.buffer.read())
        answer = run(job)
    except _Fail as fail:
        answer = {"ok": False, "kind": fail.kind, "message": fail.message}
    except MemoryError:
        answer = {"ok": False, "kind": "memory", "message": ""}
    except Exception as exc:  # noqa: BLE001 - any failure still answers, so the parent can say why
        answer = {
            "ok": False,
            "kind": "internal",
            "message": clean_error(f"{type(exc).__name__}: {exc}"),
        }
    sys.stdout.write(json.dumps(answer))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
