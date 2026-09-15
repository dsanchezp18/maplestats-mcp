"""HTTP client for the StatCan Web Data Service (WDS).

Every method wraps `shared.http.api_get`/`api_post`, respects the
statcan-wds rate limiter, and unwraps WDS's `[{"status": "SUCCESS",
"object": {...}}]` envelope. A 409 response is StatCan's documented
signal that data is locked during its 12am-8:30am ET daily update
window (see constants.py) — this is surfaced as DataLocked, not
retried and not reported as a generic failure, since retrying during
the lock window cannot succeed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

import httpx

from maple_data_mcp.modules.statcan.wds import constants
from maple_data_mcp.modules.statcan.wds.schemas import (
    ChangedCubeEntry,
    ChangedCubeList,
    ChangedSeriesEntry,
    ChangedSeriesList,
    CodeSetEntry,
    CodeSets,
    CubeDimension,
    CubeMetadata,
    CubeSummary,
    CubeSummaryList,
    DimensionMember,
    Footnote,
    FullTableDownloadLink,
    ObservationRow,
    SeriesInfo,
    VectorData,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import (
    DataLocked,
    InvalidInput,
    UpstreamError,
    UpstreamUnavailable,
)
from maple_data_mcp.shared.http import api_get, api_post
from maple_data_mcp.shared.json_utils import list_or_empty
from maple_data_mcp.shared.rate_limiter import get_limiter


def _limiter():
    return get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    )


def _raise_if_locked(exc: httpx.HTTPStatusError, method: str) -> NoReturn:
    if exc.response.status_code == 409:
        raise DataLocked(
            f"{method} is locked during StatCan's daily update window "
            "(12am-8:30am ET). Retry after 8:30am ET."
        ) from exc
    if exc.response.status_code == 406:
        # Confirmed live: WDS returns 406, not 404, for a well-formed
        # but nonexistent/invalid identifier (e.g. an unknown productId).
        raise InvalidInput(
            f"{method} rejected the request (HTTP 406) — check that the "
            "productId/vectorId/coordinate is valid."
        ) from exc
    raise exc


async def _post(method: str, body: list[dict[str, Any]]) -> list[dict[str, Any]]:
    await _limiter().acquire()
    url = f"{constants.BASE_URL}{method}"
    try:
        return await api_post(url, json_body=body)
    except httpx.HTTPStatusError as exc:
        _raise_if_locked(exc, method)
    except httpx.TimeoutException as exc:
        raise UpstreamUnavailable(
            f"{method} did not respond in time (already retried by "
            "shared/http.py). This endpoint is known to be occasionally "
            "slow; try again shortly."
        ) from exc


async def _get(method: str, path_suffix: str = "", params: dict[str, Any] | None = None) -> Any:
    await _limiter().acquire()
    url = f"{constants.BASE_URL}{method}{path_suffix}"
    try:
        return await api_get(url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_if_locked(exc, method)
    except httpx.TimeoutException as exc:
        raise UpstreamUnavailable(
            f"{method} did not respond in time (already retried by "
            "shared/http.py). This endpoint is known to be occasionally "
            "slow; try again shortly."
        ) from exc


def _unwrap_one(item: dict[str, Any], method: str) -> Any:
    """Unwrap one `{"status": "SUCCESS", "object": ...}` envelope.

    Return type is genuinely `Any`, not `dict` — WDS's `object` field is
    a dict for most methods (e.g. getCubeMetadata) but a list for the
    changed-list methods (getChangedCubeList/getChangedSeriesList),
    confirmed live. Callers annotate the shape they expect.
    """
    if item.get("status") != "SUCCESS":
        raise UpstreamError(
            f"{method} returned status={item.get('status')!r}: {item.get('object')!r}"
        )
    return item["object"]


def _pad_coordinate(coordinate: str) -> str:
    parts = coordinate.split(".")
    for part in parts:
        if part and not part.isdigit():
            raise InvalidInput(f"Coordinate part {part!r} is not numeric in {coordinate!r}")
    parts = parts[: constants.COORDINATE_DIMENSIONS]
    while len(parts) < constants.COORDINATE_DIMENSIONS:
        parts.append("0")
    return ".".join(parts)


def _cube_summary_from_json(obj: dict[str, Any]) -> CubeSummary:
    return CubeSummary(
        product_id=int(obj["productId"]),
        cansim_id=obj.get("cansimId") or None,
        cube_title_en=obj["cubeTitleEn"],
        cube_title_fr=obj["cubeTitleFr"],
        cube_start_date=obj["cubeStartDate"],
        cube_end_date=obj["cubeEndDate"],
        release_time=obj["releaseTime"],
        archived=str(obj.get("archived", obj.get("archiveStatusCode", "0"))) not in {"0", "2"},
        frequency_code=int(obj["frequencyCode"]),
        subject_codes=list_or_empty(obj, "subjectCode"),
        survey_codes=list_or_empty(obj, "surveyCode"),
        dimension_count=obj.get("dimensionCount"),
    )


async def get_all_cubes_list(*, lite: bool = True) -> CubeSummaryList:
    method = "getAllCubesListLite" if lite else "getAllCubesList"
    cache_key = f"wds:{method}"

    async def fetch() -> list[dict[str, Any]]:
        return await _get(method)

    data, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_CUBES_LIST_SECONDS, fetch)
    cubes = [_cube_summary_from_json(obj) for obj in data]
    return CubeSummaryList(
        cubes=cubes,
        total_count=len(cubes),
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}{method}",
            cached=was_cached,
            schema_name="statcan.wds.CubeSummaryList",
            freshness="daily at 8:30am ET",
        ),
    )


async def search_cubes(query: str, *, limit: int = 25) -> CubeSummaryList:
    """Full-text search over the cached cubes-lite inventory (client-side)."""
    all_cubes = await get_all_cubes_list(lite=True)
    needle = query.lower()
    matches = [
        c
        for c in all_cubes.cubes
        if needle in c.cube_title_en.lower() or needle in c.cube_title_fr.lower()
    ][:limit]
    return CubeSummaryList(
        cubes=matches,
        total_count=len(matches),
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}getAllCubesListLite",
            cached=all_cubes.provenance.cached,
            schema_name="statcan.wds.CubeSummaryList",
            coverage=f"top {limit} matches of {len(all_cubes.cubes)} cubes searched",
        ),
    )


async def get_cube_metadata(product_id: int) -> CubeMetadata:
    cache_key = f"wds:getCubeMetadata:{product_id}"

    async def fetch() -> dict[str, Any]:
        items = await _post("getCubeMetadata", [{"productId": product_id}])
        return _unwrap_one(items[0], "getCubeMetadata")

    obj, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_CUBE_METADATA_SECONDS, fetch
    )

    dimensions = [
        CubeDimension(
            dimension_position_id=int(dim["dimensionPositionId"]),
            dimension_name_en=dim["dimensionNameEn"],
            dimension_name_fr=dim["dimensionNameFr"],
            has_uom=bool(dim.get("hasUom")),
            members=[
                DimensionMember(
                    member_id=int(m["memberId"]),
                    parent_member_id=m.get("parentMemberId"),
                    member_name_en=m["memberNameEn"],
                    member_name_fr=m["memberNameFr"],
                    classification_code=m.get("classificationCode"),
                    geo_level=m.get("geoLevel"),
                    terminated=bool(int(m.get("terminated", 0) or 0)),
                )
                for m in dim.get("member", [])
            ],
        )
        for dim in obj.get("dimension", [])
    ]

    footnotes = [
        Footnote(
            footnote_id=int(fn["footnoteId"]),
            text_en=fn.get("footnotesEn", ""),
            text_fr=fn.get("footnotesFr", ""),
        )
        for fn in list_or_empty(obj, "footnote")
    ]

    return CubeMetadata(
        product_id=int(obj["productId"]),
        cansim_id=obj.get("cansimId") or None,
        cube_title_en=obj["cubeTitleEn"],
        cube_title_fr=obj["cubeTitleFr"],
        cube_start_date=obj["cubeStartDate"],
        cube_end_date=obj["cubeEndDate"],
        frequency_code=int(obj["frequencyCode"]),
        n_series=int(obj["nbSeriesCube"]),
        n_datapoints=int(obj["nbDatapointsCube"]),
        release_time=obj["releaseTime"],
        archive_status_en=obj.get("archiveStatusEn", ""),
        archive_status_fr=obj.get("archiveStatusFr", ""),
        subject_codes=list_or_empty(obj, "subjectCode"),
        survey_codes=list_or_empty(obj, "surveyCode"),
        footnotes=footnotes,
        dimensions=dimensions,
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}getCubeMetadata",
            cached=was_cached,
            schema_name="statcan.wds.CubeMetadata",
        ),
    )


async def get_series_info_from_cube_pid_coord(product_id: int, coordinate: str) -> SeriesInfo:
    coordinate = _pad_coordinate(coordinate)
    items = await _post(
        "getSeriesInfoFromCubePidCoord", [{"productId": product_id, "coordinate": coordinate}]
    )
    obj = _unwrap_one(items[0], "getSeriesInfoFromCubePidCoord")
    return SeriesInfo(
        product_id=int(obj["productId"]),
        coordinate=obj["coordinate"],
        vector_id=int(obj["vectorId"]),
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}getSeriesInfoFromCubePidCoord",
            cached=False,
            schema_name="statcan.wds.SeriesInfo",
        ),
    )


async def get_series_info_from_vector(vector_id: int) -> SeriesInfo:
    items = await _post("getSeriesInfoFromVector", [{"vectorId": vector_id}])
    obj = _unwrap_one(items[0], "getSeriesInfoFromVector")
    return SeriesInfo(
        product_id=int(obj["productId"]),
        coordinate=obj["coordinate"],
        vector_id=int(obj["vectorId"]),
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}getSeriesInfoFromVector",
            cached=False,
            schema_name="statcan.wds.SeriesInfo",
        ),
    )


def _observation_from_json(dp: dict[str, Any]) -> ObservationRow:
    ref_period_raw = dp.get("refPer") or dp.get("refPerRaw")
    if not ref_period_raw:
        raise UpstreamError(f"Observation is missing refPer/refPerRaw: {dp!r}")
    release_time = dp.get("releaseTime")
    return ObservationRow(
        ref_period=date.fromisoformat(ref_period_raw),
        value=dp.get("value"),
        decimals=int(dp.get("decimals", 0)),
        scalar_factor_code=int(dp.get("scalarFactorCode", 0)),
        symbol_code=int(dp.get("symbolCode", 0)),
        status_code=int(dp.get("statusCode", 0)),
        security_level_code=int(dp.get("securityLevelCode", 0)),
        release_time=datetime.fromisoformat(release_time).replace(tzinfo=UTC)
        if release_time
        else None,
    )


def _vector_data_from_json(obj: dict[str, Any], *, source_url: str, cached: bool) -> VectorData:
    return VectorData(
        product_id=int(obj["productId"]),
        coordinate=obj["coordinate"],
        vector_id=int(obj["vectorId"]),
        observations=[_observation_from_json(dp) for dp in list_or_empty(obj, "vectorDataPoint")],
        provenance=make_provenance(
            source="statcan-wds",
            url=source_url,
            cached=cached,
            schema_name="statcan.wds.VectorData",
        ),
    )


async def get_data_from_vectors_and_latest_n_periods(
    vector_ids: list[int], latest_n: int
) -> list[VectorData]:
    cache_key = f"wds:getDataFromVectorsAndLatestNPeriods:{sorted(vector_ids)}:{latest_n}"

    async def fetch() -> list[dict[str, Any]]:
        body = [{"vectorId": v, "latestN": latest_n} for v in vector_ids]
        items = await _post("getDataFromVectorsAndLatestNPeriods", body)
        return [_unwrap_one(item, "getDataFromVectorsAndLatestNPeriods") for item in items]

    objs, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_OBSERVATIONS_SECONDS, fetch
    )
    url = f"{constants.BASE_URL}getDataFromVectorsAndLatestNPeriods"
    return [_vector_data_from_json(obj, source_url=url, cached=was_cached) for obj in objs]


async def get_data_from_cube_pid_coord_and_latest_n_periods(
    product_id: int, coordinate: str, latest_n: int
) -> VectorData:
    coordinate = _pad_coordinate(coordinate)
    body = [{"productId": product_id, "coordinate": coordinate, "latestN": latest_n}]
    items = await _post("getDataFromCubePidCoordAndLatestNPeriods", body)
    obj = _unwrap_one(items[0], "getDataFromCubePidCoordAndLatestNPeriods")
    return _vector_data_from_json(
        obj,
        source_url=f"{constants.BASE_URL}getDataFromCubePidCoordAndLatestNPeriods",
        cached=False,
    )


async def get_bulk_vector_data_by_range(
    vector_ids: list[int], start_release_datetime: str, end_release_datetime: str
) -> list[VectorData]:
    """`start_release_datetime`/`end_release_datetime` must be full
    `YYYY-MM-DDTHH:MM` (WDS rejects a bare date with HTTP 406). Unlike
    every other WDS POST method, this one's body is a single flat
    object, not a one-item list — confirmed live; wrapping it in a list
    also produces a 406.
    """
    method = "getBulkVectorDataByRange"
    await _limiter().acquire()
    body = {
        "vectorIds": [str(v) for v in vector_ids],
        "startDataPointReleaseDate": start_release_datetime,
        "endDataPointReleaseDate": end_release_datetime,
    }
    try:
        items = await api_post(f"{constants.BASE_URL}{method}", json_body=body)
    except httpx.HTTPStatusError as exc:
        _raise_if_locked(exc, method)
    url = f"{constants.BASE_URL}{method}"
    return [
        _vector_data_from_json(
            _unwrap_one(item, "getBulkVectorDataByRange"), source_url=url, cached=False
        )
        for item in items
    ]


async def get_data_from_vector_by_reference_period_range(
    vector_ids: list[int], start_ref_period: str, end_ref_period: str
) -> list[VectorData]:
    """`start_ref_period`/`end_ref_period` must be full `YYYY-MM-DD`
    (WDS rejects an abbreviated `YYYY-MM` with HTTP 406)."""
    params = {
        "vectorIds": ",".join(str(v) for v in vector_ids),
        "startRefPeriod": start_ref_period,
        "endReferencePeriod": end_ref_period,
    }
    data = await _get("getDataFromVectorByReferencePeriodRange", params=params)
    url = f"{constants.BASE_URL}getDataFromVectorByReferencePeriodRange"
    return [
        _vector_data_from_json(
            _unwrap_one(item, "getDataFromVectorByReferencePeriodRange"),
            source_url=url,
            cached=False,
        )
        for item in data
    ]


async def get_changed_series_list() -> ChangedSeriesList:
    """Unlike getChangedCubeList, WDS documents this method as never
    accepting a date parameter — it always reflects today's changes."""
    method = "getChangedSeriesList"
    data = await _get(method)
    # Confirmed live: the response is ONE {"status", "object"} envelope
    # whose "object" is the list of entries — not one envelope per
    # entry, which is the shape getBulkVectorDataByRange etc. use.
    entries_raw: list[dict[str, Any]] = (
        _unwrap_one(data, method) if isinstance(data, dict) else data
    )
    entries = [
        ChangedSeriesEntry(
            product_id=int(obj["productId"]),
            coordinate=obj.get("coordinate", ""),
            vector_id=int(obj.get("vectorId", 0)),
            release_time=obj.get("releaseTime", ""),
        )
        for obj in entries_raw
    ]
    return ChangedSeriesList(
        series=entries,
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}{method}",
            cached=False,
            schema_name="statcan.wds.ChangedSeriesList",
        ),
    )


