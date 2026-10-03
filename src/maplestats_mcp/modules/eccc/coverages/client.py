"""Client for MSC GeoMet's OGC API - Coverages (gridded climate data).

Confirmed live against https://api.weather.gc.ca on 2026-10-03 (pygeoapi
0.20.0), across CanDCS-U6, CMIP5, DCS, climate indices, SPEI and CanGRD:

- `/collections/{id}?f=json` lists the axes in `extent`: `temporal`
  (`interval` [[start, end]], `grid.resolution` P1Y or P1M; CanGRD gives
  the years as integers), and one block per extra axis, each with
  `interval: [[values...]]`: `scenario` (SSP126/SSP245/SSP585 or
  RCP2.6/RCP4.5/RCP8.5), `percentile` (10/50/90, 5..95 or 25/50/75),
  `season` (DJF/MAM/JJA/SON) and `P20Y-Avg`/`P30Y-Avg` (windows such as
  "2071-2100"). The averaged sets have no usable temporal extent.
- `/collections/{id}/schema?f=json` lists the variables under
  `properties`, with `title` and `x-ogc-unit` (null for DCS and indices).
- `/coverage?f=json&bbox=w,s,e,n` returns CoverageJSON: `domain.axes`
  x/y as {start, stop, num} and t as {values}, `ranges[var]` with
  `axisNames` (["y", "x", "t"], or ["y", "x"]) and a flat row-major
  `values` list, null where there is no data (ocean, outside the mask).
- `subset=scenario(SSP585),percentile(90),season(JJA),P30Y-Avg(2071-2100)`
  picks one value on each axis. Without it the server silently returns the
  first value of each axis (SSP126, the lowest percentile, DJF) and does
  not say so in the response, so every request here names each axis.
- `properties=` picks variables. Several variables in one request work for
  CanDCS-U6 but give HTTP 500 for CMIP5, so each variable is its own
  request. An unknown variable gives HTTP 400 "Invalid field specified";
  an unknown subset axis HTTP 400 "Invalid axis name".
- An unknown scenario or percentile value, a `datetime` outside the
  temporal extent, a `datetime` on an averaged set and a date range on
  CanGRD all give HTTP 500, so those are checked here first.
- A bbox containing no cell centre answers HTTP 204 with an empty body
  (a CanDCS-U6 bbox under 1/12 degree wide, or a point given as a
  zero-size bbox). Point requests therefore ask for a window one cell wide
  on each side of the point and keep the nearest cell that has data.
- The server has no size cap: a whole-Canada CanDCS-U6 year is 544,680
  values (6.2 MB).
- SPEI responses give only the first and last timestamps (with drifting
  days, e.g. "2050-01-03" and "2050-12-03") while the range holds one value
  per month; months are numbered forward from the first timestamp.
- CanGRD responses use EPSG:3995 (Arctic polar stereographic, metres) for
  x/y, carry no time axis, and accept one `datetime` per request (a range
  gives HTTP 500), so a CanGRD series is one request per year or month.
"""

from __future__ import annotations

import asyncio
import itertools
import math
import re
from dataclasses import dataclass
from typing import Any, NoReturn
from urllib.parse import quote

import httpx

from maplestats_mcp.modules.eccc import client as eccc_client
from maplestats_mcp.modules.eccc.coverages import constants
from maplestats_mcp.modules.eccc.coverages.schemas import (
    CoverageCollection,
    CoverageCollectionList,
    CoverageData,
    CoverageDescription,
    CoverageRow,
    CoverageVariable,
    TimeRange,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

_SOURCE = "eccc"
_AVG_AXIS = re.compile(r"^P\d+Y-Avg$")
_YEAR = re.compile(r"^\d{4}$")
_MONTH = re.compile(r"^\d{4}-\d{2}$")

_FAMILY_NOTES = {
    "candcsu6": "CanDCS-U6: CMIP6 models statistically downscaled (BCCAQv2) to a 1/12-degree "
    "grid; values are percentiles of the 26-model ensemble.",
    "cmip5": "CMIP5 global model ensemble on a 1-degree grid; values are ensemble percentiles.",
    "dcs": "DCS: CMIP5 models statistically downscaled (BCCAQv2) to a 1/12-degree grid.",
    "indices": "Statistically downscaled climate indices (CMIP5, 1/12 degree): degree days, "
    "growing season lengths, hot nights and hot days, wet days.",
    "spei-1": "SPEI-1: Standardized Precipitation Evapotranspiration Index over 1 month (CMIP5, "
    "1 degree); negative is drier than normal.",
    "spei-3": "SPEI-3: Standardized Precipitation Evapotranspiration Index over 3 months.",
    "spei-12": "SPEI-12: Standardized Precipitation Evapotranspiration Index over 12 months.",
    "cangrd": "CanGRD: gridded observed temperature and precipitation anomalies (relative to "
    "1961-1990) and trends from station data.",
}


def _limiter():
    return get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    )


