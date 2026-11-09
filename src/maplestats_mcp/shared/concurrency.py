"""Running a tool's independent upstream requests at the same time."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any


async def gather_or_cancel(*steps: Awaitable[Any]) -> list[Any]:
    """Run steps concurrently and return their results in order.

    When one raises, the others are cancelled before the error propagates.
    asyncio.gather alone leaves them running: each would still wait for its
    turn at a source's rate limit to make a request whose answer nobody reads.
    """
    tasks = [asyncio.ensure_future(step) for step in steps]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
