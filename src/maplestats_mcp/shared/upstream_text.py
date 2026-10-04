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
from maplestats_mcp.shared.fr_typography import call_error

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
DETAIL_MAX_CHARS = 200
_NO_DETAIL = "no detail in the response"


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
    return flat or _NO_DETAIL


_OUTAGE_MARKERS = (
    "unable to obtain connection",
    "hikaripool",
    "sessions_per_user",
    "ora-0",
    "too many connections",
    "connection pool",
)


def is_backend_outage(detail: str) -> bool:
    """True when an error text describes the server's own database or pool failing.

    Some GeoServer and ArcGIS deployments answer such a failure with a 4xx;
    shared/wfs.py and shared/arcgis.py read it as the service being unavailable.
    """
    text = detail.lower()
    return any(marker in text for marker in _OUTAGE_MARKERS)


def network_error(context: str, exc: httpx.HTTPError) -> UpstreamError | UpstreamUnavailable:
    """The typed error for a request that got no usable HTTP answer."""
    if isinstance(exc, httpx.DecodingError):
        # shared/http.py's decode_json keeps the start of the body on the error.
        start = clean_detail(getattr(exc, "body_start", ""), 120)
        seen = "" if start == _NO_DETAIL else f" (it starts: {start})"
        seen_fr = "" if start == _NO_DETAIL else f" (début : {start})"
        return call_error(
            UpstreamError,
            f"{context}: the service answered, but did not return JSON{seen}; often an HTML "
            "error or maintenance page.",
            f"{context} : le service a répondu, mais pas en JSON{seen_fr} ; c'est souvent une "
            "page d'erreur ou de maintenance HTML.",
        )
    kind = type(exc).__name__
    if isinstance(exc, httpx.TimeoutException):
        reason = f"did not respond in time ({kind})"
        reason_fr = f"n'a pas répondu à temps ({kind})"
    else:
        message = str(exc).strip()
        detail = f": {clean_detail(message, 120)}" if message else ", connection reset or closed"
        detail_fr = (
            f" : {clean_detail(message, 120)}" if message else ", connexion réinitialisée ou fermée"
        )
        reason = f"could not be reached ({kind}{detail})"
        reason_fr = f"est injoignable ({kind}{detail_fr})"
    return call_error(
        UpstreamUnavailable,
        f"{context} {reason}; already retried by shared/http.py. Try again shortly.",
        f"{context} {reason_fr} ; shared/http.py a déjà réessayé. Réessayez sous peu.",
    )