def _licence(lang: str) -> str:
    return constants.ECCC_LICENCE_FR if lang == "fr" else constants.ECCC_LICENCE


def _segment(collection_id: str) -> str:
    return quote(collection_id, safe=":")


def _description(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
    except ValueError:
        return ""
    return str(body.get("description", "")) if isinstance(body, dict) else ""


def _raise_for(exc: httpx.HTTPStatusError, context: str) -> NoReturn:
    status = exc.response.status_code
    detail = _description(exc)
    if status == 404:
        raise NotFound(f"{context}: {detail or 'not found'} (HTTP 404).") from exc
    if status == 400:
        raise InvalidInput(f"{context}: {detail or 'rejected'} (HTTP 400).") from exc
    raise UpstreamError(
        f"{context}: upstream returned HTTP {status}"
        f"{': ' + detail if detail else ''}. The selection was checked against the "
        "collection's own axes first, so this is a server-side failure; retry, or narrow "
        "the variables, years or bbox."
    ) from exc


async def _fetch(path: str, params: dict[str, Any], timeout: float = 30.0) -> Any | None:
    """GET JSON; None for HTTP 204 (no grid cell inside the bbox)."""
    await _limiter().acquire()
    url = f"{constants.BASE_URL}{path}"
    try:
        response = await get_raw(url, params=params, timeout=timeout)
    except httpx.HTTPStatusError as exc:
        _raise_for(exc, path)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{path} did not respond (already retried): {type(exc).__name__}."
        ) from exc
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise UpstreamError(f"{path} did not return JSON.") from exc


# --- catalogue -------------------------------------------------------------


def _interval_values(block: Any) -> list[Any]:
    if not isinstance(block, dict):
        return []
    interval = block.get("interval") or []
    return list(interval[0]) if interval and isinstance(interval[0], list) else []


