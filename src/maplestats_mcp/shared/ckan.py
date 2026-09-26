"""Shared plumbing for any CKAN Action API deployment.

Every Canadian government CKAN portal (federal, provincial, municipal)
runs the same open-source CKAN software, so the HTTP/rate-limit/error/
envelope layer is identical across them by construction — this is CKAN's
own core behavior, not a per-deployment customization, confirmed against
the federal open.canada.ca instance and reused as-is rather than
reimplemented once per portal. What genuinely differs per portal (base
URL, rate limit, cache TTLs, whether tags/groups/bilingual fields are
actually used, dataset field quirks) is recorded in
modules/ckan/constants.PORTALS, verified live against that specific
instance per AGENTS.md.

`CkanConfig` carries the per-portal values `action()` needs; a module's
own client.py calls `action(config, "package_search", params=...)` the
same way modules/statcan/wds/client.py calls its own `_get`/`_post`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, NoReturn

import httpx

from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.rate_limiter import get_limiter


@dataclass(frozen=True)
class CkanConfig:
    """Per-portal configuration for the shared CKAN Action API client.

    `base_url` must end in `action/` (e.g.
    "https://open.canada.ca/data/api/3/action/") so `action()` can build
    a request URL with a plain string concatenation, matching how every
    module in this codebase builds URLs from its own BASE_URL constant.
    """

    source: str
    base_url: str
    rate_limit_per_second: float
    rate_limit_capacity: float
    # Per request attempt; shared/http.py retries up to three times.
    timeout: float = 30.0


def _limiter(config: CkanConfig):
    return get_limiter(
        config.source, rate=config.rate_limit_per_second, capacity=config.rate_limit_capacity
    )


def _error_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
    except ValueError:
        return exc.response.text[:200]
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        detail = err.get("message") or err.get("__type")
        if detail:
            return str(detail)
    return exc.response.text[:200]


def _raise_for_status_error(exc: httpx.HTTPStatusError, context: str) -> NoReturn:
    status = exc.response.status_code
    detail = _error_detail(exc)
    if status == 404:
        raise NotFound(f"{context}: no match found ({detail}).") from exc
    if 400 <= status < 500:
        # Every 4xx other than 404 is treated as a caller-input problem, not
        # just a bare 400 - confirmed live that different CKAN deployments
        # use different status codes for the same kind of mistake (federal
        # returns 400 "Search Query Error" for a malformed fq/sort;
        # Montreal's own deployment returns 409 "Search Error" for the
        # same class of mistake). Narrowing this to status == 400 silently
        # misclassified the 409 case as an UpstreamError.
        raise InvalidInput(f"{context}: rejected the request ({detail}).") from exc
    raise UpstreamError(f"{context} returned HTTP {status}: {detail}") from exc


async def action(config: CkanConfig, method: str, params: dict[str, Any] | None = None) -> Any:
    """Call one CKAN Action API method and unwrap its `{"help","success",
    "result"}` envelope, raising a typed error instead of returning one."""
    context = f"{config.source}:{method}"
    await _limiter(config).acquire()
    url = f"{config.base_url}{method}"
    try:
        data = await api_get(url, params=params, timeout=config.timeout)
    except httpx.HTTPStatusError as exc:
        _raise_for_status_error(exc, context)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{context} did not respond in time (already retried by shared/http.py). Try again shortly."
        ) from exc
    if not isinstance(data, dict) or not data.get("success") or "result" not in data:
        raise UpstreamError(f"{context} returned an unsuccessful envelope: {data!r}")
    return data["result"]


def pick_translated(flat: str | None, translated: dict[str, str] | None, lang: str) -> str:
    """Pick `lang` out of a CKAN `<field>_translated` dict, falling back
    to English, then to the flat (English-default) field. Not every
    portal's multilingual extension is guaranteed to include every
    language key for every record — verify live per portal rather than
    assuming this fallback path is never hit.

    Uses `lang in translated`/`"en" in translated` rather than
    `translated.get(lang) or ...` so a genuinely empty string for the
    requested language (a publisher deliberately left it blank) is
    returned as-is instead of being treated as missing and backfilled
    from English or the flat field — the same class of bug already
    fixed once for `pick_translated_list`, applied here too.
    """
    if translated:
        if lang in translated:
            return translated[lang]
        if "en" in translated:
            return translated["en"]
    return flat or ""


def pick_translated_list(translated: dict[str, list[str]] | None, lang: str) -> list[str]:
    """List-valued counterpart to `pick_translated`.

    Uses `lang in translated` rather than `translated.get(lang) or ...`
    so a genuinely empty list for the requested language is returned
    as-is instead of being treated as missing and backfilled from
    English (a real bug found and fixed in the federal module: an empty
    French keyword list is a valid answer, not an absent translation).
    """
    if not translated:
        return []
    if lang in translated:
        return translated[lang]
    return translated.get("en") or []


def pick_fra(base_value: str, fra_value: str | None, lang: str) -> str:
    """Pick between a flat field and its `_fra`-suffixed counterpart —
    an older CKAN bilingual naming convention some deployments (e.g.
    license_list on the federal portal) use instead of `_translated`.

    Checks `fra_value is not None` rather than truthiness, so a
    genuinely empty French field is returned as-is instead of being
    treated as missing and silently replaced with the English value.
    """
    if lang == "fr" and fra_value is not None:
        return fra_value
    return base_value


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def excerpt(text: str, max_length: int) -> str:
    text = text.strip()
    if max_length <= 0:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "…"


def to_bool(value: object) -> bool:
    """Coerce a CKAN boolean-shaped field to a real `bool`.

    CKAN deployments are inconsistent about whether a boolean field
    arrives as a real JSON boolean or as the literal string "true"/
    "false" (confirmed live on several of this codebase's portal
    modules — e.g. license_list flags, `isopen`, `datastore_active`).
    `bool(value)` is wrong here: `bool("false")` is `True` in Python,
    since any non-empty string is truthy — it silently inverts the
    field whenever a portal sends the string form. Never use bare
    `bool(...)` on a CKAN-sourced field; use this instead.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)
