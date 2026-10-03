"""Readable error text for failures of the portal-family clients (CKAN, Socrata,
Opendatasoft, ArcGIS Hub).

Two things these clients used to get wrong, both seen live 2026-10-03:

- Every `httpx.HTTPError` became "did not respond in time", including a
  connection reset (Oakville's host from some networks) and a 200 answer
  that was not JSON (an HTML error page), which is not a timeout at all.
  `network_error` names the exception type and gives a non-JSON body its
  own message, as an UpstreamError rather than "try again shortly".
- A 404 from Toronto's CKAN or a Socrata domain carries a whole HTML page
  as its body, which ended up pasted into the error message.
  `clean_detail` reduces such a body to its <title> (or its text) and
  caps the length.
"""

from __future__ import annotations

import html
import re

import httpx

from maplestats_mcp.shared.errors import UpstreamError, UpstreamUnavailable

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
DETAIL_MAX_CHARS = 200


def clean_detail(text: str, limit: int = DETAIL_MAX_CHARS) -> str:
    """Plain, short text from an error body that may be an HTML page."""
    stripped = text.strip()
    if "<" in stripped[:200] and ">" in stripped:
        title = _TITLE.search(stripped)
        if title and title.group(1).strip():
            stripped = title.group(1)
        else:
            stripped = _TAG.sub(" ", _SCRIPT.sub(" ", stripped))
        stripped = html.unescape(stripped)
    flat = " ".join(stripped.split())
    if len(flat) > limit:
        return flat[:limit].rstrip() + "…"
    return flat or "no detail in the response"


def network_error(context: str, exc: httpx.HTTPError) -> UpstreamError | UpstreamUnavailable:
    """The typed error for a request that got no usable HTTP answer."""
    if isinstance(exc, httpx.DecodingError):
        return UpstreamError(
            f"{context}: the service answered, but not with JSON (often an HTML error or "
            "maintenance page)."
        )
    kind = type(exc).__name__
    if isinstance(exc, httpx.TimeoutException):
        reason = f"did not respond in time ({kind})"
    else:
        message = str(exc).strip()
        detail = f": {clean_detail(message, 120)}" if message else ", connection reset or closed"
        reason = f"could not be reached ({kind}{detail})"
    return UpstreamUnavailable(
        f"{context} {reason}; already retried by shared/http.py. Try again shortly."
    )
