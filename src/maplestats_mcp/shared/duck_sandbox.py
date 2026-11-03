"""Run a caller's SQL in a separate, capped DuckDB process and await it without a thread.

The server keeps the data it fetched; the child (shared/duck_worker.py) gets
the tables and the SQL as JSON on stdin and answers in JSON on stdout. What
the child cannot do to the server, measured on Linux with duckdb 2.0.0
(2026-11-03), where the same queries in-process reached 7-10 GB or had the
server killed:

- grow past its address-space cap (RLIMIT_AS: its size after loading plus
  config.get_query_memory_mb(); not enforced on Windows or macOS, where the
  other limits still hold);
- outlive its deadline: it is killed at `seconds` plus a startup allowance,
  whatever DuckDB is doing, and the event loop waits on its pipes, so no
  worker thread is held past the limit;
- send back more than `max_chars` characters of rows, or one text cell longer
  than `max_cell_chars` (the 500-row cap alone let 5 GB of text through);
- run more than config.get_query_max_concurrent() at once (the rest wait).

The child gets a minimal environment (no tokens, no HOME) and `python -I`, so
neither the working directory nor PYTHON* variables decide what it imports.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import anyio
import anyio.abc

from maplestats_mcp import config
from maplestats_mcp.shared import duck_worker

logger = logging.getLogger("maplestats_mcp.duck_sandbox")

WORKER = "maplestats_mcp.shared.duck_worker"
# Python start, duckdb import and loading the tables: about 0.2 s on Linux
# (2026-11-03); Windows starts processes more slowly.
STARTUP_SECONDS = 1.5
# What the parent keeps of the child's stderr, for the log only.
_STDERR_BYTES = 8_192
# Environment variables passed on: what Python and the OS need, nothing else.
_ENV_KEYS = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG")

_slots: anyio.Semaphore | None = None


class SandboxError(Exception):
    """The child did not return rows: `kind` says why, `detail` is DuckDB's cleaned message.

    kind: statement, parse, timeout, memory, permission, sql, too_large,
    cell_too_large, crashed, internal.
    """

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True)
class Table:
    """One table for the child to create and fill: column names and DuckDB types, and values."""

    name: str
    columns: Sequence[tuple[str, str]]
    values: Sequence[Sequence[Any]]  # one sequence per column


@dataclass(frozen=True)
class Result:
    columns: list[str]
    types: list[str]
    rows: list[list[str | int | float | bool | None]]
    truncated: bool


def select_problem(sql: str) -> tuple[str, str] | None:
    """duck_worker.select_problem on a fresh locked connection in this process.

    Parsing only, bounded by DuckDB's expression depth (1000) and the caller's
    SQL length cap; it lets a bad query fail before any data are fetched. The
    child checks again on its own connection.
    """
    connection = duck_worker.open_sandbox(16)
    try:
        return duck_worker.select_problem(connection, sql)
    finally:
        connection.close()


def _encode(values: Sequence[Any]) -> dict[str, Any]:
    """A column as JSON: run-length encoded when it repeats (a series title on every row)."""
    runs: list[list[Any]] = []
    for value in values:
        if runs and runs[-1][0] == value and type(runs[-1][0]) is type(value):
            runs[-1][1] += 1
        else:
            runs.append([value, 1])
    if len(runs) * 2 <= len(values):
        return {"runs": runs}
    return {"values": list(values)}


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serialisable")


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _job(
    tables: Sequence[Table],
    sql: str,
    *,
    seconds: float,
    row_cap: int,
    max_chars: int,
    max_cell_chars: int,
    memory_mb: int,
) -> bytes:
    setup: list[str] = []
    load: list[dict[str, Any]] = []
    for table in tables:
        schema = ", ".join(f"{_quote(name)} {kind}" for name, kind in table.columns)
        setup.append(f"CREATE TABLE {_quote(table.name)} ({schema})")
        # One INSERT of unnested column lists: executemany took 53 s for 30,000
        # rows (duckdb 2.0.0, 2026-11-03), this takes 0.1 s. Dates arrive as ISO
        # text and are cast by the ::DATE[] / ::TIMESTAMP[] list cast.
        unnest = ", ".join(
            f"unnest(${i + 1}::{kind}[])" for i, (_, kind) in enumerate(table.columns)
        )
        load.append(
            {
                "sql": f"INSERT INTO {_quote(table.name)} SELECT {unnest}",
                "columns": [_encode(column) for column in table.values],
            }
        )
    job = {
        "sql": sql,
        "setup": setup,
        "load": load,
        "seconds": seconds,
        "row_cap": row_cap,
        "max_chars": max_chars,
        "max_cell_chars": max_cell_chars,
        "memory_mb": memory_mb,
    }
    return json.dumps(job, default=_json_default).encode("utf-8")


def _child_env() -> dict[str, str]:
    env = {key: os.environ[key] for key in _ENV_KEYS if key in os.environ}
    # glibc gives each thread a 64 MB arena of address space; two are enough
    # and keep the address-space cap about memory actually used.
    env["MALLOC_ARENA_MAX"] = "2"
    return env


def _semaphore() -> anyio.Semaphore:
    global _slots
    if _slots is None:
        _slots = anyio.Semaphore(config.get_query_max_concurrent())
    return _slots


async def run_query(
    tables: Sequence[Table],
    sql: str,
    *,
    seconds: float,
    row_cap: int,
    max_chars: int,
    max_cell_chars: int,
    memory_mb: int | None = None,
) -> Result:
    """Run `sql` over `tables` in a child process; SandboxError when it returns no rows."""
    payload = _job(
        tables,
        sql,
        seconds=seconds,
        row_cap=row_cap,
        max_chars=max_chars,
        max_cell_chars=max_cell_chars,
        memory_mb=memory_mb or config.get_query_memory_mb(),
    )
    # The answer is JSON with ASCII escapes, counted in the child as it is
    # written; past this the child is misbehaving and is killed.
    max_bytes = max_chars + 64_000
    async with _semaphore():
        answer = await _spawn(payload, seconds + STARTUP_SECONDS, max_bytes)
    if not answer.get("ok"):
        raise SandboxError(str(answer.get("kind", "internal")), str(answer.get("message", "")))
    return Result(
        columns=[str(c) for c in answer["columns"]],
        types=[str(t) for t in answer["types"]],
        rows=answer["rows"],
        truncated=bool(answer["truncated"]),
    )


async def _spawn(payload: bytes, deadline: float, max_bytes: int) -> dict[str, Any]:
    process = await anyio.open_process(
        [sys.executable, "-I", "-m", WORKER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_child_env(),
    )
    out = bytearray()
    err = bytearray()
    too_large = False

    async def feed() -> None:
        assert process.stdin is not None
        try:
            await process.stdin.send(payload)
            await process.stdin.aclose()
        except (anyio.BrokenResourceError, anyio.ClosedResourceError, OSError):
            pass  # the child exited early; its answer (or exit code) says why

    async def drain(
        stream: anyio.abc.ByteReceiveStream, into: bytearray, cap: int, stop: bool
    ) -> None:
        nonlocal too_large
        try:
            async for chunk in stream:
                if len(into) + len(chunk) > cap:
                    if stop:
                        too_large = True
                        tg.cancel_scope.cancel()
                        return
                    into.extend(chunk[: max(0, cap - len(into))])
                    continue
                into.extend(chunk)
        except (anyio.BrokenResourceError, anyio.ClosedResourceError, OSError):
            pass

    try:
        with anyio.move_on_after(deadline) as timer:
            async with anyio.create_task_group() as tg:
                assert process.stdout is not None and process.stderr is not None
                tg.start_soon(feed)
                tg.start_soon(drain, process.stdout, out, max_bytes, True)
                tg.start_soon(drain, process.stderr, err, _STDERR_BYTES, False)
            if not too_large:
                await process.wait()
    finally:
        if process.returncode is None:
            process.kill()
        with anyio.CancelScope(shield=True):
            await process.wait()
            await process.aclose()
    if too_large:
        raise SandboxError("too_large")
    if timer.cancelled_caught:
        raise SandboxError("timeout")
    try:
        answer = json.loads(out)
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        # Killed by the kernel (out of memory), a signal, or a crash in DuckDB.
        logger.warning(
            "DuckDB query process exited with %s and no answer: %s",
            process.returncode,
            bytes(err[-2000:]).decode("utf-8", "replace"),
        )
        raise SandboxError("crashed", f"exit code {process.returncode}")
    return answer  # pyright: ignore[reportUnknownVariableType]