def _id_parts(collection_id: str) -> tuple[str, str | None, str | None]:
    parts = collection_id.split(":")
    family = parts[1] if len(parts) > 1 else collection_id
    timeframe = next((p for p in parts if p in ("historical", "projected")), None)
    frequency = next((p for p in parts if p in ("annual", "seasonal", "monthly")), None)
    return family, timeframe, frequency


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_percentile(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


@dataclass
class _Entry:
    """A collection's metadata as fetched: detail document and variable schema."""

    collection: CoverageCollection
    detail: dict[str, Any]
    avg_axis: str | None


def _build_entry(collection_id: str, detail: dict[str, Any], schema: dict[str, Any]) -> _Entry:
    extent = detail.get("extent") or {}
    family, timeframe, frequency = _id_parts(collection_id)
    avg_axis = next((k for k in extent if _AVG_AXIS.match(k)), None)
    temporal = extent.get("temporal") or {}
    time_values = _interval_values(temporal)
    resolution = (temporal.get("grid") or {}).get("resolution")
    time_range = None
    if avg_axis is None and len(time_values) == 2 and None not in time_values:
        time_range = TimeRange(
            start=str(time_values[0]), end=str(time_values[1]), resolution=resolution
        )
    if frequency is None and resolution in ("P1Y", "P1M"):
        frequency = "annual" if resolution == "P1Y" else "monthly"
    variables = [
        CoverageVariable(
            name=name,
            title=(spec or {}).get("title"),
            unit=(spec or {}).get("x-ogc-unit"),
        )
        for name, spec in (schema.get("properties") or {}).items()
    ]
    percentiles = [p for p in (_number(v) for v in _interval_values(extent.get("percentile")))]
    collection = CoverageCollection(
        id=collection_id,
        title=str(detail.get("title", "")),
        family=family,
        timeframe=timeframe,
        frequency=frequency,
        variables=variables,
        scenarios=[str(v) for v in _interval_values(extent.get("scenario"))],
        percentiles=[p for p in percentiles if p is not None],
        seasons=[str(v) for v in _interval_values(extent.get("season"))],
        averaging_periods=[str(v) for v in _interval_values(extent.get(avg_axis))]
        if avg_axis
        else [],
        time_range=time_range,
    )
    return _Entry(collection=collection, detail=detail, avg_axis=avg_axis)


async def _entry(collection_id: str) -> tuple[_Entry, bool]:
    segment = _segment(collection_id)

    async def fetch() -> tuple[dict[str, Any], dict[str, Any]]:
        detail = await _fetch(f"/collections/{segment}", {"f": "json"})
        schema = await _fetch(f"/collections/{segment}/schema", {"f": "json"})
        return detail or {}, schema or {}

    (detail, schema), was_cached = await cached_fetch(
        f"eccc:coverage-meta:{collection_id}", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch
    )
    return _build_entry(collection_id, detail, schema), was_cached


async def _coverage_ids() -> list[str]:
    summaries, _ = await eccc_client._all_collections()
    return [s.id for s in summaries if s.id.startswith(constants.COLLECTION_PREFIX)]


async def _catalogue() -> tuple[list[_Entry], bool]:
    ids = await _coverage_ids()
    semaphore = asyncio.Semaphore(constants.CATALOGUE_CONCURRENCY)

    async def one(cid: str) -> tuple[_Entry, bool]:
        async with semaphore:
            return await _entry(cid)

    results = await asyncio.gather(*(one(cid) for cid in ids))
    return [entry for entry, _ in results], all(cached for _, cached in results)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _matches(
    collection: CoverageCollection,
    description: str,
    words: list[str],
    scenario: str | None,
    variable: str | None,
    timeframe: str | None,
    frequency: str | None,
    year: int | None,
) -> bool:
    haystack = " ".join(
        [collection.id, collection.title, description, collection.family]
        + [f"{v.name} {v.title or ''}" for v in collection.variables]
        + collection.scenarios
        + collection.seasons
    ).lower()
    if any(word not in haystack for word in words):
        return False
    if scenario and _norm(scenario) not in {_norm(s) for s in collection.scenarios}:
        return False
    if variable:
        needle = variable.lower()
        if not any(
            needle == v.name.lower() or needle in (v.title or "").lower()
            for v in collection.variables
        ):
            return False
    if timeframe and collection.timeframe != timeframe:
        return False
    if frequency and collection.frequency != frequency:
        return False
    return year is None or _covers_year(collection, year)


def _covers_year(collection: CoverageCollection, year: int) -> bool:
    for window in collection.averaging_periods:
        start, _, end = window.partition("-")
        if start.isdigit() and end.isdigit() and int(start) <= year <= int(end):
            return True
    if collection.time_range is not None:
        start, end = collection.time_range.start[:4], collection.time_range.end[:4]
        return start.isdigit() and end.isdigit() and int(start) <= year <= int(end)
    return False


async def search_coverages(
    query: str = "",
    *,
    scenario: str | None = None,
    variable: str | None = None,
    timeframe: str | None = None,
    frequency: str | None = None,
    year: int | None = None,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    lang: str = "en",
) -> CoverageCollectionList:
    if limit < 1 or limit > 100:
        raise InvalidInput(f"limit must be between 1 and 100, got {limit}.")
    entries, was_cached = await _catalogue()
    words = [w for w in query.lower().split() if w]
    matches = [
        e.collection
        for e in entries
        if _matches(
            e.collection,
            str(e.detail.get("description", "")),
            words,
            scenario,
            variable,
            timeframe,
            frequency,
            year,
        )
    ]
    return CoverageCollectionList(
        collections=matches[:limit],
        total_count=len(matches),
        provenance=make_provenance(
            source=_SOURCE,
            url=f"{constants.BASE_URL}/collections?f=json",
            cached=was_cached,
            schema_name="eccc.CoverageCollectionList",
            coverage=f"{len(matches)} of {len(entries)} climate coverage collections matched",
            licence=_licence(lang),
            lang=lang,
        ),
    )


def _require_collection(collection_id: str) -> str:
    collection_id = collection_id.strip()
    if not collection_id.startswith(constants.COLLECTION_PREFIX):
        raise InvalidInput(
            f"collection_id must be a climate coverage id starting with 'climate:' "
            f"(e.g. climate:candcsu6:projected:annual:absolute), got {collection_id!r}. "
            "Use eccc_coverages_search to find one; feature collections such as "
            "climate-daily are read with eccc_query_items."
        )
    return collection_id


def _grid(detail: dict[str, Any]) -> tuple[list[float] | None, list[float] | None]:
    spatial = (detail.get("extent") or {}).get("spatial") or {}
    bbox_list = spatial.get("bbox") or []
    bbox = [float(v) for v in bbox_list[0]] if bbox_list else None
    grid = spatial.get("grid") or []
    resolution = [float(g["resolution"]) for g in grid if _number(g.get("resolution"))]
    return bbox, (resolution if len(resolution) == 2 else None)


def _is_projected(entry: _Entry) -> bool:
    return entry.collection.family == "cangrd"


async def describe_coverage(collection_id: str, *, lang: str = "en") -> CoverageDescription:
    collection_id = _require_collection(collection_id)
    if collection_id not in await _coverage_ids():
        raise NotFound(
            f"No climate coverage collection {collection_id!r}. Use eccc_coverages_search "
            "to list the ids."
        )
    entry, was_cached = await _entry(collection_id)
    bbox, resolution = _grid(entry.detail)
    notes = (
        [_FAMILY_NOTES[entry.collection.family]] if entry.collection.family in _FAMILY_NOTES else []
    )
    if entry.collection.scenarios:
        notes.append(
            "Without a scenario the server would use the first one; eccc_coverages_get_data "
            "always names the scenario, percentile, season and averaging period it asks for."
        )
    if entry.avg_axis:
        notes.append(
            "Averaged set: one value per window; pick windows with `averaging_periods`, "
            "not start/end years."
        )
    if _is_projected(entry):
        notes.append(
            "Grid cells are on a polar stereographic grid (EPSG:3995); rows give each cell's "
            "centre converted to latitude/longitude. One request per year or month."
        )
    links = entry.detail.get("links") or []
    canonical = next(
        (
            link.get("href")
            for link in links
            if link.get("rel") == "canonical" and isinstance(link.get("href"), str)
        ),
        None,
    )
    data = entry.collection.model_dump()
    return CoverageDescription(
        **data,
        description=str(entry.detail.get("description", "")),
        bbox=bbox,
        grid_resolution=resolution,
        crs="EPSG:3995" if _is_projected(entry) else "CRS84",
        canonical_url=canonical,
        notes=notes,
        provenance=make_provenance(
            source=_SOURCE,
            url=f"{constants.BASE_URL}/collections/{collection_id}?f=json",
            cached=was_cached,
            schema_name="eccc.CoverageDescription",
            licence=_licence(lang),
            lang=lang,
        ),
    )


# --- data ------------------------------------------------------------------

# WGS84 ellipsoid and EPSG:3995 (polar stereographic, latitude of true scale
# 71 N, central meridian 0). Checked against a live CanGRD response: the
# forward projection of Edmonton (53.525 N, 113.475 W) gives
# (-3758084, 1632112) m, inside the returned cells' x/y range.
_A = 6378137.0
_F = 1 / 298.257223563
_E = math.sqrt(_F * (2 - _F))
_PHI_C = math.radians(71.0)


def _t(phi: float) -> float:
    sin_phi = _E * math.sin(phi)
    return math.tan(math.pi / 4 - phi / 2) / ((1 - sin_phi) / (1 + sin_phi)) ** (_E / 2)


_MC = math.cos(_PHI_C) / math.sqrt(1 - (_E * math.sin(_PHI_C)) ** 2)
_TC = _t(_PHI_C)


def polar_stereo_forward(lon: float, lat: float) -> tuple[float, float]:
    rho = _A * _MC * _t(math.radians(lat)) / _TC
    lam = math.radians(lon)
    return rho * math.sin(lam), -rho * math.cos(lam)


def polar_stereo_inverse(x: float, y: float) -> tuple[float, float]:
    rho = math.hypot(x, y)
    t = rho * _TC / (_A * _MC)
    phi = math.pi / 2 - 2 * math.atan(t)
    for _ in range(10):
        sin_phi = _E * math.sin(phi)
        phi = math.pi / 2 - 2 * math.atan(t * ((1 - sin_phi) / (1 + sin_phi)) ** (_E / 2))
    return math.degrees(math.atan2(x, -y)), math.degrees(phi)


def _axis_coords(axis: dict[str, Any]) -> list[float]:
    if "values" in axis:
        return [float(v) for v in axis["values"]]
    start, stop, num = float(axis["start"]), float(axis["stop"]), int(axis["num"])
    if num <= 1:
        return [start]
    step = (stop - start) / (num - 1)
    return [start + i * step for i in range(num)]


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(1.0, h)))


