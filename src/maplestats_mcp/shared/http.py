"""Shared async HTTP GET with retry, used by every module's client.py.

Retries only genuinely transient statuses (429/500/502/503/504) with
exponential backoff. 409 is deliberately excluded — for StatCan's WDS,
409 means "data locked during the 12am-8:30am ET update window," a
scheduled state that retrying blindly will not resolve; callers that
need to interpret 409 specially (see modules/statcan/wds/client.py)
should catch httpx.HTTPStatusError themselves rather than rely on this
layer to retry it away.

`http2=True` below is load-bearing, not an optimization: diagnosed live
against statcan.gc.ca, a plain httpx/httpcore client with the default
`http2=False` sends a TLS ClientHello whose ALPN extension offers only
"http/1.1", and something on StatCan's network path (a WAF/CDN, not
this code) blocks exactly that fingerprint — confirmed by reproducing
the identical hang with a raw `ssl` socket once ALPN was narrowed to
that single value, and confirming it disappears the moment "h2" is
added back to the ALPN list. The connection still negotiates and
transacts over HTTP/1.1 either way; `http2=True` only changes what's
offered during the handshake, not what's actually used. Do not remove
this thinking it's dead weight — it is the fix for real connections to
this project's primary data source silently timing out.
"""

from __future__ import annotations

import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from maplestats_mcp import __version__
from maplestats_mcp.shared.errors import CloudflareChallenge

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
# Built from the package version so the User-Agent upstreams see (and can
# contact us about) never goes stale after a release.
_DEFAULT_HEADERS = {"User-Agent": f"maplestats-mcp/{__version__}"}


@dataclass
class RecordedRequest:
    """One upstream request made while recording (see `recording`)."""

    method: str
    url: str
    body: bytes
    content_type: str
    accept: str = ""
    status: int | None = None
    response_type: str = ""


# reproduce_code runs a tool inside `recording()` to learn the exact
# upstream requests (URL with every query parameter, POST body) instead
# of guessing them from the result's provenance URL, which often omits
# filters. Hooks on every client this module creates feed the list.
_recorded: ContextVar[list[RecordedRequest] | None] = ContextVar(
    "maplestats_recorded", default=None
)
_pending: dict[int, RecordedRequest] = {}


async def _record_request(request: httpx.Request) -> None:
    requests = _recorded.get()
    if requests is None:
        return
    # A streamed request has no readable body (AER's streamed downloads raised
    # RequestNotRead here, 2026-09-25); every body worth replaying is small.
    try:
        body = request.content
    except httpx.RequestNotRead:
        body = b""
    entry = RecordedRequest(
        method=request.method,
        url=str(request.url),
        body=body,
        content_type=request.headers.get("content-type", ""),
        accept=request.headers.get("accept", ""),
    )
    requests.append(entry)
    _pending[id(request)] = entry


async def _record_response(response: httpx.Response) -> None:
    entry = _pending.pop(id(response.request), None)
    if entry is not None:
        entry.status = response.status_code
        entry.response_type = response.headers.get("content-type", "")


_HOOKS = {"request": [_record_request], "response": [_record_response]}


@contextmanager
def recording() -> Iterator[list[RecordedRequest]]:
    """Collect every upstream request made in this context."""
    requests: list[RecordedRequest] = []
    token = _recorded.set(requests)
    try:
        yield requests
    finally:
        _recorded.reset(token)
        # Requests that never got a response (errors) must not linger.
        for key in [k for k, v in _pending.items() if v in requests]:
            _pending.pop(key, None)


def is_recording() -> bool:
    return _recorded.get() is not None


_client = httpx.AsyncClient(timeout=30.0, http2=True, event_hooks=_HOOKS)


def new_client(
    *,
    timeout: float = 30.0,
    http2: bool = True,
    follow_redirects: bool = False,
    verify: ssl.SSLContext | bool = True,
) -> httpx.AsyncClient:
    """A module-owned client, for the few sources the shared singleton cannot serve.

    Use this instead of a bare `httpx.AsyncClient(...)` when a source
    needs its own cookie jar (a session warm-up the shared client must
    not leak into other sources), redirect following, or `http2=False`
    (CRA's registry page, see its client.py), or a `verify` context that
    adds an intermediate certificate a server fails to send (CIPO's
    opic-cipo.ca, see ised/ip_horizons/client.py). It keeps the project's
    identifying User-Agent and the `http2=True` default that StatCan's
    network path requires (see this module's docstring).
    """
    return httpx.AsyncClient(
        timeout=timeout,
        http2=http2,
        follow_redirects=follow_redirects,
        verify=verify,
        headers=_DEFAULT_HEADERS,
        event_hooks=_HOOKS,
    )


# StatCan hosts whose load balancers pin each connection to one backend.
# Probed 2026-09-27 from three GitHub runners and locally: on a reused
# connection geo.statcan.gc.ca answered 500 ten times in a row on one runner
# and 200 ten times on the others, and www12's census REST API answered twice
# and then timed out for the rest of the connection. With a new connection per
# request, failures were independent (geo: 6 of 10 succeeded), so a retry can
# reach a healthy backend instead of repeating the broken one.
_FRESH_CONNECTION_HOSTS = frozenset(
    {"geo.statcan.gc.ca", "www12.statcan.gc.ca", "www150.statcan.gc.ca"}
)


def _request_headers(url: str, headers: dict[str, str] | None) -> dict[str, str]:
    """Identify this client while preserving source-specific overrides.

    Montreal's CKAN edge returns 403 to requests with no User-Agent but
    accepts the same request once the client identifies itself. Keeping this
    in shared HTTP plumbing fixes that portal without changing StatCan's
    required HTTP/2 transport or repeating the header in every source client.
    StatCan hosts also get `Connection: close` (see _FRESH_CONNECTION_HOSTS).
    """
    fresh = {"Connection": "close"} if httpx.URL(url).host in _FRESH_CONNECTION_HOSTS else {}
    return {**_DEFAULT_HEADERS, **fresh, **(headers or {})}


