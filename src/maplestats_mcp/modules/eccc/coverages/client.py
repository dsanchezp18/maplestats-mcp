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
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

_SOURCE = "eccc"
_AVG_AXIS = re.compile(r"^P\d+Y-Avg$")
_YEAR = re.compile(r"^\d{4}$")
_MONTH = re.compile(r"^\d{4}-\d{2}$")

# English as before, or the French text in its typed template.
_raise = eccc_client._raise

# The variable titles and units come from /schema, which answers in English
# whatever `lang` is (checked live 2026-10-04 on CanDCS-U6: "Mean daily mean
# temperature" with lang=fr), while titles and descriptions have French text.
_ENGLISH_ONLY_NOTE_FR = (
    "Les titres et unités des variables ne sont publiés qu'en anglais par la source ; ils "
    "sont reproduits tels quels."
)

_FAMILY_NOTES_FR = {
    "candcsu6": "CanDCS-U6 : modèles CMIP6 à échelle réduite par méthode statistique (BCCAQv2) "
    "sur une grille de 1/12 de degré ; les valeurs sont des percentiles de l'ensemble de 26 "
    "modèles.",
    "cmip5": "Ensemble de modèles mondiaux CMIP5 sur une grille de 1 degré ; les valeurs sont "
    "des percentiles de l'ensemble.",
    "dcs": "DCS : modèles CMIP5 à échelle réduite par méthode statistique (BCCAQv2) sur une "
    "grille de 1/12 de degré.",
    "indices": "Indices climatiques à échelle réduite (CMIP5, 1/12 de degré) : degrés-jours, "
    "durée de la saison de croissance, nuits chaudes et journées chaudes, jours de pluie.",
    "spei-1": "SPEI-1 : indice normalisé de précipitations et d'évapotranspiration sur 1 mois "
    "(CMIP5, 1 degré) ; une valeur négative indique des conditions plus sèches que la normale.",
    "spei-3": "SPEI-3 : indice normalisé de précipitations et d'évapotranspiration sur 3 mois.",
    "spei-12": "SPEI-12 : indice normalisé de précipitations et d'évapotranspiration sur 12 mois.",
    "cangrd": "CanGRD : anomalies observées de température et de précipitations sur grille "
    "(par rapport à 1961-1990) et tendances, à partir des données des stations.",
}


def _note(en: str, fr: str, lang: str) -> str:
    return french_spacing(fr) if lang == "fr" else en


def _fr_int(n: int) -> str:
    """A count with the French no-break space as thousands separator."""
    return f"{n:,}".replace(",", "\u00a0")


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


def _raise_for(exc: httpx.HTTPStatusError, context: str, lang: str = "en") -> NoReturn:
    status = exc.response.status_code
    detail = _description(exc)
    # The server's own descriptions ("Invalid field specified") are English only.
    source_fr = f" (message de la source, en anglais : {detail})" if detail else ""
    if status == 404:
        _raise(
            NotFound,
            f"{context}: {detail or 'not found'} (HTTP 404).",
            f"{context} : introuvable (HTTP 404){source_fr}.",
            lang,
            exc,
        )
    if status == 400:
        _raise(
            InvalidInput,
            f"{context}: {detail or 'rejected'} (HTTP 400).",
            f"{context} : requête refusée (HTTP 400){source_fr}.",
            lang,
            exc,
        )
    _raise(
        UpstreamError,
        f"{context}: upstream returned HTTP {status}"
        f"{': ' + detail if detail else ''}. The selection was checked against the "
        "collection's own axes first, so this is a server-side failure; retry, or narrow "
        "the variables, years or bbox.",
        f"{context} : la source a renvoyé HTTP {status}{source_fr}. La sélection a été "
        "vérifiée d'abord contre les axes de la collection ; il s'agit donc d'une panne du "
        "serveur. Réessayez, ou réduisez les variables, les années ou la bbox.",
        lang,
        exc,
    )


