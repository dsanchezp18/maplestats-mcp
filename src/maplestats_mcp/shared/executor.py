"""A bounded thread pool for CPU-bound file parsing, with a time budget.

Parsing an uploaded Excel or CSV file used to run through
`asyncio.to_thread`, which shares the event loop's default executor with
DNS lookups (`getaddrinfo`). A few slow parses could fill that executor
and stall every outgoing request on the server, and the tool timeout
could not stop them: cancelling the awaiting coroutine leaves the thread
running. This module gives parsing its own small pool
(MAPLE_PARSE_WORKERS, default 4) so it never starves name resolution,
and a wall-clock budget (MAPLE_PARSE_TIMEOUT_SECONDS, default 60):

- the awaiting call gives up at the deadline and raises UpstreamError;
- parsers that loop over rows call `check_deadline()` so the worker
  thread itself stops soon after, freeing its slot for the next call.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from maplestats_mcp import config
from maplestats_mcp.shared.errors import UpstreamError

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()
_local = threading.local()


class ParseBudgetExceeded(UpstreamError):
    """A file took longer to parse than the configured budget allows."""


def get_executor() -> ThreadPoolExecutor:
    """The process-wide parsing pool, created on first use."""
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=config.get_parse_workers(), thread_name_prefix="maple-parse"
            )
        return _executor


def check_deadline() -> None:
    """Raise ParseBudgetExceeded once the current parse is past its deadline.

    Cheap enough to call every few hundred rows. A no-op outside run_parse
    (tests and scripts calling a parser directly have no deadline).
    """
    deadline = getattr(_local, "deadline", None)
    if deadline is not None and time.monotonic() > deadline:
        raise ParseBudgetExceeded("file parsing ran past its time budget")


def _run_with_deadline[T](deadline: float, func: Callable[[], T]) -> T:
    _local.deadline = deadline
    try:
        return func()
    finally:
        _local.deadline = None


async def run_in_pool[**P, T](
    func: Callable[P, T],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """Run blocking work in the parsing pool with no time budget.

    For work that is legitimately long and bounded some other way (unpacking
    a cached archive to disk, converting it to Parquet, tabulating
    microdata under its own caps): it still stays off the default executor
    that DNS lookups need, but is not cut off at the parse budget.
    """
    context = contextvars.copy_context()
    call = functools.partial(context.run, func, *args, **kwargs)
    return await asyncio.get_running_loop().run_in_executor(get_executor(), call)


async def run_parse[**P, T](
    func: Callable[P, T],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """Run a blocking parser in the parsing pool within the time budget.

    The budget covers waiting for a free worker as well as the parse, so a
    pool saturated by pathological files fails new calls with a clear
    message instead of queueing them without bound.
    """
    budget = config.get_parse_timeout_seconds()
    deadline = time.monotonic() + budget
    # Copy contextvars the way asyncio.to_thread does, so code that reads
    # them inside the parser behaves the same.
    context = contextvars.copy_context()
    call = functools.partial(context.run, func, *args, **kwargs)
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(
        get_executor(), functools.partial(_run_with_deadline, deadline, call)
    )
    try:
        return await asyncio.wait_for(future, timeout=budget)
    except TimeoutError as exc:
        name = getattr(func, "__name__", "parser")
        raise ParseBudgetExceeded(
            f"Parsing the file ({name}) took longer than {budget:.0f} s and was stopped; "
            "the file is too large or unusually shaped. Ask for one sheet or fewer rows."
        ) from exc
