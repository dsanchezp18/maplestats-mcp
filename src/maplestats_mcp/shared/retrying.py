"""Retrying GET for modules that own their client (`shared.http.new_client`).

`shared.http.api_get`/`get_raw` retry transient failures, but a module with
its own cookie jar or redirect handling (statcan reference, surveys) calls
its client directly and used to skip that layer. This helper gives them the
same rules plus one the shared layer lacks: a 429/503 `Retry-After` header is
honoured (capped), and StatCan hosts get the `Connection: close` header that
`shared.http` adds so a retry can land on a healthy backend.
"""

from __future__ import annotations

import asyncio

import httpx

from maplestats_mcp.shared.http import _request_headers, is_retryable

RETRY_ATTEMPTS = 4
RETRY_BASE_SECONDS = 2.0
RETRY_MAX_SECONDS = 30.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Seconds to wait before retry number `attempt` (0-based)."""
    retry_after = response.headers.get("retry-after", "") if response is not None else ""
    delay = float(retry_after) if retry_after.isdigit() else RETRY_BASE_SECONDS * 2**attempt
    return min(delay, RETRY_MAX_SECONDS)


async def get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str] | None = None,
    retry_statuses: frozenset[int] = RETRY_STATUSES,
) -> httpx.Response:
    """GET with retries on 429/5xx statuses and transient network errors.

    `retry_statuses` lets a caller exclude a status that is a deterministic
    answer on its host (IMDB's unknown-survey 500). Returns the last response even when it is still a retryable status (the
    caller decides what to raise); re-raises the last network error.
    """
    headers = _request_headers(url, None)
    for attempt in range(RETRY_ATTEMPTS):
        last = attempt == RETRY_ATTEMPTS - 1
        try:
            response = await client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            if last or not is_retryable(exc):
                raise
            await asyncio.sleep(retry_delay(None, attempt))
            continue
        if last or response.status_code not in retry_statuses:
            return response
        await asyncio.sleep(retry_delay(response, attempt))
    raise AssertionError("unreachable")
