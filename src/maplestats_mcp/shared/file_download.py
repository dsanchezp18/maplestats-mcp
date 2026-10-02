"""Stream a published data file with a hard size cap, a host allow-list and pacing.

`shared/http.py::get_raw` reads the whole response into memory before any
caller can look at its size, and its client does not follow redirects. A
generic file reader needs the opposite on both counts, so this module uses a
module-owned client (`new_client`) and streams:

- the URL and every redirect target must be https and on the caller's
  allow-list of hosts (federal download links answer 302 to a signed Azure
  blob URL, Montreal's to a Google Cloud Storage object, confirmed live
  2026-10-02), so a record that points at, or redirects to, an unexpected
  host is refused before any byte is requested from it;
- a declared Content-Length above the cap is refused without reading the
  body, and a body that grows past the cap without declaring a length is
  aborted mid-stream;
- each hop waits for the token bucket the caller chooses for that host;
- the bytes are cached for a few hours inside a total byte budget (a plain
  TTL cache of 40 MB files would let a few calls hold gigabytes).
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import (
    is_recording,
    is_retryable,
    new_client,
    raise_if_cloudflare_challenge,
)
from maplestats_mcp.shared.rate_limiter import TokenBucket

MAX_REDIRECTS = 4
CACHE_BUDGET_BYTES = 96 * 1024 * 1024
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

_client = new_client(timeout=60.0, follow_redirects=False)


@dataclass
class Downloaded:
    body: bytes
    final_url: str
    content_type: str


HostCheck = Callable[[str], bool]
LimiterFor = Callable[[str], TokenBucket]


def _refuse(url: str, context: str) -> InvalidInput:
    host = urlparse(url).hostname or url
    return InvalidInput(
        f"{context}: {host} is not on this portal's list of data hosts, so the file is not "
        f"downloaded. Open {url} in a browser to get it."
    )


def check_url(url: str, allow_host: HostCheck, context: str) -> None:
    """https and an allowed host, or InvalidInput (nothing is requested)."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise InvalidInput(f"{context}: only https file links are downloaded; got {url!r}.")
    if not allow_host(parsed.hostname):
        raise _refuse(url, context)


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def _fetch_chain(
    url: str,
    *,
    allow_host: HostCheck,
    limiter_for: LimiterFor,
    max_bytes: int,
    timeout: float,
    context: str,
) -> Downloaded:
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        check_url(current, allow_host, context)
        await limiter_for(urlparse(current).hostname or "").acquire()
        async with _client.stream("GET", current, timeout=timeout) as response:
            status = response.status_code
            if status in _REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    raise UpstreamError(f"{context}: {current} redirected without a location.")
                current = urljoin(str(response.url), location)
                continue
            if status >= 400:
                await response.aread()
                raise_if_cloudflare_challenge(response)
                response.raise_for_status()
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise UpstreamError(
                    f"{context}: {current} is {int(declared):,} bytes; this reader stops at "
                    f"{max_bytes:,}. Download it from the portal instead."
                )
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise UpstreamError(
                        f"{context}: {current} is larger than {max_bytes:,} bytes (stopped "
                        "reading at the cap). Download it from the portal instead."
                    )
                chunks.append(chunk)
            return Downloaded(
                body=b"".join(chunks),
                final_url=current,
                content_type=response.headers.get("content-type", ""),
            )
    raise UpstreamError(f"{context}: {url} redirected more than {MAX_REDIRECTS} times.")


async def download(
    url: str,
    *,
    allow_host: HostCheck,
    limiter_for: LimiterFor,
    max_bytes: int,
    context: str,
    timeout: float = 120.0,
) -> Downloaded:
    """GET `url` into memory under the cap, mapping failures to typed errors."""
    check_url(url, allow_host, context)
    try:
        return await _fetch_chain(
            url,
            allow_host=allow_host,
            limiter_for=limiter_for,
            max_bytes=max_bytes,
            timeout=timeout,
            context=context,
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (404, 410):
            raise NotFound(f"{context}: {url} answered HTTP {status}: no file there.") from exc
        raise UpstreamError(f"{context}: {url} returned HTTP {status}.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{context}: {url} did not respond in time ({type(exc).__name__})."
        ) from exc


class _ByteCache:
    """Downloaded bodies, evicted oldest-first once the byte budget is exceeded."""

    def __init__(self, budget: int) -> None:
        self._budget = budget
        self._items: OrderedDict[str, tuple[float, Downloaded]] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}

    def clear(self) -> None:
        self._items.clear()
        self._locks.clear()

    def get(self, key: str) -> Downloaded | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry[0] < time.monotonic():
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return entry[1]

    def put(self, key: str, ttl: float, value: Downloaded) -> None:
        if len(value.body) > self._budget:
            return
        self._items[key] = (time.monotonic() + ttl, value)
        self._items.move_to_end(key)
        while sum(len(v.body) for _, v in self._items.values()) > self._budget:
            self._items.popitem(last=False)

    def lock(self, key: str) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())


_CACHE = _ByteCache(CACHE_BUDGET_BYTES)


def clear_cache() -> None:
    _CACHE.clear()


async def cached_download(
    key: str, ttl: float, fetch: Callable[[], Awaitable[Downloaded]]
) -> tuple[Downloaded, bool]:
    """(download, was_cached). Concurrent calls for one key share a single fetch."""
    if is_recording():
        # reproduce_code records upstream requests; a cache hit would hide them.
        return await fetch(), False
    hit = _CACHE.get(key)
    if hit is not None:
        return hit, True
    async with _CACHE.lock(key):
        hit = _CACHE.get(key)
        if hit is not None:
            return hit, True
        value = await fetch()
        _CACHE.put(key, ttl, value)
        return value, False