async def _fetch(
    path: str, params: dict[str, Any], timeout: float = 30.0, lang: str = "en"
) -> Any | None:
    """GET JSON; None for HTTP 204 (no grid cell inside the bbox)."""
    await _limiter().acquire()
    url = f"{constants.BASE_URL}{path}"
    try:
        response = await get_raw(url, params=params, timeout=timeout)
    except httpx.HTTPStatusError as exc:
        _raise_for(exc, path, lang)
    except httpx.HTTPError as exc:
        _raise(
            UpstreamUnavailable,
            f"{path} did not respond (already retried): {type(exc).__name__}.",
            f"{path} n'a pas répondu (après plusieurs essais) : {type(exc).__name__}.",
            lang,
            exc,
        )
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        _raise(
            UpstreamError,
            f"{path} did not return JSON.",
            f"{path} n'a pas renvoyé de JSON.",
            lang,
            exc,
        )


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


async def _entry(collection_id: str, lang: str = "en") -> tuple[_Entry, bool]:
    segment = _segment(collection_id)

    async def fetch() -> tuple[dict[str, Any], dict[str, Any]]:
        detail = await _fetch(f"/collections/{segment}", {"f": "json"}, lang=lang)
        schema = await _fetch(f"/collections/{segment}/schema", {"f": "json"}, lang=lang)
        return detail or {}, schema or {}

    (detail, schema), was_cached = await cached_fetch(
        f"eccc:coverage-meta:{collection_id}", constants.CACHE_TTL_CATALOGUE_SECONDS, fetch
    )
    return _build_entry(collection_id, detail, schema), was_cached


async def _coverage_ids() -> list[str]:
    summaries, _ = await eccc_client._all_collections()
    return [s.id for s in summaries if s.id.startswith(constants.COLLECTION_PREFIX)]


async def _french_texts() -> dict[str, tuple[str, str]]:
    """French title and description per collection id.

    The collection list with lang=fr (one cached request shared with
    eccc_list_collections) carries them: "CanDCSU6 - Projections annuelles"
    for climate:candcsu6:projected:annual:absolute (live 2026-10-04).
    """
    summaries, _ = await eccc_client._all_collections("fr")
    return {s.id: (s.title, s.description) for s in summaries}


def _in_french(
    collection: CoverageCollection, description: str, french: dict[str, tuple[str, str]]
) -> tuple[CoverageCollection, str]:
    title_fr, description_fr = french.get(collection.id, ("", ""))
    if title_fr:
        collection = collection.model_copy(update={"title": title_fr})
    return collection, description_fr or description


async def _catalogue(lang: str = "en") -> tuple[list[_Entry], bool]:
    ids = await _coverage_ids()
    semaphore = asyncio.Semaphore(constants.CATALOGUE_CONCURRENCY)

    async def one(cid: str) -> tuple[_Entry, bool]:
        async with semaphore:
            return await _entry(cid, lang)

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
        _raise(
            InvalidInput,
            f"limit must be between 1 and 100, got {limit}.",
            f"limit doit être compris entre 1 et 100 ; valeur reçue : {limit}.",
            lang,
        )
    entries, was_cached = await _catalogue(lang)
    french = await _french_texts() if lang == "fr" else {}
    words = [w for w in query.lower().split() if w]
    matches = []
    for e in entries:
        collection = e.collection
        description = str(e.detail.get("description", ""))
        if lang == "fr":
            # French words match the French title and description, English
            # words (and variable names) still match the English text.
            english = f"{collection.title} {description}"
            collection, description = _in_french(collection, description, french)
            description = f"{description} {english}"
        if _matches(collection, description, words, scenario, variable, timeframe, frequency, year):
            matches.append(collection)
    coverage = _note(
        f"{len(matches)} of {len(entries)} climate coverage collections matched",
        f"{len(matches)} des {len(entries)} collections de données climatiques sur grille "
        "correspondent",
        lang,
    )
    return CoverageCollectionList(
        collections=matches[:limit],
        total_count=len(matches),
        provenance=make_provenance(
            source=_SOURCE,
            url=f"{constants.BASE_URL}/collections?f=json",
            cached=was_cached,
            schema_name="eccc.CoverageCollectionList",
            coverage=coverage,
            limits=french_spacing(_ENGLISH_ONLY_NOTE_FR) if lang == "fr" else None,
            licence=_licence(lang),
            lang=lang,
        ),
    )


