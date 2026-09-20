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
"""

from __future__ import annotations

from typing import Any

import httpx

from maple_data_mcp.modules.ised.cipo import constants
from maple_data_mcp.modules.ised.cipo.schemas import TrademarkRecord, TrademarkSearchResult
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import api_post
from maple_data_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


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

    criteria = criteria.strip()
    body = {
        "domIntlFilter": "1",
        "searchfield1": api_field,
        "textfield1": criteria,
        "display": "list",
        "maxReturn": str(max_return),
        "nicetextfield1": None,
        "cipotextfield1": None,
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

    cache_key = f"ised-cipo:search:{api_field}:{criteria}:{max_return}"
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
