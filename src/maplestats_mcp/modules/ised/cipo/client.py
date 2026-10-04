"""HTTP client for the Canadian Trademarks Database (CIPO) search API.

Confirmed live 2026-09-20 against
`https://ised-isde.canada.ca/cipo/trademark-search/srch`. This endpoint
backs the public search UI's own XHR calls and is not documented as a
public API anywhere, but it is a plain unauthenticated JSON POST -- no
session cookie, CSRF token, or API key was required to reproduce it with
a bare `fetch()`, and it stayed reachable outside the browser. Real
quirks found and handled:

1. `searchfield1` accepts only the exact internal codes the search UI's
   dropdown uses (see constants.SEARCH_FIELD_TO_API) -- any other value
   returns HTTP 500 "Internal Server Error" with no detail, not a 400.
2. There is no pagination parameter: `start`/`startRow`/`offset`/`page`/
   `pageNum` were all tried live and every one was silently ignored
   (the response is identical regardless). `maxReturn` only controls how
   many of the top-ranked matches come back in one call; results beyond
   `maxReturn` are not reachable at all through this endpoint.
3. An empty `textfield1` is a deliberate match-all against the entire
   trademark register (confirmed live: >2 million records), the same
   convention this codebase's other search tools already use for an
   empty query.
4. `mediaFileNames` in the response are relative paths (e.g.
   "/media/1137536.png"); this client resolves them to full URLs.
5. Nice classification and CIPO status are not searched through
   `textfield1`: the UI sends them as lists of codes in `nicetextfield1`
   and `cipotextfield1` (its search.js). Checked live 2026-10-03:
   textfield1="45" with the Nice field matched the whole register
   (2,188,587) and nicetextfield1=["45"] matched 97,515; textfield1=
   "REGISTERED" with the status field answered HTTP 500 and
   cipotextfield1=["19"] matched 871,520. A code the UI does not offer
   (Nice "46", status "12") is ignored, giving the whole register or
   nothing, so both are checked here before sending.
6. Number fields given text match nothing ("abc" gave 0 for application,
   registration and international numbers), and an application number
   with thousands separators ("1,244,495") also gave 0, so numbers are
   checked and separators dropped before sending.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from maplestats_mcp.modules.ised.cipo import constants
from maplestats_mcp.modules.ised.cipo.schemas import TrademarkRecord, TrademarkSearchResult
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_post
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


_NUMBER_FIELDS = (
    "application_number",
    "original_application_number",
    "international_registration_number",
)
# Registration numbers carry an optional letter prefix: "TMA700000",
# "TMA 700000", "TMA700,000" and "700000" all matched live (2026-10-03).
_REGISTRATION = re.compile(r"^[A-Z]{0,4}\s*[\d,]+$", re.IGNORECASE)
_SEPARATORS = re.compile(r"[\s,]+")


def _nice_classes(criteria: str, context: str) -> list[str]:
    parts = [p for p in _SEPARATORS.split(criteria) if p]
    if not parts or not all(p.isdigit() for p in parts):
        raise InvalidInput(
            f"{context}: nice_classification criteria must be one or more Nice class "
            f"numbers ({constants.NICE_CLASS_MIN}-{constants.NICE_CLASS_MAX}), "
            f"e.g. '9' or '9, 35'; got {criteria!r}."
        )
    classes = sorted({int(p) for p in parts})
    bad = [c for c in classes if not constants.NICE_CLASS_MIN <= c <= constants.NICE_CLASS_MAX]
    if bad:
        raise InvalidInput(
            f"{context}: Nice classes run from {constants.NICE_CLASS_MIN} to "
            f"{constants.NICE_CLASS_MAX}; got {bad}."
        )
    return [str(c) for c in classes]


def _status_codes(criteria: str, context: str) -> list[str]:
    by_label: dict[str, list[int]] = {}
    for code, label in constants.CIPO_STATUS_CODES.items():
        by_label.setdefault(label.lower(), []).append(code)
    codes: set[int] = set()
    for part in (p.strip() for p in criteria.split(",")):
        if not part:
            continue
        if part.isdigit() and int(part) in constants.CIPO_STATUS_CODES:
            codes.add(int(part))
        elif part.lower() in by_label:
            codes.update(by_label[part.lower()])
        else:
            labels = sorted(set(constants.CIPO_STATUS_CODES.values()))
            raise InvalidInput(
                f"{context}: unknown cipo_status {part!r}; give status names or codes "
                f"separated by commas, from {labels} (codes {sorted(constants.CIPO_STATUS_CODES)})."
            )
    if not codes:
        raise InvalidInput(f"{context}: cipo_status needs at least one status name or code.")
    return [str(c) for c in sorted(codes)]


def _number(search_field: str, criteria: str, context: str) -> str:
    if search_field == "registration_number":
        if not _REGISTRATION.match(criteria):
            raise InvalidInput(
                f"{context}: registration_number must be a number, optionally with its "
                f"prefix (e.g. 'TMA700000' or '700000'); got {criteria!r}."
            )
        return criteria
    digits = _SEPARATORS.sub("", criteria)
    if not digits.isdigit():
        raise InvalidInput(f"{context}: {search_field} must be digits only; got {criteria!r}.")
    return digits


def _trademark_record(doc: dict[str, Any]) -> TrademarkRecord:
    intl_reg_nos = [value for value in doc.get("intlRegNos") or [] if value]
    media_names = doc.get("mediaFileNames") or []
    return TrademarkRecord(
        id=doc.get("id") or "",
        application_number=doc.get("appNo") or "",
        mark_name=doc.get("markName") or "",
        mark_type=doc.get("type") or None,
        status_code=doc.get("statusCode"),
        status_description=doc.get("statusDesc") or None,
        nice_classes=doc.get("niceCodes") or [],
        international_registration_numbers=intl_reg_nos,
        image_urls=[f"{constants.MEDIA_BASE_URL}{name}" for name in media_names],
    )


async def search_trademarks(
    search_field: str, criteria: str, *, max_return: int = constants.MAX_RETURN_DEFAULT
) -> TrademarkSearchResult:
    """Search the Canadian Trademarks Database by one field."""
    api_field = constants.SEARCH_FIELD_TO_API.get(search_field)
    if api_field is None:
        raise InvalidInput(
            f"ised_cipo:search_trademarks: search_field must be one of "
            f"{sorted(constants.SEARCH_FIELD_TO_API)}, got {search_field!r}."
        )
    if max_return < 1 or max_return > constants.MAX_RETURN_MAX:
        raise InvalidInput(
            f"ised_cipo:search_trademarks: max_return must be between 1 and "
            f"{constants.MAX_RETURN_MAX}, got {max_return}."
        )

    context = "ised_cipo:search_trademarks"
    criteria = criteria.strip()
    text = criteria
    nice: list[str] | None = None
    status: list[str] | None = None
    # An empty criteria stays the documented match-all for every field.
    if criteria and search_field == "nice_classification":
        nice, text = _nice_classes(criteria, context), ""
    elif criteria and search_field == "cipo_status":
        status, text = _status_codes(criteria, context), ""
    elif criteria and (search_field in _NUMBER_FIELDS or search_field == "registration_number"):
        text = _number(search_field, criteria, context)
    body = {
        "domIntlFilter": "1",
        "searchfield1": api_field,
        "textfield1": text,
        "display": "list",
        "maxReturn": str(max_return),
        "nicetextfield1": nice,
        "cipotextfield1": status,
    }

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_post(constants.BASE_URL, json_body=body)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = exc.response.text[:200]
            raise UpstreamError(
                f"ised_cipo:search_trademarks returned HTTP {status}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "ised_cipo:search_trademarks did not respond in time "
                "(already retried by shared/http.py). Try again shortly."
            ) from exc

    cache_key = f"ised-cipo:search:{api_field}:{text}:{nice}:{status}:{max_return}"
    payload, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)

    if not isinstance(payload, dict) or "docs" not in payload:
        raise UpstreamError(
            "ised_cipo:search_trademarks: unexpected response shape (missing 'docs')."
        )

    docs = payload.get("docs") or []
    return TrademarkSearchResult(
        records=[_trademark_record(doc) for doc in docs],
        returned_count=len(docs),
        total_matched=payload.get("numFound") or 0,
        search_field=search_field,
        criteria=criteria,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.BASE_URL,
            cached=was_cached,
            schema_name="ised_cipo.TrademarkSearchResult",
            limits=(
                "No pagination beyond max_return -- results ranked past the "
                "requested count are not reachable through this endpoint."
            ),
        ),
    )