def _add_months(month: str, count: int) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    index = year * 12 + mon - 1 + count
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _time_labels(domain_t: dict[str, Any] | None, count: int, notes: list[str]) -> list[str | None]:
    if domain_t is None:
        return [None] * count
    values = [str(v) for v in domain_t.get("values", [])]
    if len(values) == count:
        labels: list[str | None] = list(values)
        return labels
    if len(values) == 2 and count > 2 and re.match(r"^\d{4}-\d{2}", values[0]):
        note = (
            f"The source gave only the first and last timestamps ({values[0]}, {values[1]}) "
            f"for {count} monthly values; months were numbered forward from the first."
        )
        if note not in notes:
            notes.append(note)
        return [_add_months(values[0][:7], i) for i in range(count)]
    raise UpstreamError(
        f"Coverage time axis has {len(values)} labels for {count} values; cannot align them."
    )


@dataclass
class _Request:
    variable: str
    scenario: str | None
    percentile: float | None
    season: str | None
    averaging_period: str | None
    datetime: str | None
    time_label: str | None


@dataclass
class _Cell:
    lat: float
    lon: float
    values: list[float | None]


# Families whose range rows run opposite to the domain's y axis. Checked live
# on 2026-10-03 by requesting a 3 x 2 cell bbox and then each cell on its own:
# CanDCS-U6, DCS and CanGRD put their first data row at the domain's y `stop`;
# CMIP5, climate indices and SPEI at its `start`.
_ROWS_REVERSED = frozenset({"candcsu6", "dcs", "cangrd"})


