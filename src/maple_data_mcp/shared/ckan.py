"""Shared plumbing for any CKAN Action API deployment.

Every Canadian government CKAN portal (federal, provincial, municipal)
runs the same open-source CKAN software, so the HTTP/rate-limit/error/
envelope layer is identical across them by construction — this is CKAN's
own core behavior, not a per-deployment customization, confirmed against
the federal open.canada.ca instance and reused as-is rather than
reimplemented once per portal. What genuinely differs per portal (base
URL, rate limit, cache TTLs, whether tags/groups/bilingual fields are
actually used, dataset field quirks) stays in each modules/ckan_<portal>/
package, verified live against that specific instance per AGENTS.md.

`CkanConfig` carries the per-portal values `action()` needs; a module's
own client.py calls `action(config, "package_search", params=...)` the
same way modules/statcan/wds/client.py calls its own `_get`/`_post`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, NoReturn

import httpx

from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import api_get
from maple_data_mcp.shared.rate_limiter import get_limiter


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
    if status == 400:
        raise InvalidInput(f"{context}: rejected the request ({detail}).") from exc
    raise UpstreamError(f"{context} returned HTTP {status}: {detail}") from exc


async def action(config: CkanConfig, method: str, params: dict[str, Any] | None = None) -> Any:
    """Call one CKAN Action API method and unwrap its `{"help","success",
    "result"}` envelope, raising a typed error instead of returning one."""
    context = f"{config.source}:{method}"
    await _limiter(config).acquire()
    url = f"{config.base_url}{method}"
    try:
        data = await api_get(url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status_error(exc, context)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{context} did not respond in time (already retried by shared/http.py). Try again shortly."
        ) from exc
    if not isinstance(data, dict) or not data.get("success"):
        raise UpstreamError(f"{context} returned an unsuccessful envelope: {data!r}")
    return data["result"]


def pick_translated(flat: str | None, translated: dict[str, str] | None, lang: str) -> str:
    """Pick `lang` out of a CKAN `<field>_translated` dict, falling back
    to English, then to the flat (English-default) field. Not every
    portal's multilingual extension is guaranteed to include every
    language key for every record — verify live per portal rather than
    assuming this fallback path is never hit."""
    if translated:
        picked = translated.get(lang) or translated.get("en")
        if picked:
            return picked
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
    license_list on the federal portal) use instead of `_translated`."""
    if lang == "fr" and fra_value:
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
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "…"
