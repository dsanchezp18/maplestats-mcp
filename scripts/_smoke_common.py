"""Shared helper for live smoke tests that skip a sustained upstream outage."""

from __future__ import annotations

import re

from maplestats_mcp.shared.errors import UpstreamError, UpstreamUnavailable


def is_upstream_outage(exc: BaseException) -> bool:
    """True for a timeout, a network failure, a Cloudflare challenge or an HTTP 5xx.

    A 4xx or a changed response shape is not an outage: it is a possible
    regression, so the smoke test must still fail on it.
    """
    if isinstance(exc, UpstreamUnavailable):
        return True
    return isinstance(exc, UpstreamError) and re.search(r"HTTP 5\d\d", str(exc)) is not None