def _cells(
    payload: dict[str, Any], variable: str, family: str, notes: list[str]
) -> tuple[list[_Cell], int, str | None]:
    """Unpack one CoverageJSON response into cells with their time series.

    Returns the cells, the number of time steps (0 when the response has no
    time axis) and the unit. Every family checked live stores the values
    time-major (all cells of the first time step, then the next), row by
    row, although `axisNames` says ["y", "x", "t"]; reading the declared
    order interleaves unrelated cells and puts nulls inside a series.
    """
    domain = payload.get("domain") or {}
    axes = domain.get("axes") or {}
    ranges = payload.get("ranges") or {}
    key = variable
    if key not in ranges:
        # Confirmed live: climate:dcs:projected:monthly:absolute answers
        # properties=tm with a range named "tmean".
        if len(ranges) != 1:
            raise UpstreamError(f"Coverage response has no range for variable {variable!r}.")
        key = next(iter(ranges))
        note = f"The source names {variable} {key!r} in its data response."
        if note not in notes:
            notes.append(note)
    rng = ranges[key]
    names: list[str] = list(rng.get("axisNames") or [])
    shape: list[int] = [int(n) for n in rng.get("shape") or []]
    values: list[Any] = list(rng.get("values") or [])
    if len(names) != len(shape) or math.prod(shape) != len(values):
        raise UpstreamError("Coverage range shape does not match its values.")
    xs = _axis_coords(axes["x"])
    ys = _axis_coords(axes["y"])
    size = dict(zip(names, shape, strict=True))
    nx, ny, n_time = size.get("x", 1), size.get("y", 1), size.get("t", 1)
    if len(xs) != nx or len(ys) != ny:
        raise UpstreamError("Coverage domain size does not match its range shape.")
    referencing = domain.get("referencing") or [{}]
    crs_id = str((referencing[0].get("system") or {}).get("id", ""))
    projected = crs_id.endswith("/3995")
    reversed_rows = family in _ROWS_REVERSED
    cells: list[_Cell] = []
    for iy, ix in itertools.product(range(ny), range(nx)):
        lon, lat = polar_stereo_inverse(xs[ix], ys[iy]) if projected else (xs[ix], ys[iy])
        row = ny - 1 - iy if reversed_rows else iy
        base = row * nx + ix
        series = [values[it * nx * ny + base] for it in range(n_time)]
        cells.append(
            _Cell(
                lat=round(lat, 6),
                lon=round(lon, 6),
                values=[float(v) if v is not None else None for v in series],
            )
        )
    parameter = (payload.get("parameters") or {}).get(key) or {}
    unit = (parameter.get("unit") or {}).get("symbol")
    return cells, (n_time if "t" in size else 0), unit