async def get_changed_cube_list(date_str: str | None = None) -> ChangedCubeList:
    """Unlike getChangedSeriesList, WDS requires an explicit date here —
    a bare call with no date returns HTTP 404, not "today" by default.
    Defaults to today's date in Eastern Time (WDS's own reference
    timezone) client-side when none is given."""
    method = "getChangedCubeList"
    date_str = date_str or datetime.now(ZoneInfo("America/Toronto")).date().isoformat()
    data = await _get(method, path_suffix=f"/{date_str}")
    # Same envelope shape as getChangedSeriesList — see its comment above.
    entries_raw: list[dict[str, Any]] = (
        _unwrap_one(data, method) if isinstance(data, dict) else data
    )
    entries = [
        ChangedCubeEntry(product_id=int(obj["productId"]), release_time=obj.get("releaseTime", ""))
        for obj in entries_raw
    ]
    return ChangedCubeList(
        cubes=entries,
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}{method}",
            cached=False,
            schema_name="statcan.wds.ChangedCubeList",
        ),
    )


async def get_changed_series_data_from_vector(vector_id: int) -> VectorData:
    items = await _post("getChangedSeriesDataFromVector", [{"vectorId": vector_id}])
    obj = _unwrap_one(items[0], "getChangedSeriesDataFromVector")
    return _vector_data_from_json(
        obj, source_url=f"{constants.BASE_URL}getChangedSeriesDataFromVector", cached=False
    )


