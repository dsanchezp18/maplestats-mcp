"""Forward the hosted server's tool-call counts to GoatCounter, so they outlive a restart.

/stats (shared/usage.py) lives in memory and starts again on every deploy or
idle sleep, and each host (Azure, Render) only knows its own calls. With
MAPLE_GOATCOUNTER_URL and MAPLE_GOATCOUNTER_TOKEN set, every counted call is
also sent to the project's GoatCounter site as an event named
`mcp/<instance>/<tool>` (`.../error` when it failed), where MAPLE_INSTANCE_NAME
labels the host. The website's page views already go to the same site.

What leaves the server is the event name and the time of the call: a tool name
from the server's own registry (never one a caller typed; unknown names are
"other"), the instance label and the outcome. No arguments, query text or
client addresses, and `no_sessions` tells GoatCounter not to count visitors.

Events are queued in memory and sent in batches of at most 100 (GoatCounter's
limit per request) every FLUSH_SECONDS by one background task. A failed batch
is dropped and logged, never retried in a loop, and the queue is capped, so an
unreachable GoatCounter costs a few kilobytes and one warning, not memory or
latency on tool calls.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from maplestats_mcp import config

logger = logging.getLogger("maplestats_mcp.goatcounter")

FLUSH_SECONDS = 60
# GoatCounter accepts at most 100 hits per /api/v0/count request.
BATCH_SIZE = 100
# About two hours of a busy server; beyond this, new events are dropped.
MAX_QUEUED = 5000


class GoatCounterForwarder:
    """Queue tool-call events and send them to GoatCounter's count API in batches."""

    def __init__(
        self,
        url: str | None,
        token: str | None,
        instance: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url
        self.token = token
        self.instance = instance
        self.transport = transport
        self.queue: list[dict[str, object]] = []
        self.dropped = 0
        self._task: asyncio.Task[None] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.token)

    def add(self, tool: str, ok: bool) -> None:
        """Queue one call; `tool` must already be a registry name or "other"."""
        if not self.enabled:
            return
        if len(self.queue) >= MAX_QUEUED:
            self.dropped += 1
            return
        name = f"mcp/{self.instance}/{tool}" + ("" if ok else "/error")
        self.queue.append(
            {
                "path": name,
                "title": tool,
                "event": True,
                "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        self._start()

    def _start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no loop (a sync caller); the next call from the server starts it
        self._task = loop.create_task(self._run(), name="goatcounter-flush")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_SECONDS)
            await self.flush()

    async def flush(self) -> int:
        """Send what is queued; return how many events GoatCounter accepted."""
        if not self.enabled or not self.queue:
            return 0
        pending, self.queue = self.queue, []
        sent = 0
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            for start in range(0, len(pending), BATCH_SIZE):
                batch = pending[start : start + BATCH_SIZE]
                try:
                    response = await client.post(
                        f"{self.url}/api/v0/count",
                        headers={"Authorization": f"Bearer {self.token}"},
                        json={"no_sessions": True, "hits": batch},
                    )
                except httpx.HTTPError as exc:
                    logger.warning(
                        "GoatCounter unreachable, %d events dropped: %s",
                        len(pending) - sent,
                        type(exc).__name__,
                    )
                    return sent
                if response.status_code >= 300:
                    logger.warning(
                        "GoatCounter answered HTTP %d, %d events dropped",
                        response.status_code,
                        len(batch),
                    )
                    continue
                sent += len(batch)
        if self.dropped:
            logger.warning("GoatCounter queue was full: %d events dropped", self.dropped)
            self.dropped = 0
        return sent


FORWARDER = GoatCounterForwarder(
    config.get_goatcounter_url(), config.get_goatcounter_token(), config.get_instance_name()
)