def _normalize_time(value: str, resolution: str | None, *, is_end: bool, label: str) -> str:
    value = value.strip()
    if resolution == "P1M":
        if _YEAR.match(value):
            return f"{value}-12" if is_end else f"{value}-01"
        if _MONTH.match(value):
            return value
        raise InvalidInput(f"{label} must be YYYY or YYYY-MM for this monthly set, got {value!r}.")
    if _YEAR.match(value):
        return value
    if _MONTH.match(value):
        raise InvalidInput(f"{label} must be a year (YYYY) for this annual/seasonal set.")
    raise InvalidInput(f"{label} must be a year (YYYY), got {value!r}.")


def _steps(start: str, end: str, resolution: str | None) -> list[str]:
    if resolution == "P1M":
        count = (int(end[:4]) - int(start[:4])) * 12 + int(end[5:7]) - int(start[5:7]) + 1
        return [_add_months(start, i) for i in range(max(count, 0))]
    return [str(y) for y in range(int(start), int(end) + 1)]


def _pick(
    requested: list[Any] | None,
    available: list[Any],
    axis: str,
    default: list[Any],
    normalize: Any = str,
) -> list[Any]:
    if not available:
        if requested:
            raise InvalidInput(f"This collection has no {axis} axis; leave `{axis}` empty.")
        return [None]
    if not requested:
        return default
    lookup = {normalize(a): a for a in available}
    picked = []
    for value in requested:
        key = normalize(value)
        if key not in lookup:
            raise InvalidInput(
                f"{axis} {value!r} is not in this collection; choose from "
                f"{', '.join(str(a) for a in available)}."
            )
        picked.append(lookup[key])
    return list(dict.fromkeys(picked))


def _plan_requests(
    entry: _Entry,
    variables: list[str] | None,
    scenarios: list[str] | None,
    percentiles: list[float] | None,
    seasons: list[str] | None,
    averaging_periods: list[str] | None,
    start: str | None,
    end: str | None,
    notes: list[str],
) -> tuple[list[_Request], int]:
    """Expand the selection into one request per upstream call; also count time steps."""
    collection = entry.collection
    names = [v.name for v in collection.variables]
    if variables:
        unknown = [v for v in variables if v not in names]
        if unknown:
            raise InvalidInput(
                f"Unknown variable(s) {unknown} for {collection.id}; choose from {', '.join(names)}."
            )
        chosen_vars = list(dict.fromkeys(variables))
    else:
        chosen_vars = names[:1]
        if len(names) > 1:
            notes.append(
                f"No variable given: returned {names[0]}; this collection also has "
                f"{', '.join(names[1:])}."
            )
    pct_default = (
        [50.0]
        if 50.0 in collection.percentiles
        else collection.percentiles[
            len(collection.percentiles) // 2 : len(collection.percentiles) // 2 + 1
        ]
    )
    chosen_scen = _pick(scenarios, collection.scenarios, "scenarios", collection.scenarios, _norm)
    chosen_pct = _pick(percentiles, collection.percentiles, "percentiles", pct_default, float)
    chosen_season = _pick(seasons, collection.seasons, "seasons", collection.seasons, str.upper)
    chosen_avg = _pick(
        averaging_periods,
        collection.averaging_periods,
        "averaging_periods",
        collection.averaging_periods,
    )

    time_range = collection.time_range
    if time_range is None and (start or end):
        raise InvalidInput(
            f"{collection.id} has no time axis to filter (an averaged or trend set); "
            "leave start/end empty" + (" and use averaging_periods." if entry.avg_axis else ".")
        )
    datetimes: list[tuple[str | None, str | None]] = [(None, None)]
    n_steps = 1
    if time_range is not None:
        resolution = time_range.resolution
        lo = _normalize_time(time_range.start, resolution, is_end=False, label="extent start")
        hi = _normalize_time(time_range.end, resolution, is_end=True, label="extent end")
        first = _normalize_time(start, resolution, is_end=False, label="start") if start else lo
        last = _normalize_time(end, resolution, is_end=True, label="end") if end else hi
        if first > last:
            raise InvalidInput(f"start {first} is after end {last}.")
        if first < lo or last > hi:
            raise InvalidInput(f"{collection.id} covers {lo} to {hi}; requested {first} to {last}.")
        steps = _steps(first, last, resolution)
        n_steps = len(steps)
        if _is_projected(entry):
            if not start and not end:
                steps = [hi]
                n_steps = 1
                notes.append(f"No start/end given: returned the latest step, {hi}.")
            datetimes = [(s, s) for s in steps]
        else:
            dt = first if first == last else f"{first}/{last}"
            datetimes = [(dt, None)]

    requests = [
        _Request(var, scen, pct, season, avg, dt, label)
        for var, scen, pct, season, avg, (dt, label) in itertools.product(
            chosen_vars, chosen_scen, chosen_pct, chosen_season, chosen_avg, datetimes
        )
    ]
    if len(requests) > constants.MAX_REQUESTS:
        raise InvalidInput(
            f"This selection needs {len(requests)} upstream requests (one per variable x "
            f"scenario x percentile x season x averaging period"
            f"{' x time step' if _is_projected(entry) else ''}); the limit is "
            f"{constants.MAX_REQUESTS}. Name fewer variables, scenarios, percentiles or "
            "seasons, or a shorter time range."
        )
    return requests, (1 if _is_projected(entry) else n_steps)