async def get_changed_series_data_from_cube_pid_coord(
    product_id: int, coordinate: str
) -> VectorData:
    coordinate = _pad_coordinate(coordinate)
    items = await _post(
        "getChangedSeriesDataFromCubePidCoord",
        [{"productId": product_id, "coordinate": coordinate}],
    )
    obj = _unwrap_one(items[0], "getChangedSeriesDataFromCubePidCoord")
    return _vector_data_from_json(
        obj, source_url=f"{constants.BASE_URL}getChangedSeriesDataFromCubePidCoord", cached=False
    )


async def get_full_table_download_csv(product_id: int, lang: str = "en") -> FullTableDownloadLink:
    method = "getFullTableDownloadCSV"
    data = await _get(method, path_suffix=f"/{product_id}/{lang}")
    return FullTableDownloadLink(
        product_id=product_id,
        format="csv",
        language=lang,
        download_url=data.get("object", data) if isinstance(data, dict) else str(data),
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}{method}/{product_id}/{lang}",
            cached=False,
            schema_name="statcan.wds.FullTableDownloadLink",
        ),
    )


async def get_full_table_download_sdmx(product_id: int) -> FullTableDownloadLink:
    method = "getFullTableDownloadSDMX"
    data = await _get(method, path_suffix=f"/{product_id}")
    return FullTableDownloadLink(
        product_id=product_id,
        format="sdmx",
        language="en",
        download_url=data.get("object", data) if isinstance(data, dict) else str(data),
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}{method}/{product_id}",
            cached=False,
            schema_name="statcan.wds.FullTableDownloadLink",
        ),
    )