# Public names for sources that keep their own client and retry policy (HEAD,
# range reads, streamed downloads) but should send the same headers and honour
# the same Retry-After as the main HTTP path.
request_headers = _request_headers


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUSES
    # TimeoutException covers connect/read/write/pool timeouts; NetworkError
    # covers connect/read/write/close failures; RemoteProtocolError is a
    # server dropping the connection mid-response -- all transient on a
    # flaky government server, unlike a malformed request.
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError))


def is_cloudflare_challenge(response: httpx.Response) -> bool:
    """True when Cloudflare answered with its managed bot challenge.

    Confirmed live 2026-10-02 for www12.statcan.gc.ca: HTTP 403 with
    `Server: cloudflare`, `Cf-Mitigated: challenge` and a "Just a moment..."
    interstitial for every path. The challenge needs a browser to solve;
    this project does not try to defeat it (no spoofed headers, no
    automation), it only recognises it so a caller gets a clear
    "unavailable" error instead of a misleading 403 or "not found".
    """
    if response.status_code not in (403, 429, 503):
        return False
    if response.headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    return response.status_code == 403 and b"Just a moment" in response.content[:4096]


def raise_if_cloudflare_challenge(response: httpx.Response) -> None:
    if is_cloudflare_challenge(response):
        host = response.request.url.host
        raise CloudflareChallenge(
            f"{host} is behind a Cloudflare bot challenge (HTTP {response.status_code}, "
            "Cf-Mitigated: challenge) that automated clients cannot pass, so this "
            "service is unavailable from MapleStats until StatCan lifts it. MapleStats "
            "does not try to bypass it."
        )


def decode_json(response: httpx.Response, url: str = "") -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise httpx.DecodingError(
            f"Response from {url or response.url} was not valid JSON"
        ) from exc


_RETRY_AFTER_CAP_SECONDS = 30.0
_backoff = wait_exponential(multiplier=1, min=1, max=10)


def _wait_honouring_retry_after(state: RetryCallState) -> float:
    """Exponential backoff, or the server's Retry-After (capped) when it sent one."""
    wait = _backoff(state)
    exc = state.outcome.exception() if state.outcome else None
    if isinstance(exc, httpx.HTTPStatusError):
        header = exc.response.headers.get("retry-after", "")
        if header.isdigit():
            return max(wait, min(float(header), _RETRY_AFTER_CAP_SECONDS))
    return wait


wait_honouring_retry_after = _wait_honouring_retry_after


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(3),
    wait=_wait_honouring_retry_after,
    reraise=True,
)
async def api_get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> Any:
    response = await _client.get(
        url, params=params, headers=_request_headers(url, headers), timeout=timeout
    )
    raise_if_cloudflare_challenge(response)
    response.raise_for_status()
    return decode_json(response, url=url)


_PASSTHROUGH_STATUSES = frozenset({406, 409})


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(3),
    wait=_wait_honouring_retry_after,
    reraise=True,
)
async def get_raw(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    """GET without JSON-decoding — for non-JSON responses (e.g. SDMX-ML/XML).

    Statuses in _PASSTHROUGH_STATUSES (406, 409) are returned as-is,
    unraised — callers need to inspect these themselves (StatCan uses
    409 for its daily lock window and 406 for a rejected parameter
    combination, neither a generic failure). Every other non-2xx status
    still raises via raise_for_status(), so the retry decorator's
    is_retryable check still fires for genuinely transient statuses
    (429/500/502/503/504).
    """
    response = await _client.get(
        url, params=params, headers=_request_headers(url, headers), timeout=timeout
    )
    if response.status_code in _PASSTHROUGH_STATUSES:
        return response
    raise_if_cloudflare_challenge(response)
    response.raise_for_status()
    return response


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(3),
    wait=_wait_honouring_retry_after,
    reraise=True,
)
async def post_form_raw(
    url: str,
    *,
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    """POST form-encoded data without JSON-decoding the response.

    For an endpoint whose response is a non-JSON file download (e.g. a
    CSV export) rather than a JSON API result — `api_post` always
    JSON-decodes and always sends a JSON body, neither of which fits.
    """
    response = await _client.post(
        url, data=data, headers=_request_headers(url, headers), timeout=timeout
    )
    raise_if_cloudflare_challenge(response)
    response.raise_for_status()
    return response


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(3),
    wait=_wait_honouring_retry_after,
    reraise=True,
)
async def api_post(
    url: str,
    *,
    json_body: Any,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> Any:
    response = await _client.post(
        url, json=json_body, headers=_request_headers(url, headers), timeout=timeout
    )
    raise_if_cloudflare_challenge(response)
    response.raise_for_status()
    return decode_json(response, url=url)


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(3),
    wait=_wait_honouring_retry_after,
    reraise=True,
)
async def send_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    """Send one request on a module-owned client (see `new_client`) with the
    shared retry rules, request headers and Cloudflare-challenge check.

    For sources that must keep their own client (HEAD with redirects, cookie
    jars) but should not lose what `api_get` gives every other source:
    retries on 429/5xx and transient network errors with backoff that honours
    a Retry-After header, and `Connection: close` on StatCan hosts. Any other
    status (404 included) is returned for the caller to interpret; only the
    retryable ones raise, once the attempts are used up.
    """
    response = await client.request(
        method, url, headers=_request_headers(url, headers), timeout=timeout
    )
    raise_if_cloudflare_challenge(response)
    if response.status_code in _RETRYABLE_STATUSES:
        response.raise_for_status()
    return response