def _bbox_for(
    entry: _Entry,
    lat: float | None,
    lon: float | None,
    bbox: list[float] | None,
) -> tuple[list[float], bool]:
    extent_bbox, resolution = _grid(entry.detail)
    if (lat is None) != (lon is None):
        raise InvalidInput("Give both lat and lon for a point, or neither.")
    point = lat is not None and lon is not None
    if point == (bbox is not None):
        raise InvalidInput("Give either a point (lat and lon) or a bbox, not both and not neither.")
    if point:
        assert lat is not None and lon is not None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise InvalidInput(f"lat/lon out of range: {lat}, {lon}.")
        if _is_projected(entry) or resolution is None:
            pad = 0.1
        else:
            pad = max(resolution)
        box = [lon - pad, lat - pad, lon + pad, lat + pad]
    else:
        assert bbox is not None
        if len(bbox) != 4:
            raise InvalidInput(f"bbox must be [west, south, east, north], got {len(bbox)} values.")
        box = [float(v) for v in bbox]
        if box[0] >= box[2] or box[1] >= box[3]:
            raise InvalidInput(
                "bbox must be [west, south, east, north] with west < east, south < north."
            )
    if extent_bbox is not None:
        w, s, e, n = extent_bbox
        if point and not (
            w <= box[0] + (box[2] - box[0]) / 2 <= e and s <= box[1] + (box[3] - box[1]) / 2 <= n
        ):
            raise InvalidInput(
                f"Point ({lat}, {lon}) is outside {entry.collection.id}'s extent "
                f"[{w}, {s}, {e}, {n}]."
            )
        box = [max(box[0], w), max(box[1], s), min(box[2], e), min(box[3], n)]
        if box[0] >= box[2] or box[1] >= box[3]:
            raise InvalidInput(f"bbox does not overlap the collection extent [{w}, {s}, {e}, {n}].")
    return box, point


def _estimated_cells(entry: _Entry, box: list[float]) -> int:
    _, resolution = _grid(entry.detail)
    if resolution is None:
        return 1
    rx, ry = resolution
    if _is_projected(entry):
        rx, ry = rx / 111_000, ry / 111_000
    return (math.ceil((box[2] - box[0]) / rx) + 1) * (math.ceil((box[3] - box[1]) / ry) + 1)


async def _coverage(
    collection_id: str, params: dict[str, Any]
) -> tuple[dict[str, Any] | None, bool]:
    key = f"eccc:coverage:{collection_id}:{sorted(params.items())}"
    segment = _segment(collection_id)

    async def fetch() -> dict[str, Any] | None:
        return await _fetch(
            f"/collections/{segment}/coverage", params, timeout=constants.COVERAGE_TIMEOUT_SECONDS
        )

    return await cached_fetch(key, constants.CACHE_TTL_COVERAGE_SECONDS, fetch)


def _params(entry: _Entry, request: _Request, box: list[float]) -> dict[str, Any]:
    params: dict[str, Any] = {
        "f": "json",
        "bbox": ",".join(f"{v:.6f}".rstrip("0").rstrip(".") for v in box),
        "properties": request.variable,
    }
    subset = []
    if request.scenario is not None:
        subset.append(f"scenario({request.scenario})")
    if request.percentile is not None:
        subset.append(f"percentile({_format_percentile(request.percentile)})")
    if request.season is not None:
        subset.append(f"season({request.season})")
    if request.averaging_period is not None and entry.avg_axis:
        subset.append(f"{entry.avg_axis}({request.averaging_period})")
    if subset:
        params["subset"] = ",".join(subset)
    if request.datetime is not None:
        params["datetime"] = request.datetime
    return params