def _require_collection(collection_id: str, lang: str = "en") -> str:
    collection_id = collection_id.strip()
    if not collection_id.startswith(constants.COLLECTION_PREFIX):
        _raise(
            InvalidInput,
            f"collection_id must be a climate coverage id starting with 'climate:' "
            f"(e.g. climate:candcsu6:projected:annual:absolute), got {collection_id!r}. "
            "Use eccc_coverages_search to find one; feature collections such as "
            "climate-daily are read with eccc_query_items.",
            "collection_id doit être un identifiant de données climatiques sur grille "
            "commençant par 'climate:' (p. ex. climate:candcsu6:projected:annual:absolute) ; "
            f"valeur reçue : {collection_id!r}. Trouvez-en un avec eccc_coverages_search ; "
            "les collections d'entités comme climate-daily se lisent avec eccc_query_items.",
            lang,
        )
    return collection_id


def _no_collection(collection_id: str, lang: str) -> NoReturn:
    _raise(
        NotFound,
        f"No climate coverage collection {collection_id!r}. Use eccc_coverages_search "
        "to list the ids.",
        f"aucune collection de données climatiques sur grille {collection_id!r}. "
        "eccc_coverages_search donne la liste des identifiants.",
        lang,
    )


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
    collection_id = _require_collection(collection_id, lang)
    if collection_id not in await _coverage_ids():
        _no_collection(collection_id, lang)
    entry, was_cached = await _entry(collection_id, lang)
    bbox, resolution = _grid(entry.detail)
    family = entry.collection.family
    notes = (
        [_note(_FAMILY_NOTES[family], _FAMILY_NOTES_FR[family], lang)]
        if family in _FAMILY_NOTES
        else []
    )
    if entry.collection.scenarios:
        notes.append(
            _note(
                "Without a scenario the server would use the first one; eccc_coverages_get_data "
                "always names the scenario, percentile, season and averaging period it asks for.",
                "Sans scénario précisé, le serveur prendrait le premier ; "
                "eccc_coverages_get_data nomme toujours le scénario, le percentile, la saison "
                "et la période de calcul de la moyenne demandés.",
                lang,
            )
        )
    if entry.avg_axis:
        notes.append(
            _note(
                "Averaged set: one value per window; pick windows with `averaging_periods`, "
                "not start/end years.",
                "Jeu de moyennes : une valeur par période ; choisissez les périodes avec "
                "`averaging_periods`, et non avec des années de début et de fin.",
                lang,
            )
        )
    if _is_projected(entry):
        notes.append(
            _note(
                "Grid cells are on a polar stereographic grid (EPSG:3995); rows give each cell's "
                "centre converted to latitude/longitude. One request per year or month.",
                "Les cellules sont sur une grille stéréographique polaire (EPSG:3995) ; les "
                "lignes donnent le centre de chaque cellule converti en latitude et longitude. "
                "Une requête par année ou par mois.",
                lang,
            )
        )
    description = str(entry.detail.get("description", ""))
    collection = entry.collection
    if lang == "fr":
        collection, description = _in_french(collection, description, await _french_texts())
        notes.append(french_spacing(_ENGLISH_ONLY_NOTE_FR))
    links = entry.detail.get("links") or []
    canonical = next(
        (
            link.get("href")
            for link in links
            if link.get("rel") == "canonical" and isinstance(link.get("href"), str)
        ),
        None,
    )
    data = collection.model_dump()
    return CoverageDescription(
        **data,
        description=description,
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


def _time_labels(
    domain_t: dict[str, Any] | None, count: int, notes: list[str], lang: str = "en"
) -> list[str | None]:
    if domain_t is None:
        return [None] * count
    values = [str(v) for v in list_or_empty(domain_t, "values")]
    if len(values) == count:
        labels: list[str | None] = list(values)
        return labels
    if len(values) == 2 and count > 2 and re.match(r"^\d{4}-\d{2}", values[0]):
        note = _note(
            f"The source gave only the first and last timestamps ({values[0]}, {values[1]}) "
            f"for {count} monthly values; months were numbered forward from the first.",
            f"La source n'a donné que le premier et le dernier horodatage ({values[0]}, "
            f"{values[1]}) pour {count} valeurs mensuelles ; les mois ont été numérotés à "
            "partir du premier.",
            lang,
        )
        if note not in notes:
            notes.append(note)
        return [_add_months(values[0][:7], i) for i in range(count)]
    _raise(
        UpstreamError,
        f"Coverage time axis has {len(values)} labels for {count} values; cannot align them.",
        f"l'axe du temps de la réponse compte {len(values)} étiquettes pour {count} valeurs ; "
        "impossible de les aligner.",
        lang,
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
    payload: dict[str, Any], variable: str, family: str, notes: list[str], lang: str = "en"
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
            _raise(
                UpstreamError,
                f"Coverage response has no range for variable {variable!r}.",
                f"la réponse ne contient aucune plage pour la variable {variable!r}.",
                lang,
            )
        key = next(iter(ranges))
        note = _note(
            f"The source names {variable} {key!r} in its data response.",
            f"La source nomme {variable} {key!r} dans sa réponse.",
            lang,
        )
        if note not in notes:
            notes.append(note)
    rng = ranges[key]
    names: list[str] = list(rng.get("axisNames") or [])
    shape: list[int] = [int(n) for n in rng.get("shape") or []]
    values: list[Any] = list(rng.get("values") or [])
    if len(names) != len(shape) or math.prod(shape) != len(values):
        _raise(
            UpstreamError,
            "Coverage range shape does not match its values.",
            "la forme de la plage de la réponse ne correspond pas à ses valeurs.",
            lang,
        )
    xs = _axis_coords(axes["x"])
    ys = _axis_coords(axes["y"])
    size = dict(zip(names, shape, strict=True))
    nx, ny, n_time = size.get("x", 1), size.get("y", 1), size.get("t", 1)
    if len(xs) != nx or len(ys) != ny:
        _raise(
            UpstreamError,
            "Coverage domain size does not match its range shape.",
            "la taille du domaine de la réponse ne correspond pas à la forme de sa plage.",
            lang,
        )
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


def _normalize_time(
    value: str, resolution: str | None, *, is_end: bool, label: str, lang: str = "en"
) -> str:
    value = value.strip()
    if resolution == "P1M":
        if _YEAR.match(value):
            return f"{value}-12" if is_end else f"{value}-01"
        if _MONTH.match(value):
            return value
        _raise(
            InvalidInput,
            f"{label} must be YYYY or YYYY-MM for this monthly set, got {value!r}.",
            f"{label} doit être au format AAAA ou AAAA-MM pour ce jeu mensuel ; "
            f"valeur reçue : {value!r}.",
            lang,
        )
    if _YEAR.match(value):
        return value
    if _MONTH.match(value):
        _raise(
            InvalidInput,
            f"{label} must be a year (YYYY) for this annual/seasonal set.",
            f"{label} doit être une année (AAAA) pour ce jeu annuel ou saisonnier.",
            lang,
        )
    _raise(
        InvalidInput,
        f"{label} must be a year (YYYY), got {value!r}.",
        f"{label} doit être une année (AAAA) ; valeur reçue : {value!r}.",
        lang,
    )


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
    lang: str = "en",
) -> list[Any]:
    if not available:
        if requested:
            _raise(
                InvalidInput,
                f"This collection has no {axis} axis; leave `{axis}` empty.",
                f"cette collection n'a pas d'axe {axis} ; laissez `{axis}` vide.",
                lang,
            )
        return [None]
    if not requested:
        return default
    lookup = {normalize(a): a for a in available}
    picked = []
    for value in requested:
        key = normalize(value)
        if key not in lookup:
            choices = ", ".join(str(a) for a in available)
            _raise(
                InvalidInput,
                f"{axis} {value!r} is not in this collection; choose from {choices}.",
                f"{axis} {value!r} n'existe pas dans cette collection ; choisissez parmi "
                f"{choices}.",
                lang,
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
    lang: str = "en",
) -> tuple[list[_Request], int]:
    """Expand the selection into one request per upstream call; also count time steps."""
    collection = entry.collection
    names = [v.name for v in collection.variables]
    if variables:
        unknown = [v for v in variables if v not in names]
        if unknown:
            _raise(
                InvalidInput,
                f"Unknown variable(s) {unknown} for {collection.id}; choose from {', '.join(names)}.",
                f"variable(s) inconnue(s) {unknown} pour {collection.id} ; choisissez parmi "
                f"{', '.join(names)}.",
                lang,
            )
        chosen_vars = list(dict.fromkeys(variables))
    else:
        chosen_vars = names[:1]
        if len(names) > 1:
            notes.append(
                _note(
                    f"No variable given: returned {names[0]}; this collection also has "
                    f"{', '.join(names[1:])}.",
                    f"Aucune variable précisée : {names[0]} est renvoyée ; cette collection a "
                    f"aussi {', '.join(names[1:])}.",
                    lang,
                )
            )
    pct_default = (
        [50.0]
        if 50.0 in collection.percentiles
        else collection.percentiles[
            len(collection.percentiles) // 2 : len(collection.percentiles) // 2 + 1
        ]
    )
    chosen_scen = _pick(
        scenarios, collection.scenarios, "scenarios", collection.scenarios, _norm, lang
    )
    chosen_pct = _pick(percentiles, collection.percentiles, "percentiles", pct_default, float, lang)
    chosen_season = _pick(
        seasons, collection.seasons, "seasons", collection.seasons, str.upper, lang
    )
    chosen_avg = _pick(
        averaging_periods,
        collection.averaging_periods,
        "averaging_periods",
        collection.averaging_periods,
        str,
        lang,
    )

    time_range = collection.time_range
    if time_range is None and (start or end):
        _raise(
            InvalidInput,
            f"{collection.id} has no time axis to filter (an averaged or trend set); "
            "leave start/end empty" + (" and use averaging_periods." if entry.avg_axis else "."),
            f"{collection.id} n'a pas d'axe du temps à filtrer (jeu de moyennes ou de "
            "tendances) ; laissez start/end vides"
            + (" et utilisez averaging_periods." if entry.avg_axis else "."),
            lang,
        )
    datetimes: list[tuple[str | None, str | None]] = [(None, None)]
    n_steps = 1
    if time_range is not None:
        resolution = time_range.resolution
        lo = _normalize_time(
            time_range.start, resolution, is_end=False, label="extent start", lang=lang
        )
        hi = _normalize_time(time_range.end, resolution, is_end=True, label="extent end", lang=lang)
        first = (
            _normalize_time(start, resolution, is_end=False, label="start", lang=lang)
            if start
            else lo
        )
        last = _normalize_time(end, resolution, is_end=True, label="end", lang=lang) if end else hi
        if first > last:
            _raise(
                InvalidInput,
                f"start {first} is after end {last}.",
                f"start {first} est postérieur à end {last}.",
                lang,
            )
        if first < lo or last > hi:
            _raise(
                InvalidInput,
                f"{collection.id} covers {lo} to {hi}; requested {first} to {last}.",
                f"{collection.id} couvre {lo} à {hi} ; période demandée : {first} à {last}.",
                lang,
            )
        steps = _steps(first, last, resolution)
        n_steps = len(steps)
        if _is_projected(entry):
            if not start and not end:
                steps = [hi]
                n_steps = 1
                notes.append(
                    _note(
                        f"No start/end given: returned the latest step, {hi}.",
                        f"Aucun start/end précisé : le pas le plus récent, {hi}, est renvoyé.",
                        lang,
                    )
                )
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
        _raise(
            InvalidInput,
            f"This selection needs {len(requests)} upstream requests (one per variable x "
            f"scenario x percentile x season x averaging period"
            f"{' x time step' if _is_projected(entry) else ''}); the limit is "
            f"{constants.MAX_REQUESTS}. Name fewer variables, scenarios, percentiles or "
            "seasons, or a shorter time range.",
            f"cette sélection exige {len(requests)} requêtes à la source (une par variable x "
            f"scénario x percentile x saison x période de moyenne"
            f"{' x pas de temps' if _is_projected(entry) else ''}) ; la limite est de "
            f"{constants.MAX_REQUESTS}. Nommez moins de variables, de scénarios, de "
            "percentiles ou de saisons, ou une période plus courte.",
            lang,
        )
    return requests, (1 if _is_projected(entry) else n_steps)


def _bbox_for(
    entry: _Entry,
    lat: float | None,
    lon: float | None,
    bbox: list[float] | None,
    lang: str = "en",
) -> tuple[list[float], bool]:
    extent_bbox, resolution = _grid(entry.detail)
    if (lat is None) != (lon is None):
        _raise(
            InvalidInput,
            "Give both lat and lon for a point, or neither.",
            "donnez à la fois lat et lon pour un point, ou ni l'un ni l'autre.",
            lang,
        )
    point = lat is not None and lon is not None
    if point == (bbox is not None):
        _raise(
            InvalidInput,
            "Give either a point (lat and lon) or a bbox, not both and not neither.",
            "donnez soit un point (lat et lon), soit une bbox, mais pas les deux ni aucun.",
            lang,
        )
    if point:
        assert lat is not None and lon is not None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            _raise(
                InvalidInput,
                f"lat/lon out of range: {lat}, {lon}.",
                f"lat/lon hors limites : {lat}, {lon}.",
                lang,
            )
        if _is_projected(entry) or resolution is None:
            pad = 0.1
        else:
            pad = max(resolution)
        box = [lon - pad, lat - pad, lon + pad, lat + pad]
    else:
        assert bbox is not None
        if len(bbox) != 4:
            _raise(
                InvalidInput,
                f"bbox must be [west, south, east, north], got {len(bbox)} values.",
                f"bbox doit être [ouest, sud, est, nord] ; {len(bbox)} valeurs reçues.",
                lang,
            )
        box = [float(v) for v in bbox]
        if box[0] >= box[2] or box[1] >= box[3]:
            _raise(
                InvalidInput,
                "bbox must be [west, south, east, north] with west < east, south < north.",
                "bbox doit être [ouest, sud, est, nord] avec ouest < est et sud < nord.",
                lang,
            )
    if extent_bbox is not None:
        w, s, e, n = extent_bbox
        if point and not (
            w <= box[0] + (box[2] - box[0]) / 2 <= e and s <= box[1] + (box[3] - box[1]) / 2 <= n
        ):
            _raise(
                InvalidInput,
                f"Point ({lat}, {lon}) is outside {entry.collection.id}'s extent "
                f"[{w}, {s}, {e}, {n}].",
                f"le point ({lat}, {lon}) est hors de l'étendue de {entry.collection.id} "
                f"[{w}, {s}, {e}, {n}].",
                lang,
            )
        box = [max(box[0], w), max(box[1], s), min(box[2], e), min(box[3], n)]
        if box[0] >= box[2] or box[1] >= box[3]:
            _raise(
                InvalidInput,
                f"bbox does not overlap the collection extent [{w}, {s}, {e}, {n}].",
                f"la bbox ne recoupe pas l'étendue de la collection [{w}, {s}, {e}, {n}].",
                lang,
            )
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
    collection_id: str, params: dict[str, Any], lang: str = "en"
) -> tuple[dict[str, Any] | None, bool]:
    key = f"eccc:coverage:{collection_id}:{sorted(params.items())}"
    segment = _segment(collection_id)

    async def fetch() -> dict[str, Any] | None:
        return await _fetch(
            f"/collections/{segment}/coverage",
            params,
            timeout=constants.COVERAGE_TIMEOUT_SECONDS,
            lang=lang,
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
    collection_id = _require_collection(collection_id, lang)
    if max_rows < 1 or max_rows > constants.ROWS_MAX:
        _raise(
            InvalidInput,
            f"max_rows must be between 1 and {constants.ROWS_MAX}, got {max_rows}.",
            f"max_rows doit être compris entre 1 et {constants.ROWS_MAX} ; "
            f"valeur reçue : {max_rows}.",
            lang,
        )
    if collection_id not in await _coverage_ids():
        _no_collection(collection_id, lang)
    entry, _ = await _entry(collection_id, lang)
    notes: list[str] = []
    box, point = _bbox_for(entry, lat, lon, bbox, lang)
    requests, n_steps = _plan_requests(
        entry,
        variables,
        scenarios,
        percentiles,
        seasons,
        averaging_periods,
        start,
        end,
        notes,
        lang,
    )
    estimate = _estimated_cells(entry, box) * n_steps * len(requests)
    if estimate > constants.MAX_ESTIMATED_VALUES:
        cap = constants.MAX_ESTIMATED_VALUES
        _raise(
            InvalidInput,
            f"This request would return about {estimate:,} grid values (bbox cells x time "
            f"steps x requests); the limit is {cap:,}. Use a "
            "smaller bbox, a point (lat/lon), fewer years or fewer selections.",
            f"cette requête renverrait environ {_fr_int(estimate)} valeurs de grille "
            f"(cellules de la bbox x pas de temps x requêtes) ; la limite est de "
            f"{_fr_int(cap)}. Prenez une bbox plus petite, un point (lat/lon), moins "
            "d'années ou moins de sélections.",
            lang,
        )

    semaphore = asyncio.Semaphore(constants.COVERAGE_CONCURRENCY)

    async def run(request: _Request) -> tuple[_Request, dict[str, Any] | None, bool]:
        async with semaphore:
            payload, cached = await _coverage(collection_id, _params(entry, request, box), lang)
            return request, payload, cached

    results = await asyncio.gather(*(run(r) for r in requests))

    rows: list[CoverageRow] = []
    skipped = 0
    distance: float | None = None
    schema_units = {v.name: v.unit for v in entry.collection.variables}
    for request, payload, _ in results:
        if payload is None:
            continue
        cells, n_time, unit = _cells(
            payload, request.variable, entry.collection.family, notes, lang
        )
        domain_t = payload["domain"]["axes"].get("t") if n_time else None
        labels = _time_labels(domain_t, n_time, notes, lang) if n_time else [request.time_label]
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
        where_fr = f"au point ({lat}, {lon})" if point else f"dans la bbox {box}"
        _raise(
            NotFound,
            f"{collection_id} has no data at {where}: no grid cell centre falls inside it, or "
            "every cell is outside the data mask (ocean or outside Canada). Try a point "
            "further inland or a larger bbox.",
            f"{collection_id} n'a pas de données {where_fr} : aucun centre de cellule n'y "
            "tombe, ou toutes les cellules sont hors du masque de données (océan ou hors du "
            "Canada). Essayez un point plus à l'intérieur des terres ou une bbox plus grande.",
            lang,
        )
    total = len(rows)
    shown = min(total, max_rows)
    coverage = _note(
        f"{shown} of {total} values from {len(requests)} request(s)",
        f"{shown} valeurs sur {total}, tirées de {len(requests)} requête(s)",
        lang,
    )
    limits = _note(
        f"max_rows capped at {constants.ROWS_MAX}; at most {constants.MAX_REQUESTS} "
        f"upstream requests and about {constants.MAX_ESTIMATED_VALUES:,} grid values "
        "per call",
        f"max_rows plafonné à {constants.ROWS_MAX} ; au plus {constants.MAX_REQUESTS} "
        f"requêtes à la source et environ {_fr_int(constants.MAX_ESTIMATED_VALUES)} valeurs "
        "de grille par appel",
        lang,
    )
    if lang == "fr":
        notes.append(french_spacing(_ENGLISH_ONLY_NOTE_FR))
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
            coverage=coverage,
            limits=limits,
            licence=_licence(lang),
            lang=lang,
        ),
    )
