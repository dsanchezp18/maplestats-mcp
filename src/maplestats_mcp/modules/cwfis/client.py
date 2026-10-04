"""CWFIS client: GeoServer WFS layers plus the situation-report API.

Live quirks (confirmed 2026-09-29) this file relies on:

- A spatial CQL filter needs the CRS spelled out: `BBOX(geom,x1,y1,x2,y2,'EPSG:4326')`
  matches, while the bare form returns 0 rows; point tests use
  `INTERSECTS(the_geom, SRID=4326;POINT(lon lat))`. `DWITHIN` returned stations
  hundreds of km away (degree/axis confusion), so radius searches use a bbox
  and a haversine filter in Python instead.
- The geometry column is `geometry` on hotspot/perimeter layers and `the_geom`
  on the station, forecast, danger and NFDB layers.
- Station names are space-padded; the station layer uses NF for NL and SA for SK.
- The archive `hotspots` layer is 18.5 million rows: always filter by date.
  Descending sort on `frp` puts NULLs first, so the FRP ranking is a query
  with `frp IS NOT NULL`, followed by the null-FRP rows (2023 archive rows
  mostly have none: BC on 2023-08-18 matched 9,813 detections, 0 with FRP).
- The situation-report API ignores a `type` filter, caps `limit` at 100 (HTTP 422
  above), answers 404 before 1998, and `by-date` returns the latest report on or
  before the date. Numeric totals are null for reports from 2024 on.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from maplestats_mcp.modules.cwfis import constants as c
from maplestats_mcp.modules.cwfis.schemas import (
    FireDanger,
    ForecastDay,
    ForecastResult,
    Hotspot,
    HotspotResult,
    LargeFire,
    LargeFireResult,
    Perimeter,
    PerimeterResult,
    ReportSection,
    SituationReport,
    SituationReportList,
    SituationReportSummary,
    SituationStats,
    StationResult,
    WeatherStation,
)
from maplestats_mcp.shared.arg_checks import check_range
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.fr_typography import fr_or_en, lang_error
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.licences_fr import licence_for_lang
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.rate_limiter import get_limiter
from maplestats_mcp.shared.wfs import WfsConfig, get_features

CONFIG = WfsConfig(
    source=c.RATE_LIMIT_SOURCE,
    base_url=c.WFS_URL,
    rate_limit_per_second=c.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=c.RATE_LIMIT_CAPACITY,
)
SRS = "EPSG:4326"


# ---------------------------------------------------------------- helpers


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _check_page(limit: int, offset: int, maximum: int = c.ROWS_LIMIT_MAX, lang: str = "en") -> None:
    if limit < 1 or limit > maximum:
        raise lang_error(
            InvalidInput,
            lang,
            f"limit must be between 1 and {maximum}, got {limit}.",
            f"limit doit être compris entre 1 et {maximum} ; reçu {limit}.",
        )
    if offset < 0:
        raise lang_error(
            InvalidInput,
            lang,
            f"offset must be >= 0, got {offset}.",
            f"offset doit être positif ou nul ; reçu {offset}.",
        )


def _check_range(start: Any, end: Any, start_name: str, end_name: str, lang: str) -> None:
    """shared/arg_checks.check_range, with its message in French for lang="fr"."""
    if lang != "fr":
        check_range(start, end, start_name, end_name)
    elif start is not None and end is not None and start > end:
        raise lang_error(
            InvalidInput,
            lang,
            "",
            f"{start_name} ({start}) est postérieur à {end_name} ({end}) ; inversez-les ou "
            "élargissez la plage.",
        )


def _bbox_cql(field: str, bbox: list[float], lang: str = "en") -> str:
    if len(bbox) != 4:
        raise lang_error(
            InvalidInput,
            lang,
            "bbox must be [min_lon, min_lat, max_lon, max_lat].",
            "bbox doit être [min_lon, min_lat, max_lon, max_lat].",
        )
    min_lon, min_lat, max_lon, max_lat = bbox
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise lang_error(
            InvalidInput,
            lang,
            f"bbox is not a valid lon/lat box: {bbox}.",
            f"bbox n'est pas un rectangle longitude/latitude valide : {bbox}.",
        )
    return f"BBOX({field},{min_lon},{min_lat},{max_lon},{max_lat},'{SRS}')"


def _parse_day(value: str | None, name: str, lang: str = "en") -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise lang_error(
            InvalidInput,
            lang,
            f"{name} must be YYYY-MM-DD, got {value!r}.",
            f"{name} doit être au format AAAA-MM-JJ ; reçu {value!r}.",
        ) from exc


def _dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _day(value: object) -> date | None:
    parsed = _dt(value)
    return parsed.date() if parsed else None


async def _wfs(
    type_name: str,
    *,
    cql: str | None,
    fields: str | None,
    sort_by: str | None,
    limit: int,
    offset: int,
    ttl: int,
) -> tuple[dict[str, Any], bool]:
    async def fetch() -> dict[str, Any]:
        return await get_features(
            CONFIG,
            type_name,
            cql_filter=cql,
            property_names=fields,
            srs_name=SRS,
            sort_by=sort_by,
            count=limit,
            start_index=offset,
        )

    key = f"cwfis:{type_name}:{cql}:{fields}:{sort_by}:{limit}:{offset}"
    body, cached = await cached_fetch(key, ttl, fetch)
    return body, cached


def _props(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [f.get("properties") or {} for f in body.get("features") or []]


def _total(body: dict[str, Any], fallback: int) -> int:
    return body.get("numberMatched") or body.get("totalFeatures") or fallback


def _prov(
    schema: str,
    layer: str,
    cached: bool,
    *,
    coverage: str | None = None,
    limits: str | None = None,
    freshness: str | None = None,
    lang: str = "en",
) -> Provenance:
    url = f"{c.WFS_URL}?typeName={layer}"
    return make_provenance(
        source=c.RATE_LIMIT_SOURCE,
        url=url,
        cached=cached,
        schema_name=f"cwfis.{schema}",
        coverage=coverage,
        limits=limits,
        freshness=freshness,
        licence=licence_for_lang(c.RATE_LIMIT_SOURCE, url, lang),
        lang=lang,
    )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


# --------------------------------------------------------------- hotspots

_HOTSPOT_FIELDS = (
    "lat,lon,rep_date,source,sensor,satellite,agency,frp,fwi,ffmc,isi,bui,fuel,hfi,estarea"
)


async def get_hotspots(
    *,
    agency: str | None = None,
    bbox: list[float] | None = None,
    min_frp: float | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    canada_only: bool = True,
    sort_by: str = "latest",
    limit: int = c.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> HotspotResult:
    """Satellite hotspots: last 24 hours, or the archive when dates are given."""
    _check_page(limit, offset, lang=lang)
    if sort_by not in ("latest", "frp"):
        raise lang_error(
            InvalidInput,
            lang,
            "sort_by must be 'latest' or 'frp'.",
            "sort_by doit être « latest » ou « frp ».",
        )
    start = _parse_day(start_date, "start_date", lang)
    end = _parse_day(end_date, "end_date", lang)
    _check_range(start, end, "start_date", "end_date", lang)
    archive = start is not None or end is not None
    if archive and not (start and end):
        # One open-ended side would scan up to 18.5M rows.
        raise lang_error(
            InvalidInput,
            lang,
            "Archive queries need both start_date and end_date (YYYY-MM-DD).",
            "une requête dans les archives exige start_date et end_date (AAAA-MM-JJ).",
        )
    layer = c.HOTSPOTS_ARCHIVE if archive else c.HOTSPOTS_CURRENT
    clauses: list[str] = []
    if agency:
        code = agency.strip().upper()
        if code not in (*c.CANADIAN_AGENCIES, *c.OTHER_HOTSPOT_AGENCIES):
            raise lang_error(
                InvalidInput,
                lang,
                f"agency must be a province or territory code ({', '.join(c.CANADIAN_AGENCIES)}) "
                f"or a US state code or MX, got {agency!r}.",
                f"agency doit être un code de province ou de territoire "
                f"({', '.join(c.CANADIAN_AGENCIES)}), un code d'État américain ou MX ; reçu "
                f"{agency!r}.",
            )
        clauses.append(f"agency = {_quote(code)}")
    elif canada_only:
        clauses.append("agency IN (" + ",".join(_quote(a) for a in c.CANADIAN_AGENCIES) + ")")
    if bbox:
        clauses.append(_bbox_cql("geometry", bbox, lang))
    if min_frp is not None:
        clauses.append(f"frp >= {float(min_frp)}")
    if start and end:
        clauses.append(f"rep_date >= '{start.isoformat()}T00:00:00Z'")
        clauses.append(f"rep_date < '{(end + timedelta(days=1)).isoformat()}T00:00:00Z'")
    ttl = c.CACHE_TTL_ARCHIVE if archive else c.CACHE_TTL_HOTSPOTS
    without_frp = None
    if sort_by == "frp":
        # Ranked rows first, then the rows with no FRP, so the filter never
        # hides detections or changes total_matched.
        ranked, cached = await _wfs(
            layer,
            cql=" AND ".join([*clauses, "frp IS NOT NULL"]),
            fields=_HOTSPOT_FIELDS,
            sort_by="frp D",
            limit=limit,
            offset=offset,
            ttl=ttl,
        )
        props = _props(ranked)
        ranked_total = _total(ranked, len(props))
        unranked, _ = await _wfs(
            layer,
            cql=" AND ".join([*clauses, "frp IS NULL"]),
            fields=_HOTSPOT_FIELDS,
            sort_by="rep_date D",
            limit=max(limit - len(props), 1),
            offset=max(offset - ranked_total, 0),
            ttl=ttl,
        )
        without_frp = _total(unranked, len(_props(unranked)))
        if len(props) < limit:
            props += _props(unranked)[: limit - len(props)]
        total = ranked_total + without_frp
    else:
        body, cached = await _wfs(
            layer,
            cql=" AND ".join(clauses) or None,
            fields=_HOTSPOT_FIELDS,
            sort_by="rep_date D",
            limit=limit,
            offset=offset,
            ttl=ttl,
        )
        props = _props(body)
        total = _total(body, len(props))
    rows = [
        Hotspot(
            latitude=p["lat"],
            longitude=p["lon"],
            reported_at=_dt(p.get("rep_date")),
            agency=p.get("agency"),
            source=p.get("source"),
            sensor=p.get("sensor"),
            satellite=p.get("satellite"),
            frp_mw=p.get("frp"),
            fwi=p.get("fwi"),
            ffmc=p.get("ffmc"),
            isi=p.get("isi"),
            bui=p.get("bui"),
            fuel_type=p.get("fuel"),
            head_fire_intensity=p.get("hfi"),
            estimated_area=p.get("estarea"),
        )
        for p in props
    ]
    return HotspotResult(
        hotspots=rows,
        returned_count=len(rows),
        total_matched=total,
        without_frp=without_frp,
        layer=layer,
        provenance=_prov(
            "HotspotResult",
            layer,
            cached,
            coverage=fr_or_en(
                lang,
                f"{len(rows)} of {total} matching detections returned",
                f"{len(rows)} détections renvoyées sur {total} correspondantes",
            ),
            limits=fr_or_en(
                lang,
                "current layer covers the last 24 hours; archive needs a date range",
                "la couche courante couvre les 24 dernières heures ; les archives exigent une "
                "plage de dates",
            ),
            freshness=fr_or_en(
                lang,
                "updated several times a day from NASA and EUMETSAT feeds",
                "mise à jour plusieurs fois par jour à partir des flux de la NASA et d'EUMETSAT",
            ),
            lang=lang,
        ),
    )


# ------------------------------------------------------------- perimeters


async def get_perimeters(
    *,
    bbox: list[float] | None = None,
    min_area_ha: float | None = None,
    include_geometry: bool = False,
    limit: int = c.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> PerimeterResult:
    """Current-season estimated fire perimeters, largest first."""
    _check_page(limit, offset, lang=lang)
    clauses: list[str] = []
    if bbox:
        clauses.append(_bbox_cql("geometry", bbox, lang))
    if min_area_ha is not None:
        clauses.append(f"area >= {float(min_area_ha)}")
    body, cached = await _wfs(
        c.PERIMETERS,
        cql=" AND ".join(clauses) or None,
        fields=None if include_geometry else "hcount,firstdate,lastdate,area",
        sort_by="area D",
        limit=limit,
        offset=offset,
        ttl=c.CACHE_TTL_LIVE,
    )
    rows = []
    used = 0
    features = body.get("features") or []
    for feature in features:
        p = feature.get("properties") or {}
        geometry = feature.get("geometry") if include_geometry else None
        if geometry is not None:
            used += len(json.dumps(geometry, separators=(",", ":")))
            if rows and used > c.GEOMETRY_BYTES_MAX:
                break
        rows.append(
            Perimeter(
                hotspot_count=p.get("hcount"),
                first_detected=_dt(p.get("firstdate")),
                last_detected=_dt(p.get("lastdate")),
                area=p.get("area"),
                geometry=geometry,
            )
        )
    total = _total(body, len(rows))
    note = None
    if len(rows) < len(features):
        note = fr_or_en(
            lang,
            f"Stopped at {len(rows)} perimeters: their polygons reach the "
            f"{c.GEOMETRY_BYTES_MAX // 1000} KB geometry budget. Continue with "
            f"offset={offset + len(rows)}, or leave include_geometry off for attributes only.",
            f"Arrêt à {len(rows)} périmètres : leurs polygones atteignent le plafond de "
            f"{c.GEOMETRY_BYTES_MAX // 1000} Ko de géométrie. Continuez avec "
            f"offset={offset + len(rows)}, ou laissez include_geometry désactivé pour les "
            "attributs seulement.",
        )
    return PerimeterResult(
        perimeters=rows,
        returned_count=len(rows),
        total_matched=total,
        has_more=offset + len(rows) < total,
        note=note,
        provenance=_prov(
            "PerimeterResult",
            c.PERIMETERS,
            cached,
            coverage=fr_or_en(
                lang,
                f"{len(rows)} of {total} matching perimeters returned",
                f"{len(rows)} périmètres renvoyés sur {total} correspondants",
            ),
            limits=fr_or_en(
                lang,
                "model estimates from hotspot clusters, not agency-mapped perimeters",
                "estimations modélisées à partir des grappes de points chauds, et non "
                "périmètres cartographiés par les organismes",
            ),
            lang=lang,
        ),
    )


# --------------------------------------------------------------- stations


def _station(p: dict[str, Any], distance: float | None = None) -> WeatherStation:
    raw_prov = (p.get("prov") or "").strip()
    return WeatherStation(
        name=(p.get("name") or "").strip(),
        wmo=p.get("wmo"),
        aes=p.get("aes"),
        province=c.STATION_CODE_TO_PROVINCE.get(raw_prov, raw_prov) or None,
        agency=(p.get("agency") or "").strip() or None,
        latitude=p.get("lat"),
        longitude=p.get("lon"),
        elevation_m=p.get("elev"),
        observed_at=_dt(p.get("rep_date")),
        temperature_c=p.get("temp"),
        relative_humidity=p.get("rh"),
        wind_speed_kmh=p.get("ws"),
        wind_direction_deg=p.get("wdir"),
        precipitation_mm=p.get("precip"),
        ffmc=p.get("ffmc"),
        dmc=p.get("dmc"),
        dc=p.get("dc"),
        isi=p.get("isi"),
        bui=p.get("bui"),
        fwi=p.get("fwi"),
        dsr=p.get("dsr"),
        distance_km=None if distance is None else round(distance, 1),
    )


_STATION_FIELDS = (
    "aes,wmo,name,rep_date,agency,prov,lat,lon,elev,temp,rh,ws,wdir,precip,"
    "ffmc,dmc,dc,isi,bui,fwi,dsr"
)


async def get_stations(
    *,
    province: str | None = None,
    name: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = 50.0,
    limit: int = c.ROWS_LIMIT_DEFAULT,
    lang: str = "en",
) -> StationResult:
    """Fire-weather stations with latest FWI values, by province, name or point."""
    _check_page(limit, 0, lang=lang)
    if (latitude is None) != (longitude is None):
        raise lang_error(
            InvalidInput,
            lang,
            "Give both latitude and longitude, or neither.",
            "donnez latitude et longitude ensemble, ou ni l'une ni l'autre.",
        )
    clauses: list[str] = []
    if province:
        code = province.upper()
        clauses.append(f"prov = {_quote(c.PROVINCE_TO_STATION_CODE.get(code, code))}")
    if name:
        clauses.append(f"strToUpperCase(name) LIKE {_quote('%' + name.upper() + '%')}")
    if latitude is not None and longitude is not None:
        if not 0 < radius_km <= c.MAX_RADIUS_KM:
            raise lang_error(
                InvalidInput,
                lang,
                f"radius_km must be in (0, {c.MAX_RADIUS_KM:g}], got {radius_km}.",
                f"radius_km doit être dans ]0, {c.MAX_RADIUS_KM:g}] ; reçu {radius_km}.",
            )
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise lang_error(
                InvalidInput,
                lang,
                "latitude/longitude out of range.",
                "latitude ou longitude hors limites.",
            )
        dlat = radius_km / 111.32
        dlon = radius_km / (111.32 * max(math.cos(math.radians(latitude)), 0.05))
        box = [
            max(longitude - dlon, -180),
            max(latitude - dlat, -90),
            min(longitude + dlon, 180),
            min(latitude + dlat, 90),
        ]
        clauses.append(_bbox_cql("the_geom", box, lang))
    if not clauses:
        raise lang_error(
            InvalidInput,
            lang,
            "Give at least one of province, name, or latitude+longitude.",
            "donnez au moins province, name, ou latitude et longitude.",
        )
    by_point = latitude is not None
    body, cached = await _wfs(
        c.STATIONS,
        cql=" AND ".join(clauses),
        fields=_STATION_FIELDS,
        sort_by="name",  # the layer has no primary key; WFS paging needs an explicit sort
        limit=c.ROWS_LIMIT_MAX if by_point else limit,
        offset=0,
        ttl=c.CACHE_TTL_LIVE,
    )
    props = _props(body)
    if latitude is not None and longitude is not None:
        scored = [
            (_haversine_km(latitude, longitude, p["lat"], p["lon"]), p)
            for p in props
            if p.get("lat") is not None and p.get("lon") is not None
        ]
        scored = sorted((s for s in scored if s[0] <= radius_km), key=lambda s: s[0])
        stations = [_station(p, d) for d, p in scored[:limit]]
        total = len(scored)
    else:
        stations = [_station(p) for p in props]
        total = _total(body, len(stations))
    note = None
    if not stations:
        # Outside the fire season the layer holds a handful of stations (10 on
        # 2026-10-03, nine of them NL), so an empty answer says so.
        everything, _ = await _wfs(
            c.STATIONS,
            cql=None,
            fields="prov",
            sort_by="name",
            limit=c.ROWS_LIMIT_MAX,
            offset=0,
            ttl=c.CACHE_TTL_LIVE,
        )
        held = _props(everything)
        provinces = sorted(
            {
                c.STATION_CODE_TO_PROVINCE.get(code, code)
                for p in held
                if (code := (p.get("prov") or "").strip())
            }
        )
        held_in = f" ({', '.join(provinces)})" if provinces else ""
        note = fr_or_en(
            lang,
            f"No station matched. The layer currently holds {len(held)} stations"
            + held_in
            + "; stations report during the fire season only.",
            f"Aucune station ne correspond. La couche compte actuellement {len(held)} "
            f"stations{held_in} ; les stations ne transmettent que pendant la saison des feux.",
        )
    return StationResult(
        stations=stations,
        returned_count=len(stations),
        total_matched=total,
        note=note,
        provenance=_prov(
            "StationResult",
            c.STATIONS,
            cached,
            coverage=fr_or_en(
                lang,
                f"{len(stations)} of {total} matching stations returned",
                f"{len(stations)} stations renvoyées sur {total} correspondantes",
            ),
            limits=fr_or_en(
                lang,
                "includes US stations; FWI components are null where inputs are missing",
                "comprend des stations américaines ; les composantes de l'IFM sont nulles "
                "lorsque des données d'entrée manquent",
            ),
            freshness=fr_or_en(
                lang,
                "one noon (UTC) observation per station per day",
                "une observation à midi (UTC) par station et par jour",
            ),
            lang=lang,
        ),
    )


# --------------------------------------------------------------- forecast

_FORECAST_FIELDS = "wmo,name,rep_date,elevation,temp,rh,ws,wdir,precip,ffmc,dmc,dc,isi,bui,fwi,dsr"


async def get_forecast(*, station_name: str, limit: int = 100, lang: str = "en") -> ForecastResult:
    """Daily forecast fire weather (SCRIBE) for stations whose name contains the text."""
    _check_page(limit, 0, lang=lang)
    if not station_name.strip():
        raise lang_error(
            InvalidInput,
            lang,
            "station_name must not be empty.",
            "station_name ne doit pas être vide.",
        )
    cql = f"strToUpperCase(name) LIKE {_quote('%' + station_name.strip().upper() + '%')}"
    body, cached = await _wfs(
        c.FORECAST,
        cql=cql,
        fields=_FORECAST_FIELDS,
        sort_by="name,rep_date",
        limit=limit,
        offset=0,
        ttl=c.CACHE_TTL_FORECAST,
    )
    rows = [
        ForecastDay(
            station_id=str(p["wmo"]) if p.get("wmo") is not None else None,
            station_name=(p.get("name") or "").strip(),
            valid_at=_dt(p.get("rep_date")) or datetime.min.replace(tzinfo=UTC),
            elevation_m=p.get("elevation"),
            temperature_c=p.get("temp"),
            relative_humidity=p.get("rh"),
            wind_speed_kmh=p.get("ws"),
            wind_direction_deg=p.get("wdir"),
            precipitation_mm=p.get("precip"),
            ffmc=p.get("ffmc"),
            dmc=p.get("dmc"),
            dc=p.get("dc"),
            isi=p.get("isi"),
            bui=p.get("bui"),
            fwi=p.get("fwi"),
            dsr=p.get("dsr"),
        )
        for p in _props(body)
    ]
    if not rows:
        raise lang_error(
            NotFound,
            lang,
            f"No forecast station name contains {station_name!r}.",
            f"aucun nom de station de prévision ne contient {station_name!r}.",
        )
    total = _total(body, len(rows))
    return ForecastResult(
        forecasts=rows,
        returned_count=len(rows),
        total_matched=total,
        provenance=_prov(
            "ForecastResult",
            c.FORECAST,
            cached,
            coverage=fr_or_en(
                lang,
                f"{len(rows)} of {total} station-days returned",
                f"{len(rows)} jours-stations renvoyés sur {total}",
            ),
            freshness=fr_or_en(
                lang, "model forecast refreshed daily", "prévision modélisée actualisée chaque jour"
            ),
            lang=lang,
        ),
    )


# ----------------------------------------------------------------- danger


async def get_fire_danger(*, latitude: float, longitude: float, lang: str = "en") -> FireDanger:
    """Fire danger class of the current national fire danger polygon at a point."""
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise lang_error(
            InvalidInput,
            lang,
            "latitude/longitude out of range.",
            "latitude ou longitude hors limites.",
        )
    cql = f"INTERSECTS(the_geom, SRID=4326;POINT({longitude} {latitude}))"
    body, cached = await _wfs(
        c.DANGER,
        cql=cql,
        fields="GRIDCODE",
        sort_by=None,
        limit=1,
        offset=0,
        ttl=c.CACHE_TTL_LIVE,
    )
    props = _props(body)
    if not props:
        raise lang_error(
            NotFound,
            lang,
            f"No fire danger polygon covers ({latitude}, {longitude}); "
            "the grid only covers land in and near Canada.",
            f"aucun polygone de danger d'incendie ne couvre ({latitude}, {longitude}) ; la "
            "grille ne couvre que les terres du Canada et des environs.",
        )
    # A polygon with a null or missing GRIDCODE has no class to report; say so
    # rather than fail on int(None).
    raw = props[0].get("GRIDCODE")
    try:
        code = int(raw) if raw is not None else None
    except (TypeError, ValueError):
        code = None
    if code is None:
        label = fr_or_en(
            lang,
            "Unknown (no danger class recorded for this polygon)",
            "Inconnu (aucune classe de danger enregistrée pour ce polygone)",
        )
    elif lang == "fr":
        label = c.DANGER_CLASSES_FR.get(code, f"Inconnu ({code})")
    else:
        label = c.DANGER_CLASSES.get(code, f"Unknown ({code})")
    return FireDanger(
        latitude=latitude,
        longitude=longitude,
        gridcode=code,
        danger_class=label,
        provenance=_prov(
            "FireDanger",
            c.DANGER,
            cached,
            freshness=fr_or_en(
                lang,
                "current-day fire danger rating grid",
                "grille de l'indice de danger d'incendie du jour",
            ),
            limits=fr_or_en(
                lang,
                "class 4 (Extreme) is inferred from the five-class CWFIS scale",
                "la classe 4 (Extrême) est déduite de l'échelle à cinq classes du SCIFV",
            ),
            lang=lang,
        ),
    )


# ------------------------------------------------------------------- NFDB

_NFDB_FIELDS = (
    "NFDBFIREID,FIRE_ID,FIRENAME,SRC_AGENCY,NAT_PARK,LATITUDE,LONGITUDE,YEAR,REP_DATE,"
    "OUT_DATE,SIZE_HA,CAUSE,FIRE_TYPE,RESPONSE"
)


async def search_large_fires(
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    agency: str | None = None,
    min_size_ha: float | None = None,
    cause: str | None = None,
    name: str | None = None,
    sort_by: str = "size",
    limit: int = c.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> LargeFireResult:
    """Query the National Fire Database point layer (fires of 200 ha or more)."""
    _check_page(limit, offset, lang=lang)
    if sort_by not in ("size", "date"):
        raise lang_error(
            InvalidInput,
            lang,
            "sort_by must be 'size' or 'date'.",
            "sort_by doit être « size » ou « date ».",
        )
    _check_range(year_from, year_to, "year_from", "year_to", lang)
    clauses: list[str] = []
    if year_from is not None:
        clauses.append(f"YEAR >= {int(year_from)}")
    if year_to is not None:
        clauses.append(f"YEAR <= {int(year_to)}")
    if agency:
        code = agency.strip().upper()
        if code not in c.LARGE_FIRE_AGENCIES:
            raise lang_error(
                InvalidInput,
                lang,
                f"agency must be one of {', '.join(c.LARGE_FIRE_AGENCIES)}, got {agency!r}.",
                f"agency doit être l'une des valeurs {', '.join(c.LARGE_FIRE_AGENCIES)} ; reçu "
                f"{agency!r}.",
            )
        clauses.append(f"SRC_AGENCY = {_quote(code)}")
    if min_size_ha is not None:
        clauses.append(f"SIZE_HA >= {float(min_size_ha)}")
    if cause:
        if cause.upper() not in c.NFDB_CAUSES:
            raise lang_error(
                InvalidInput,
                lang,
                f"cause must be one of {sorted(c.NFDB_CAUSES)}, got {cause!r}.",
                f"cause doit être l'une des valeurs {sorted(c.NFDB_CAUSES)} ; reçu {cause!r}.",
            )
        clauses.append(f"CAUSE = {_quote(cause.upper())}")
    if name:
        clauses.append(f"strToUpperCase(FIRENAME) LIKE {_quote('%' + name.upper() + '%')}")
    body, cached = await _wfs(
        c.NFDB,
        cql=" AND ".join(clauses) or None,
        fields=_NFDB_FIELDS,
        sort_by="SIZE_HA D" if sort_by == "size" else "REP_DATE D",
        limit=limit,
        offset=offset,
        ttl=c.CACHE_TTL_ARCHIVE,
    )
    fires = [
        LargeFire(
            nfdb_id=p["NFDBFIREID"],
            fire_id=p.get("FIRE_ID") or None,
            name=p.get("FIRENAME") or None,
            agency=p.get("SRC_AGENCY") or None,
            latitude=p.get("LATITUDE"),
            longitude=p.get("LONGITUDE"),
            year=p.get("YEAR"),
            reported_date=_day(p.get("REP_DATE")),
            out_date=_day(p.get("OUT_DATE")),
            size_ha=p.get("SIZE_HA"),
            cause_code=p.get("CAUSE") or None,
            cause=(c.NFDB_CAUSES_FR if lang == "fr" else c.NFDB_CAUSES).get(p.get("CAUSE") or ""),
            fire_type=p.get("FIRE_TYPE") or None,
            response=p.get("RESPONSE") or None,
            national_park=p.get("NAT_PARK") or None,
        )
        for p in _props(body)
    ]
    total = _total(body, len(fires))
    return LargeFireResult(
        fires=fires,
        returned_count=len(fires),
        total_matched=total,
        limit=limit,
        offset=offset,
        provenance=_prov(
            "LargeFireResult",
            c.NFDB,
            cached,
            coverage=fr_or_en(
                lang,
                f"{len(fires)} of {total} matching fires returned",
                f"{len(fires)} feux renvoyés sur {total} correspondants",
            ),
            limits=fr_or_en(
                lang,
                "fires of 200 ha or more only; the layer's latest year is 2023 "
                "although its title says 1970-2024",
                "feux de 200 ha ou plus seulement ; la dernière année de la couche est 2023, "
                "même si son titre indique 1970-2024. Les noms de feux et les codes "
                "d'organisme sont ceux de la source.",
            ),
            freshness=fr_or_en(
                lang, "annual compilation, not real time", "compilation annuelle, pas en temps réel"
            ),
            lang=lang,
        ),
    )


# -------------------------------------------------------- situation reports


def _stats(item: dict[str, Any]) -> SituationStats:
    return SituationStats(
        uncontrolled=item.get("uncontrolled"),
        controlled=item.get("controlled"),
        modified_response=item.get("modified_response"),
        fires_to_date=item.get("number_2004_to_date"),
        fires_10yr_avg=item.get("number_10yr_avg"),
        fires_pct_of_normal=item.get("number_p100_normal"),
        prescribed_fires=item.get("number_prescribed"),
        area_to_date_ha=item.get("area_2004_to_date"),
        area_10yr_avg_ha=item.get("area_10yr_avg"),
        area_pct_of_normal=item.get("area_p100_normal"),
        prescribed_area_ha=item.get("area_prescribed"),
        us_fires=item.get("number_us"),
        us_area=item.get("area_us"),
    )


async def _sitrep_get(path: str, params: dict[str, Any], lang: str = "en") -> tuple[Any, bool]:
    url = c.SITREP_URL + path

    async def fetch() -> Any:
        await get_limiter(
            c.SITREP_RATE_SOURCE, rate=c.RATE_LIMIT_PER_SECOND, capacity=c.RATE_LIMIT_CAPACITY
        ).acquire()
        try:
            return await api_get(url, params=params)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise lang_error(
                    NotFound,
                    lang,
                    "No situation report on or before that date (reports start in 1998).",
                    "aucun rapport de situation à cette date ou avant (les rapports commencent "
                    "en 1998).",
                ) from exc
            if status == 422:
                raise lang_error(
                    InvalidInput,
                    lang,
                    f"Situation report API rejected the request: {exc.response.text[:200]}",
                    "l'API des rapports de situation a refusé la requête (message de l'API, en "
                    f"anglais) : {exc.response.text[:200]}",
                ) from exc
            raise lang_error(
                UpstreamError,
                lang,
                f"CWFIS situation reports returned HTTP {status}.",
                f"les rapports de situation du SCIFV ont répondu HTTP {status}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise lang_error(
                UpstreamUnavailable,
                lang,
                "CWFIS situation report API did not respond.",
                "l'API des rapports de situation du SCIFV n'a pas répondu.",
            ) from exc

    key = f"cwfis-sitrep:{path}:{sorted(params.items())}"
    return await cached_fetch(key, c.CACHE_TTL_SITREP, fetch)


def _sitrep_prov(schema: str, cached: bool, limits: str, lang: str = "en") -> Provenance:
    return make_provenance(
        source=c.SITREP_RATE_SOURCE,
        url=c.SITREP_URL,
        cached=cached,
        schema_name=f"cwfis.{schema}",
        limits=limits,
        licence=licence_for_lang(c.SITREP_RATE_SOURCE, c.SITREP_URL, lang),
        lang=lang,
    )


async def list_situation_reports(
    *,
    report_type: str = "all",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 20,
    offset: int = 0,
    lang: str = "en",
) -> SituationReportList:
    """List national situation reports (newest first) with their numeric totals."""
    _check_page(limit, offset, c.SITREP_LIMIT_MAX, lang)
    if report_type not in ("all", "end_of_season"):
        raise lang_error(
            InvalidInput,
            lang,
            "report_type must be 'all' or 'end_of_season'.",
            "report_type doit être « all » ou « end_of_season ».",
        )
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    _check_range(
        _parse_day(start_date, "start_date", lang),
        _parse_day(end_date, "end_date", lang),
        "start_date",
        "end_date",
        lang,
    )
    for key, value in (("start_date", start_date), ("end_date", end_date)):
        parsed = _parse_day(value, key, lang)
        if parsed:
            params[key] = parsed.isoformat()
    path = "/end-of-season" if report_type == "end_of_season" else ""
    body, cached = await _sitrep_get(path, params, lang)
    reports = [
        SituationReportSummary(
            report_date=date.fromisoformat(i["date"]),
            report_type=i.get("type") or report_type,
            stats=_stats(i),
        )
        for i in body.get("items") or []
    ]
    return SituationReportList(
        reports=reports,
        returned_count=len(reports),
        total_matched=body.get("total") or len(reports),
        offset=offset,
        provenance=_sitrep_prov(
            "SituationReportList",
            cached,
            fr_or_en(
                lang,
                "numeric totals are published for 1998-2023 reports only; "
                "later reports carry them in the narrative text",
                "les totaux numériques ne sont publiés que pour les rapports de 1998 à 2023 ; "
                "les rapports suivants les donnent dans le texte. Utilisez "
                'cwfis_get_situation_report avec lang="fr" pour le texte en français',
            ),
            lang,
        ),
    )


_IN_SEASON = (
    ("synopsis", "Synopsis", "Synopsis"),
    ("prognosis", "Prognosis", "Pronostic"),
    ("priority_fires", "Priority fires", "Feux prioritaires"),
    ("interagency_mobilization", "Interagency mobilization", "Mobilisation interorganismes"),
    ("wildfires", "Wildfires", "Feux de végétation"),
)
_END_OF_SEASON = (
    ("interagency_mobilization_summary", "Mobilization summary", "Sommaire de la mobilisation"),
    ("human_impacts", "Human impacts", "Répercussions sur la population"),
    ("wildfires_overview", "Wildfires overview", "Aperçu des feux de végétation"),
    ("weather_in_review", "Weather in review", "Bilan de la météo"),
)


async def get_situation_report(
    *, report_type: str = "in_season", date_on_or_before: str | None = None, lang: str = "en"
) -> SituationReport:
    """One situation report with narrative: latest, or the one on/before a date."""
    if report_type not in ("in_season", "end_of_season"):
        raise lang_error(
            InvalidInput,
            lang,
            "report_type must be 'in_season' or 'end_of_season'.",
            "report_type doit être « in_season » ou « end_of_season ».",
        )
    french = lang == "fr"
    when = _parse_day(date_on_or_before, "date_on_or_before", lang)
    params: dict[str, Any] = {"limit": 1, "offset": 0}
    if report_type == "in_season":
        if when:
            params["date"] = when.isoformat()
        item, cached = await _sitrep_get("/by-date", params, lang)
        if not item or "date" not in item:
            raise lang_error(
                NotFound,
                lang,
                "No in-season situation report found.",
                "aucun rapport de situation en saison trouvé.",
            )
    else:
        if when:
            params["end_date"] = when.isoformat()
        body, cached = await _sitrep_get("/end-of-season", params, lang)
        items = body.get("items") or []
        if not items:
            raise lang_error(
                NotFound,
                lang,
                "No end-of-season report on or before that date.",
                "aucun rapport de fin de saison à cette date ou avant.",
            )
        item = items[0]
    layout = _IN_SEASON if item.get("type", report_type) == "in_season" else _END_OF_SEASON
    suffix = "_f" if french else "_e"
    sections = []
    for key, en, fr in layout:
        text = item.get(key + suffix)
        if isinstance(text, str) and text.strip():
            sections.append(ReportSection(heading=fr if french else en, text=text.strip()))
    return SituationReport(
        report_date=date.fromisoformat(item["date"]),
        report_type=item.get("type") or report_type,
        stats=_stats(item),
        sections=sections,
        language="fr" if french else "en",
        provenance=_sitrep_prov(
            "SituationReport",
            cached,
            fr_or_en(
                lang,
                "narrative is in the requested language; numeric totals are null from 2024",
                "le texte est dans la langue demandée ; les totaux numériques sont nuls à "
                "partir de 2024",
            ),
            lang,
        ),
    )
