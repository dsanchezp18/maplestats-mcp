"""Client for NRCan's Geolocator and geographical names APIs."""

from __future__ import annotations

from typing import Any

import httpx

from maple_data_mcp.modules.nrcan_geo import constants
from maple_data_mcp.modules.nrcan_geo.schemas import (
    Location,
    LocationResult,
    PlaceName,
    PlaceNameResult,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import api_get
from maple_data_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


async def _get(url: str, params: dict[str, Any], ttl: int) -> tuple[Any, bool]:
    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, params=params)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (400, 404):
                # Geonames answers a malformed parameter with a Tomcat 404 page.
                raise InvalidInput(f"nrcan_geo: {url} rejected the request ({status}).") from exc
            raise UpstreamError(f"nrcan_geo: {url} returned HTTP {status}.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"nrcan_geo: {url} did not respond in time.") from exc

    return await cached_fetch(f"nrcan-geo:{url}:{sorted(params.items())}", ttl, fetch)


def _check_limit(limit: int) -> None:
    if limit < 1 or limit > constants.LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.LIMIT_MAX}, got {limit}.")


async def locate(
    query: str, *, limit: int = constants.LIMIT_DEFAULT, lang: str = "en"
) -> LocationResult:
    if not query.strip():
        raise InvalidInput("query must not be empty.")
    _check_limit(limit)
    raw, cached = await _get(
        constants.GEOLOCATOR_URL,
        {"q": query.strip(), "lang": lang},
        constants.CACHE_TTL_LOOKUP_SECONDS,
    )
    if not isinstance(raw, list):
        raise UpstreamError("nrcan_geo: the Geolocator did not return a list.")
    locations = [
        Location(
            name=item.get("name") or "",
            province=item.get("province"),
            category=item.get("category"),
            latitude=item["lat"],
            longitude=item["lng"],
            bbox=item.get("bbox"),
            source=item.get("key"),
        )
        for item in raw
        if item.get("lat") is not None and item.get("lng") is not None
    ][:limit]
    return LocationResult(
        query=query,
        locations=locations,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.GEOLOCATOR_URL,
            cached=cached,
            schema_name="nrcan_geo.LocationResult",
        ),
    )


async def _concise_terms(lang: str) -> dict[str, str]:
    url = constants.GEONAMES_ROOT.format(lang=lang) + "codes/concise.json"
    raw, _ = await _get(url, {}, constants.CACHE_TTL_CODES_SECONDS)
    return {d["code"]: d.get("term") or d["code"] for d in raw.get("definitions") or []}


def _province_code(value: str) -> str:
    value = value.strip().upper()
    if value.isdigit():
        return value
    code = constants.PROVINCE_CODES.get(value)
    if code is None:
        raise InvalidInput(
            f"province must be an abbreviation like 'AB' or an SGC code like '48', got {value!r}."
        )
    return code


async def search_names(
    query: str | None = None,
    *,
    province: str | None = None,
    feature_type: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    bbox: list[float] | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> PlaceNameResult:
    _check_limit(limit)
    params: dict[str, Any] = {"num": limit}
    if query and query.strip():
        params["q"] = query.strip()
    if province:
        params["province"] = _province_code(province)
    if feature_type:
        params["concise"] = feature_type.strip().upper()
    if (latitude is None) != (longitude is None):
        raise InvalidInput("latitude and longitude must be given together.")
    if latitude is not None and longitude is not None:
        radius = radius_km or 10
        if not 0 < radius <= constants.RADIUS_MAX_KM:
            raise InvalidInput(f"radius_km must be between 0 and {constants.RADIUS_MAX_KM}.")
        params.update(lat=latitude, lon=longitude, radius=radius)
    if bbox is not None:
        if len(bbox) != 4:
            raise InvalidInput("bbox must be [west, south, east, north].")
        params["bbox"] = ",".join(str(v) for v in bbox)
    if len(params) == 1:
        raise InvalidInput("Give a query, a province or feature type, a point, or a bbox.")

    url = constants.GEONAMES_ROOT.format(lang=lang) + "geonames.json"
    raw, cached = await _get(url, params, constants.CACHE_TTL_LOOKUP_SECONDS)
    terms = await _concise_terms(lang)
    names = [
        PlaceName(
            id=item["id"],
            name=item.get("name") or "",
            feature_type=terms.get((item.get("concise") or {}).get("code") or ""),
            status=(item.get("status") or {}).get("code"),
            province=(item.get("province") or {}).get("code"),
            latitude=item.get("latitude"),
            longitude=item.get("longitude"),
            location=item.get("location") or None,
            map_sheets=list(item.get("map") or []),
            decision_date=item.get("decision"),
        )
        for item in raw.get("items") or []
    ]
    return PlaceNameResult(
        names=names,
        returned_count=len(names),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="nrcan_geo.PlaceNameResult",
        ),
    )
