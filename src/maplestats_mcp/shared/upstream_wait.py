"""How much of a tool call is spent waiting on publishers, for ToolTimeoutMiddleware.

A deadline reached while a request is pending, or soon after one ended (a retry's
backoff or a Retry-After wait sits between attempts), is the source's slowness; a
deadline long after the last request is the server's own work, which a retry would
not fix. BreakerClient.send and TokenBucket.acquire report here.
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass, field

# Longest wait between attempts: http.py honours Retry-After up to 30 s and backs
# off at most 10 s; a little more covers the rate limiter's sleeps.
RECENT_SECONDS = 35.0


@dataclass
class UpstreamWait:
    in_flight: int = 0
    last_end: float | None = field(default=None)

    def waiting(self, now: float | None = None) -> bool:
        if self.in_flight > 0:
            return True
        if self.last_end is None:
            return False
        return (now if now is not None else time.monotonic()) - self.last_end <= RECENT_SECONDS


# Set once per tool call by the outermost ToolTimeoutMiddleware; nested calls
# (call_tool runs its target through the middleware again) share it, and child
# tasks inherit it.
current: ContextVar[UpstreamWait | None] = ContextVar("maplestats_upstream_wait", default=None)


def track(delta: int) -> None:
    state = current.get()
    if state is None:
        return
    state.in_flight += delta
    if delta < 0:
        state.last_end = time.monotonic()
