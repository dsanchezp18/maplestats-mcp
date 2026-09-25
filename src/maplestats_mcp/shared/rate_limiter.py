"""Per-source async token bucket, keyed by source name.

One bucket per upstream source (e.g. "statcan-wds") so a slow burst
against one source never throttles calls to an unrelated one.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class TokenBucket:
    rate: float
    capacity: float
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self._tokens = self.capacity
        self._last_refill = time.monotonic()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._last_refill = now

            if self._tokens >= 1:
                self._tokens -= 1
                return

            wait_seconds = (1 - self._tokens) / self.rate

        await asyncio.sleep(wait_seconds)
        await self.acquire()


_limiters: dict[str, TokenBucket] = {}


def get_limiter(source: str, rate: float = 10.0, capacity: float = 10.0) -> TokenBucket:
    """Return the shared TokenBucket for `source`, creating it on first use.

    `rate`/`capacity` only take effect the first time a given `source` key
    is requested — later calls with different values are ignored, matching
    a singleton registry rather than a per-call reconfiguration.
    """
    if source not in _limiters:
        _limiters[source] = TokenBucket(rate=rate, capacity=capacity)
    return _limiters[source]
