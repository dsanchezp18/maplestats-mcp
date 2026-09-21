"""HTTP client for the 2016 Census Profile Web Data Service.

Confirmed live 2026-09-21. Both endpoints return the same
column-oriented shape: `{"COLUMNS": [...], "DATA": [[...], ...]}`
(row values in the same order as COLUMNS, not an array of objects) --
this client zips each row against COLUMNS into a dict before mapping
named fields, rather than assuming a fixed column order.
"""

from __future__ import annotations

from typing import Any

import httpx

from maple_data_mcp.modules.statcan.census_profile_2016 import constants
from maple_data_mcp.modules.statcan.census_profile_2016.schemas import (
    Census2016DataResult,
    Census2016Geography,
    Census2016GeographyList,
    Census2016Value,
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


def _rows_as_dicts(payload: Any, context: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or "COLUMNS" not in payload or "DATA" not in payload:
        raise UpstreamError(f"{context}: unexpected response shape (missing COLUMNS/DATA).")
    columns = payload["COLUMNS"]
    return [dict(zip(columns, row, strict=False)) for row in payload["DATA"]]


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def list_geographies(
    level: str, *, province_territory: str = "all", lang: str = "en"
) -> Census2016GeographyList:
    """List 2016 Census geographies (with their DGUIDs) for one level."""
    geo_code = constants.GEOGRAPHY_LEVELS.get(level)
    if geo_code is None:
        raise InvalidInput(
            f"statcan_census_profile_2016:list_geographies: level must be one of "
            f"{sorted(constants.GEOGRAPHY_LEVELS)}, got {level!r}."
        )
    prov_code = constants.PROVINCE_TERRITORY_CODES.get(province_territory)
    if prov_code is None:
        raise InvalidInput(
            f"statcan_census_profile_2016:list_geographies: province_territory must be one of "
            f"{sorted(constants.PROVINCE_TERRITORY_CODES)}, got {province_territory!r}."
        )
    lang_code = constants.LANG_TO_CODE.get(lang, "E")
    url = f"{constants.BASE_URL}/CR2016Geo.json"
    params = {"lang": lang_code, "geos": geo_code, "cpt": prov_code}

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, params=params)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamError(
                f"statcan_census_profile_2016:list_geographies returned HTTP {status}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "statcan_census_profile_2016:list_geographies did not respond in time. "
                "Try again shortly."
            ) from exc

    cache_key = f"statcan-census-profile-2016:geo:{geo_code}:{prov_code}:{lang_code}"
    payload, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)
    rows = _rows_as_dicts(payload, "statcan_census_profile_2016:list_geographies")

    geographies = [
        Census2016Geography(
            geo_uid=row.get("GEO_UID") or "",
            province_territory_code=row.get("PROV_TERR_ID_CODE"),
            province_territory_name=row.get("PROV_TERR_NAME_NOM"),
            geo_id=row.get("GEO_ID_CODE"),
            geo_name=row.get("GEO_NAME_NOM") or "",
            geo_type=row.get("GEO_TYPE"),
            non_response_rate_short_form=_to_float(row.get("GEO_GNR_SF")),
            non_response_rate_long_form=_to_float(row.get("GEO_GNR_LF")),
            data_quality_flag=row.get("GEO_DQ"),
        )
        for row in rows
    ]
    return Census2016GeographyList(
        level=level,
        geographies=geographies,
        returned_count=len(geographies),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_census_profile_2016.Census2016GeographyList",
        ),
    )


async def get_data(
    dguid: str,
    *,
    topic: str = "all_topics",
    statistic: str = "counts",
    include_notes: bool = False,
    lang: str = "en",
) -> Census2016DataResult:
    """Fetch 2016 Census Profile data for one geography (by DGUID)."""
    if not dguid.strip():
        raise InvalidInput("statcan_census_profile_2016:get_data: dguid must not be empty.")
    topic_code = constants.TOPICS.get(topic)
    if topic_code is None:
        raise InvalidInput(
            f"statcan_census_profile_2016:get_data: topic must be one of "
            f"{sorted(constants.TOPICS)}, got {topic!r}."
        )
    stat_code = constants.STATISTIC_TO_CODE.get(statistic)
    if stat_code is None:
        raise InvalidInput(
            f"statcan_census_profile_2016:get_data: statistic must be one of "
            f"{sorted(constants.STATISTIC_TO_CODE)}, got {statistic!r}."
        )
    lang_code = constants.LANG_TO_CODE.get(lang, "E")
    url = f"{constants.BASE_URL}/CPR2016.json"
    params = {
        "lang": lang_code,
        "dguid": dguid.strip(),
        "topic": str(topic_code),
        "notes": "1" if include_notes else "0",
        "stat": str(stat_code),
    }

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, params=params)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamError(
                f"statcan_census_profile_2016:get_data returned HTTP {status}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "statcan_census_profile_2016:get_data did not respond in time. Try again shortly."
            ) from exc

    cache_key = f"statcan-census-profile-2016:data:{dguid}:{topic_code}:{stat_code}:{lang_code}"
    payload, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)
    rows = _rows_as_dicts(payload, "statcan_census_profile_2016:get_data")

    values = [
        Census2016Value(
            geo_uid=row.get("GEO_UID") or "",
            geo_name=row.get("GEO_NAME_NOM") or "",
            topic=row.get("TOPIC_THEME"),
            text_id=row.get("TEXT_ID"),
            hierarchy_id=row.get("HIER_ID"),
            indent_level=row.get("INDENT_ID"),
            label=row.get("TEXT_NAME_NOM") or "",
            note=row.get("NOTE"),
            total_value=_to_float(row.get("T_DATA_DONNEE")),
            total_symbol=row.get("T_SYM"),
            male_value=_to_float(row.get("M_DATA_DONNEE")),
            male_symbol=row.get("M_SYM"),
            female_value=_to_float(row.get("F_DATA_DONNEE")),
            female_symbol=row.get("F_SYM"),
        )
        for row in rows
    ]
    return Census2016DataResult(
        dguid=dguid,
        topic=topic,
        values=values,
        returned_count=len(values),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_census_profile_2016.Census2016DataResult",
        ),
    )