async def get_code_sets() -> CodeSets:
    cache_key = "wds:getCodeSets"

    async def fetch() -> dict[str, Any]:
        data = await _get("getCodeSets")
        return data["object"]

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_CODE_SETS_SECONDS, fetch)

    def entries(key: str, code_field: str, en_field: str, fr_field: str) -> list[CodeSetEntry]:
        return [
            CodeSetEntry(
                code=int(e[code_field]),
                description_en=e.get(en_field),
                description_fr=e.get(fr_field),
            )
            for e in obj.get(key, [])
        ]

    # Field names below are verified against a live getCodeSets response,
    # not guessed — several differ from the pattern the other categories
    # use (no "Desc" infix for survey/subject/classificationType; a
    # completely different key set for terminated).
    return CodeSets(
        scalar=entries("scalar", "scalarFactorCode", "scalarFactorDescEn", "scalarFactorDescFr"),
        frequency=entries("frequency", "frequencyCode", "frequencyDescEn", "frequencyDescFr"),
        symbol=entries("symbol", "symbolCode", "symbolDescEn", "symbolDescFr"),
        status=entries("status", "statusCode", "statusDescEn", "statusDescFr"),
        uom=entries("uom", "memberUomCode", "memberUomEn", "memberUomFr"),
        survey=entries("survey", "surveyCode", "surveyEn", "surveyFr"),
        subject=entries("subject", "subjectCode", "subjectEn", "subjectFr"),
        classification_type=entries(
            "classificationType",
            "classificationTypeCode",
            "classificationTypeEn",
            "classificationTypeFr",
        ),
        security_level=entries(
            "securityLevel", "securityLevelCode", "securityLevelDescEn", "securityLevelDescFr"
        ),
        terminated=entries("terminated", "codeId", "codeTextEn", "codeTextFr"),
        provenance=make_provenance(
            source="statcan-wds",
            url=f"{constants.BASE_URL}getCodeSets",
            cached=was_cached,
            schema_name="statcan.wds.CodeSets",
        ),
    )
