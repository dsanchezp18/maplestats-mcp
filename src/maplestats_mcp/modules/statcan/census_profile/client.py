"""HTTP client for the 2021 Census Profile SDMX API.

Confirmed live 2026-09-20. Two real quirks handled:

1. The `data` resource honours `format=jsondata` as a query parameter,
   but the `codelist`/`dataflow` metadata resources only respond in
   JSON via HTTP content negotiation (`Accept:
   application/vnd.sdmx.structure+json;version=1.0`) -- the query
   parameter has no effect there, confirmed live (a plain GET without
   that header returns SDMX-ML XML instead).
2. SDMX-JSON is self-describing but positionally indexed: a series key
   like "0:0:0:0:0" indexes into each dimension's own per-response
   `values` list (in `structures[0].dimensions.series` order), not a
   global codelist -- and series/observation attributes (GEO_DESC,
   TOPIC, FLAG, CI_LOW, CI_HIGH, RELEASE_DATE, ...) are decoded the
   same positional way against `structures[0].attributes.series` /
   `.observation`. `_decode_attrs` below handles both the coded
   ({"id", "name"}) and plain scalar ({"value"}) attribute-value
   shapes the API actually returns.
3. The `data` resource is genuinely slow -- confirmed live and
   reproducible across multiple distinct queries (a single geography x
   single characteristic each took 45-48 seconds via a raw `curl`,
   bypassing this client entirely), well past `shared/http.py`'s
   default 30-second timeout. `get_data`'s fetch passes an explicit
   60-second timeout rather than assuming the default is enough; this
   is real upstream latency, not a bug in this client or a sign the
   query is malformed.
4. French output is real but is selected by the `Accept-Language`
   request header, not a `lang`/`locale` query parameter (a `lang=fr`
   query parameter is rejected outright with "Unknown query
   parameter", confirmed live) -- every function here takes `lang` and
   translates it to that header.
"""

from __future__ import annotations

from typing import Any

import httpx

from maplestats_mcp.modules.statcan.census_profile import constants
from maplestats_mcp.modules.statcan.census_profile.schemas import (
    CensusProfileDataResult,
    CensusProfileValue,
    CharacteristicMatch,
    CharacteristicSearchResult,
    GeographyMatch,
    GeographySearchResult,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

_STRUCTURE_ACCEPT = {"Accept": "application/vnd.sdmx.structure+json;version=1.0"}
_LANG_TO_API = {"en": "en", "fr": "fr"}


def _attr_display(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    if "name" in entry:
        return entry["name"]
    if "value" in entry:
        return entry["value"]
    return None


def _decode_attrs(defs: list[dict[str, Any]], indices: list[Any]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for defn, idx in zip(defs, indices, strict=False):
        if idx is None:
            result[defn["id"]] = None
            continue
        values = defn.get("values") or []
        entry = values[idx] if isinstance(idx, int) and 0 <= idx < len(values) else None
        result[defn["id"]] = _attr_display(entry)
    return result


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def _fetch_codelist(codelist_id: str, lang: str = "en") -> tuple[list[dict[str, Any]], bool]:
    url = f"{constants.BASE_URL}/codelist/{constants.AGENCY}/{codelist_id}/latest"
    api_lang = _LANG_TO_API.get(lang, "en")
    headers = {**_STRUCTURE_ACCEPT, "Accept-Language": api_lang}

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, headers=headers)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = exc.response.text[:200]
            raise UpstreamError(
                f"statcan_census_profile:_fetch_codelist({codelist_id}) returned HTTP {status}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "statcan_census_profile:_fetch_codelist did not respond in time "
                "(already retried by shared/http.py). Try again shortly."
            ) from exc

    cache_key = f"statcan-census-profile:codelist:{codelist_id}:{api_lang}"
    payload, cached = await cached_fetch(cache_key, constants.CACHE_TTL_CODELIST_SECONDS, fetch)
    codelists = ((payload or {}).get("data") or {}).get("codelists") or []
    if not codelists:
        raise UpstreamError(
            f"statcan_census_profile:_fetch_codelist: no codelist found for {codelist_id!r}."
        )
    codes = codelists[0].get("codes") or []
    return [
        {"code": c["id"], "name": c.get("name") or c["id"], "parent": c.get("parent")}
        for c in codes
    ], cached


async def search_geography(
    level: str,
    query: str = "",
    *,
    limit: int = constants.GEOGRAPHY_SEARCH_LIMIT_DEFAULT,
    lang: str = "en",
) -> GeographySearchResult:
    """Search one geography level's codelist by place name substring."""
    dataflow = constants.GEOGRAPHY_LEVEL_TO_DATAFLOW.get(level)
    if dataflow is None:
        raise InvalidInput(
            f"statcan_census_profile:search_geography: level must be one of "
            f"{sorted(constants.GEOGRAPHY_LEVEL_TO_DATAFLOW)}, got {level!r}."
        )
    if limit < 1 or limit > constants.GEOGRAPHY_SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"statcan_census_profile:search_geography: limit must be between 1 and "
            f"{constants.GEOGRAPHY_SEARCH_LIMIT_MAX}, got {limit}."
        )
    _, codelist_id = dataflow
    codes, cached = await _fetch_codelist(codelist_id, lang)
    query_lower = query.strip().lower()
    matched = [c for c in codes if query_lower in c["name"].lower()] if query_lower else codes
    return GeographySearchResult(
        level=level,
        matches=[GeographyMatch(code=c["code"], name=c["name"]) for c in matched[:limit]],
        total_matched=len(matched),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}/codelist/{constants.AGENCY}/{codelist_id}/latest",
            cached=cached,
            schema_name="statcan_census_profile.GeographySearchResult",
        ),
    )


