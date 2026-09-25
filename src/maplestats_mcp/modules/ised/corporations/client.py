"""HTTP client for Corporations Canada's federal corporation lookup API.

Confirmed live 2026-09-19 against
`https://ised-isde.canada.ca/cc/lgcy/api/corporations/<id_or_bn9>.json`
(the domain moved from the officially documented `www.ic.gc.ca` host,
which now 301-redirects here). Three real quirks found and handled:

1. A response is always HTTP 200, even for an id/business number with
   no match -- the body becomes a plain two-element list of strings
   (`["could not find corporation X", "... est inconnu."]`) instead of
   the usual `[data_or_null, data_or_null]` shape. `_is_not_found_body`
   below detects this before trying to treat either element as a
   record.
2. The response is a two-element array where exactly one element holds
   the record and the other is `null`, chosen by the `lang` query
   parameter (`eng` -> index 0, `fra` -> index 1) rather than by
   returning one bilingual object -- this client requests the caller's
   language but falls back to whichever slot is non-null if the
   requested one is empty (confirmed live: the API can return the
   matching-language slot as `null` on the same request that returns
   real data in the other slot for at least one legacy record).
3. The address list key is `adresses`, not `addresses` -- a real,
   confirmed-live misspelling in the upstream API's own field name,
   not a mistake in this client.
"""

from __future__ import annotations

from typing import Any

import httpx

from maplestats_mcp.modules.ised.corporations import constants
from maplestats_mcp.modules.ised.corporations.schemas import (
    Activity,
    AnnualReturn,
    CorporationAddress,
    CorporationDetail,
    CorporationName,
    DirectorLimits,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

_LANG_TO_API = {"en": "eng", "fr": "fra"}
_LANG_INDEX = {"en": 0, "fr": 1}


def _is_not_found_body(body: Any) -> bool:
    return isinstance(body, list) and len(body) == 2 and all(isinstance(item, str) for item in body)


def _corp_name(entry: dict[str, Any]) -> CorporationName:
    obj = entry.get("CorporationName") or {}
    return CorporationName(
        name=obj.get("name") or "",
        name_type=obj.get("nameType") or None,
        current=bool(obj.get("current", False)),
        effective_date=obj.get("effectiveDate") or None,
        expiry_date=obj.get("expiryDate") or None,
    )


def _corp_address(entry: dict[str, Any]) -> CorporationAddress:
    obj = entry.get("address") or {}
    return CorporationAddress(
        address_lines=list_or_empty(obj, "addressLine"),
        city=obj.get("city") or None,
        province_code=obj.get("provinceCode") or None,
        postal_code=obj.get("postalCode") or None,
        country_code=obj.get("countryCode") or None,
        current=bool(obj.get("current", False)),
    )


def _annual_return(entry: dict[str, Any]) -> AnnualReturn:
    obj = entry.get("annualReturn") or {}
    return AnnualReturn(
        year_of_filing=obj.get("yearOfFiling") or None,
        annual_meeting_date=obj.get("annualMeetingdate") or None,
    )


def _activity(entry: dict[str, Any]) -> Activity:
    obj = entry.get("activity") or {}
    return Activity(activity=obj.get("activity") or "", activity_date=obj.get("date") or None)


async def get_corporation(id_or_business_number: str, lang: str = "en") -> CorporationDetail:
    """Look up one federal corporation by its corporation id or 9-digit business number."""
    query = id_or_business_number.strip()
    if not query:
        raise InvalidInput("id_or_business_number must not be empty.")
    if not query.isdigit():
        raise InvalidInput(
            f"id_or_business_number must be numeric (a corporation id or 9-digit "
            f"business number), got {id_or_business_number!r}."
        )
    api_lang = _LANG_TO_API.get(lang, "eng")

    async def fetch() -> Any:
        await _LIMITER.acquire()
        url = f"{constants.BASE_URL}/{query}.json"
        try:
            return await api_get(url, params={"lang": api_lang})
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = exc.response.text[:200]
            if status == 404:
                raise NotFound(f"ised_corporations:get_corporation: {detail}") from exc
            if 400 <= status < 500:
                raise InvalidInput(f"ised_corporations:get_corporation: {detail}") from exc
            raise UpstreamError(
                f"ised_corporations:get_corporation returned HTTP {status}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "ised_corporations:get_corporation did not respond in time "
                "(already retried by shared/http.py). Try again shortly."
            ) from exc

    body, was_cached = await cached_fetch(
        f"ised-corporations:get:{query}:{api_lang}", constants.CACHE_TTL_SECONDS, fetch
    )
    if _is_not_found_body(body):
        raise NotFound(
            f"ised_corporations:get_corporation: no match for {id_or_business_number!r}."
        )
    if not isinstance(body, list) or len(body) != 2:
        raise UpstreamError(
            f"ised_corporations:get_corporation: unexpected response shape for {id_or_business_number!r}."
        )
    preferred_index = _LANG_INDEX.get(lang, 0)
    record = body[preferred_index] or body[1 - preferred_index]
    if not isinstance(record, dict):
        raise UpstreamError(
            f"ised_corporations:get_corporation: no record data for {id_or_business_number!r}."
        )

    director_limits_raw = record.get("directorLimits") or {}
    business_numbers = record.get("businessNumbers") or {}
    return CorporationDetail(
        corporation_id=record.get("corporationId") or query,
        act=record.get("act") or None,
        status=record.get("status") or None,
        business_number=business_numbers.get("businessNumber") or None,
        names=[_corp_name(entry) for entry in list_or_empty(record, "corporationNames")],
        addresses=[_corp_address(entry) for entry in list_or_empty(record, "adresses")],
        director_limits=DirectorLimits(
            minimum=director_limits_raw.get("minimum"),
            maximum=director_limits_raw.get("maximum"),
        )
        if director_limits_raw
        else None,
        annual_returns=[_annual_return(entry) for entry in list_or_empty(record, "annualReturns")],
        activities=[_activity(entry) for entry in list_or_empty(record, "activities")],
        landing_page_url=constants.LANDING_PAGE_URL,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}/{query}.json",
            cached=was_cached,
            schema_name="ised_corporations.CorporationDetail",
        ),
    )
