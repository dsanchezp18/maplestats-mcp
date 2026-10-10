"""Retrying GET for modules that own their client (`shared.http.new_client`).

Same retry rules and Retry-After cap as `shared.http.send_with_retry`, with the
three differences reference and surveys need: query `params`, a configurable
set of retryable statuses (IMDB's unknown-survey 500 is a deterministic
answer), and returning the last response when attempts run out instead of
raising, so the caller keeps its own error mapping. StatCan hosts get the
`Connection: close` header so a retry can reach a healthy backend.
"""

from __future__ import annotations

import asyncio

import httpx

from maplestats_mcp.shared.http import (
    _RETRY_AFTER_CAP_SECONDS,
    _RETRYABLE_STATUSES,
    _request_headers,
    is_retryable,
    retry_after_seconds,
)

RETRY_ATTEMPTS = 4
RETRY_BASE_SECONDS = 2.0
RETRY_MAX_SECONDS = _RETRY_AFTER_CAP_SECONDS
RETRY_STATUSES = _RETRYABLE_STATUSES


def retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Seconds to wait before retry number `attempt` (0-based)."""
    retry_after = response.headers.get("retry-after", "") if response is not None else ""
    # The same reading as shared/http.py: whole seconds or an HTTP date.
    asked = retry_after_seconds(retry_after)
    delay = asked if asked is not None else RETRY_BASE_SECONDS * 2**attempt
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