async def search_characteristic(
    query: str = "",
    *,
    limit: int = constants.CHARACTERISTIC_SEARCH_LIMIT_DEFAULT,
    lang: str = "en",
) -> CharacteristicSearchResult:
    """Search the 2,631 census profile characteristics (variables) by name substring."""
    if limit < 1 or limit > constants.CHARACTERISTIC_SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"statcan_census_profile:search_characteristic: limit must be between 1 and "
            f"{constants.CHARACTERISTIC_SEARCH_LIMIT_MAX}, got {limit}."
        )
    codes, cached = await _fetch_codelist(constants.CHARACTERISTIC_CODELIST, lang)
    query_lower = query.strip().lower()
    matched = [c for c in codes if query_lower in c["name"].lower()] if query_lower else codes
    return CharacteristicSearchResult(
        matches=[
            CharacteristicMatch(code=c["code"], name=c["name"], parent_code=c.get("parent"))
            for c in matched[:limit]
        ],
        total_matched=len(matched),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}/codelist/{constants.AGENCY}/{constants.CHARACTERISTIC_CODELIST}/latest",
            cached=cached,
            schema_name="statcan_census_profile.CharacteristicSearchResult",
        ),
    )


async def get_data(
    level: str,
    geography_codes: list[str],
    characteristic_codes: list[str],
    *,
    gender: str = "total",
    statistic: str = "counts",
    lang: str = "en",
) -> CensusProfileDataResult:
    """Fetch census profile values for one or more geographies and characteristics."""
    dataflow = constants.GEOGRAPHY_LEVEL_TO_DATAFLOW.get(level)
    if dataflow is None:
        raise InvalidInput(
            f"statcan_census_profile:get_data: level must be one of "
            f"{sorted(constants.GEOGRAPHY_LEVEL_TO_DATAFLOW)}, got {level!r}."
        )
    if not geography_codes:
        raise InvalidInput("statcan_census_profile:get_data: geography_codes must not be empty.")
    if not characteristic_codes:
        raise InvalidInput(
            "statcan_census_profile:get_data: characteristic_codes must not be empty."
        )
    gender_code = constants.GENDER_TO_CODE.get(gender)
    if gender_code is None:
        raise InvalidInput(
            f"statcan_census_profile:get_data: gender must be one of "
            f"{sorted(constants.GENDER_TO_CODE)}, got {gender!r}."
        )
    statistic_code = constants.STATISTIC_TO_CODE.get(statistic)
    if statistic_code is None:
        raise InvalidInput(
            f"statcan_census_profile:get_data: statistic must be one of "
            f"{sorted(constants.STATISTIC_TO_CODE)}, got {statistic!r}."
        )

    dataflow_id, _ = dataflow
    key = (
        f"A5.{'+'.join(geography_codes)}.{gender_code}."
        f"{'+'.join(characteristic_codes)}.{statistic_code}"
    )
    url = f"{constants.BASE_URL}/data/{constants.AGENCY},{dataflow_id}/{key}"
    api_lang = _LANG_TO_API.get(lang, "en")

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(
                url,
                params={"format": "jsondata"},
                headers={"Accept-Language": api_lang},
                timeout=60.0,
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = exc.response.text[:200]
            if 400 <= status < 500:
                raise InvalidInput(
                    f"statcan_census_profile:get_data returned HTTP {status}: {detail}"
                ) from exc
            raise UpstreamError(
                f"statcan_census_profile:get_data returned HTTP {status}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "statcan_census_profile:get_data did not respond in time "
                "(already retried by shared/http.py). Try again shortly."
            ) from exc

    cache_key = f"statcan-census-profile:data:{dataflow_id}:{key}:{api_lang}"
    payload, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_DATA_SECONDS, fetch)

    data = (payload or {}).get("data") or {}
    datasets = data.get("dataSets") or []
    structures = data.get("structures") or []
    if not datasets or not structures:
        raise UpstreamError(
            "statcan_census_profile:get_data: unexpected response shape (missing dataSets/structures)."
        )

    dims = structures[0]["dimensions"]["series"]
    series_attr_defs = structures[0].get("attributes", {}).get("series", [])
    obs_attr_defs = structures[0].get("attributes", {}).get("observation", [])

    release_date: str | None = None
    values: list[CensusProfileValue] = []
    for series_key, series_obj in (datasets[0].get("series") or {}).items():
        idx_list = [int(x) for x in series_key.split(":")]
        dim_values: dict[str, dict[str, Any]] = {}
        for defn, idx in zip(dims, idx_list, strict=False):
            defn_values = defn.get("values") or []
            dim_values[defn["id"]] = defn_values[idx] if 0 <= idx < len(defn_values) else {}

        series_attrs = _decode_attrs(series_attr_defs, series_obj.get("attributes") or [])
        if release_date is None and series_attrs.get("RELEASE_DATE"):
            release_date = series_attrs["RELEASE_DATE"]

        geography_name = series_attrs.get("GEO_DESC") or dim_values.get("REF_AREA", {}).get(
            "name", ""
        )
        topic = series_attrs.get("TOPIC")

        for obs_arr in (series_obj.get("observations") or {}).values():
            if not obs_arr:
                continue
            value_raw = obs_arr[0]
            obs_attrs = _decode_attrs(obs_attr_defs, obs_arr[1:])
            values.append(
                CensusProfileValue(
                    geography_code=dim_values.get("REF_AREA", {}).get("id", ""),
                    geography_name=geography_name,
                    characteristic_code=dim_values.get("CHARACTERISTIC", {}).get("id", ""),
                    characteristic_name=dim_values.get("CHARACTERISTIC", {}).get("name", ""),
                    topic=topic,
                    gender=dim_values.get("GENDER", {}).get("name", ""),
                    statistic=dim_values.get("STATISTIC", {}).get("name", ""),
                    value=_to_float(value_raw),
                    value_raw=str(value_raw) if value_raw is not None else None,
                    flag=obs_attrs.get("FLAG"),
                    confidence_interval_low=_to_float(obs_attrs.get("CI_LOW")),
                    confidence_interval_high=_to_float(obs_attrs.get("CI_HIGH")),
                )
            )

    return CensusProfileDataResult(
        level=level,
        values=values,
        release_date=release_date,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_census_profile.CensusProfileDataResult",
        ),
    )
