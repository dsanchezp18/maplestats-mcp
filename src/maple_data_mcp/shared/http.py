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

from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_DEFAULT_HEADERS = {"User-Agent": "maple-data-mcp/0.1"}
_client = httpx.AsyncClient(timeout=30.0, http2=True)


def new_client(
    *, timeout: float = 30.0, http2: bool = True, follow_redirects: bool = False
) -> httpx.AsyncClient:
    """A module-owned client, for the few sources the shared singleton cannot serve.

    Use this instead of a bare `httpx.AsyncClient(...)` when a source
    needs its own cookie jar (a session warm-up the shared client must
    not leak into other sources), redirect following, or `http2=False`
    (CRA's registry page, see its client.py). It keeps the project's
    identifying User-Agent and the `http2=True` default that StatCan's
    network path requires (see this module's docstring).
    """
    return httpx.AsyncClient(
        timeout=timeout,
        http2=http2,
        follow_redirects=follow_redirects,
        headers=_DEFAULT_HEADERS,
    )


def _request_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Identify this client while preserving source-specific overrides.

    Montreal's CKAN edge returns 403 to requests with no User-Agent but
    accepts the same request once the client identifies itself. Keeping this
    in shared HTTP plumbing fixes that portal without changing StatCan's
    required HTTP/2 transport or repeating the header in every source client.
    """
    return {**_DEFAULT_HEADERS, **(headers or {})}


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUSES
    # TimeoutException covers connect/read/write/pool timeouts; NetworkError
    # covers connect/read/write/close failures; RemoteProtocolError is a
    # server dropping the connection mid-response -- all transient on a
    # flaky government server, unlike a malformed request.
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError))


def decode_json(response: httpx.Response, url: str = "") -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise httpx.DecodingError(
            f"Response from {url or response.url} was not valid JSON"
        ) from exc


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
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
        url, params=params, headers=_request_headers(headers), timeout=timeout
    )
    response.raise_for_status()
    return decode_json(response, url=url)


_PASSTHROUGH_STATUSES = frozenset({406, 409})


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
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
        url, params=params, headers=_request_headers(headers), timeout=timeout
    )
    if response.status_code in _PASSTHROUGH_STATUSES:
        return response
    response.raise_for_status()
    return response


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
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
        url, data=data, headers=_request_headers(headers), timeout=timeout
    )
    response.raise_for_status()
    return response


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
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
        url, json=json_body, headers=_request_headers(headers), timeout=timeout
    )
    response.raise_for_status()
    return decode_json(response, url=url)