async def get_coverage_data(
    collection_id: str,
    *,
    lat: float | None = None,
    lon: float | None = None,
    bbox: list[float] | None = None,
    variables: list[str] | None = None,
    scenarios: list[str] | None = None,
    percentiles: list[float] | None = None,
    seasons: list[str] | None = None,
    averaging_periods: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    max_rows: int = constants.ROWS_DEFAULT,
    lang: str = "en",
) -> CoverageData:
    collection_id = _require_collection(collection_id)
    if max_rows < 1 or max_rows > constants.ROWS_MAX:
        raise InvalidInput(f"max_rows must be between 1 and {constants.ROWS_MAX}, got {max_rows}.")
    if collection_id not in await _coverage_ids():
        raise NotFound(
            f"No climate coverage collection {collection_id!r}. Use eccc_coverages_search "
            "to list the ids."
        )
    entry, _ = await _entry(collection_id)
    notes: list[str] = []
    box, point = _bbox_for(entry, lat, lon, bbox)
    requests, n_steps = _plan_requests(
        entry, variables, scenarios, percentiles, seasons, averaging_periods, start, end, notes
    )
    estimate = _estimated_cells(entry, box) * n_steps * len(requests)
    if estimate > constants.MAX_ESTIMATED_VALUES:
        raise InvalidInput(
            f"This request would return about {estimate:,} grid values (bbox cells x time "
            f"steps x requests); the limit is {constants.MAX_ESTIMATED_VALUES:,}. Use a "
            "smaller bbox, a point (lat/lon), fewer years or fewer selections."
        )

    semaphore = asyncio.Semaphore(constants.COVERAGE_CONCURRENCY)

    async def run(request: _Request) -> tuple[_Request, dict[str, Any] | None, bool]:
        async with semaphore:
            payload, cached = await _coverage(collection_id, _params(entry, request, box))
            return request, payload, cached

    results = await asyncio.gather(*(run(r) for r in requests))

    rows: list[CoverageRow] = []
    skipped = 0
    distance: float | None = None
    schema_units = {v.name: v.unit for v in entry.collection.variables}
    for request, payload, _ in results:
        if payload is None:
            continue
        cells, n_time, unit = _cells(payload, request.variable, entry.collection.family, notes)
        domain_t = payload["domain"]["axes"].get("t") if n_time else None
        labels = _time_labels(domain_t, n_time, notes) if n_time else [request.time_label]
        if point:
            assert lat is not None and lon is not None
            with_data = [c for c in cells if any(v is not None for v in c.values)]
            if not with_data:
                continue
            best = min(with_data, key=lambda c: _distance_km(lat, lon, c.lat, c.lon))
            d = _distance_km(lat, lon, best.lat, best.lon)
            distance = d if distance is None else max(distance, d)
            cells = [best]
        for cell in cells:
            for label, value in zip(labels, cell.values, strict=True):
                if value is None:
                    skipped += 1
                    continue
                rows.append(
                    CoverageRow(
                        time=label,
                        value=value,
                        unit=unit or schema_units.get(request.variable),
                        variable=request.variable,
                        scenario=request.scenario,
                        percentile=request.percentile,
                        season=request.season,
                        averaging_period=request.averaging_period,
                        lat=cell.lat,
                        lon=cell.lon,
                    )
                )
    if not rows:
        where = f"point ({lat}, {lon})" if point else f"bbox {box}"
        raise NotFound(
            f"{collection_id} has no data at {where}: no grid cell centre falls inside it, or "
            "every cell is outside the data mask (ocean or outside Canada). Try a point "
            "further inland or a larger bbox."
        )
    total = len(rows)
    url = f"{constants.BASE_URL}/collections/{collection_id}/coverage"
    return CoverageData(
        collection_id=collection_id,
        rows=rows[:max_rows],
        total_rows=total,
        truncated=total > max_rows,
        missing_values_skipped=skipped,
        requests_made=len(requests),
        point_distance_km=round(distance, 2) if distance is not None else None,
        notes=notes,
        provenance=make_provenance(
            source=_SOURCE,
            url=url,
            cached=all(cached for _, _, cached in results),
            schema_name="eccc.CoverageData",
            coverage=f"{min(total, max_rows)} of {total} values from {len(requests)} request(s)",
            limits=(
                f"max_rows capped at {constants.ROWS_MAX}; at most {constants.MAX_REQUESTS} "
                f"upstream requests and about {constants.MAX_ESTIMATED_VALUES:,} grid values "
                "per call"
            ),
            licence=_licence(lang),
            lang=lang,
        ),
    )
