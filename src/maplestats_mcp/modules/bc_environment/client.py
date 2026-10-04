"""BC Ministry of Environment monitoring files: air, snow, groundwater, hydrometric.

Every file is a CSV on www.env.gov.bc.ca (layouts, time zones and missing
codes are in constants.py). Files up to 16 MB are downloaded whole and
cached briefly; the snow and hydrometric archives (40-190 MB) are sorted,
so a period is found by binary search with HTTP range requests and only
that stretch is read. Station and well metadata come from the BC
Geographic Warehouse WFS layers the BC Catalogue lists for these networks.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from maplestats_mcp.modules.bc_environment import constants
from maplestats_mcp.modules.bc_environment.schemas import (
    AirReading,
    AirSeries,
    AirStation,
    AirStationList,
    AqhiArea,
    AqhiHour,
    AqhiResult,
    HydroParameter,
    HydroReading,
    HydroSeries,
    HydroStation,
    HydroStationList,
    SnowReading,
    SnowSeries,
    SnowStation,
    SnowStationList,
    SnowSurvey,
    SnowSurveyList,
    SurveySeason,
    Well,
    WellLevel,
    WellList,
    WellSeries,
    WellSeriesKind,
)
from maplestats_mcp.shared import file_download, remote_zip
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

_LISTING_ROW = re.compile(
    r'<a href="([^"?/][^"]*)">[^<]*</a>\s*</td><td align="right">([^<]*)</td>'
    r'<td align="right">([^<]*)</td>'
)
_TIME = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?(?:[ T](\d{2}):?(\d{2})?(?::(\d{2}))?)?$")
_MISSING_CODE_FLOOR = -999.0


# ---------------------------------------------------------------- helpers


def _provenance(url: str, cached: bool, schema: str, lang: Lang, **extra: Any) -> Provenance:
    return make_provenance(
        source=constants.PROVENANCE_SOURCE,
        url=url,
        cached=cached,
        schema_name=f"bc_environment.{schema}",
        licence=constants.LICENCE[lang],
        lang=lang,
        **extra,
    )


def _check_limit(limit: int, maximum: int, lang: Lang) -> None:
    if not 1 <= limit <= maximum:
        raise_typed(
            InvalidInput,
            pick(
                lang,
                f"limit must be between 1 and {maximum}; got {limit}.",
                f"limit doit être compris entre 1 et {maximum} (reçu {limit}).",
            ),
            lang,
        )


def _decode(body: bytes) -> str:
    # The hydrometric files are Windows-1252 (an en dash in a station name,
    # confirmed live); the air, snow and well files are UTF-8 (degree sign).
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return body.decode("cp1252", errors="replace")


def _rows(body: bytes) -> tuple[list[str], list[list[str]]]:
    reader = csv.reader(io.StringIO(_decode(body)))
    header = [h.strip() for h in next(reader, [])]
    return header, [[cell.strip() for cell in row] for row in reader if row]


def _float(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _value(text: str | None) -> tuple[float | None, str | None]:
    """A measured value and, when the cell holds a missing-value code, that code."""
    number = _float(text)
    if number is not None and number <= _MISSING_CODE_FLOOR:
        return None, text
    return number, None


def norm_time(text: str) -> str:
    """'YYYY-MM-DD HH:MM:SS' from the several published spellings (T, +00:00, no seconds)."""
    value = text.strip().replace("T", " ").replace("/", "-")
    for suffix in ("+00:00", "Z"):
        value = value.removesuffix(suffix)
    if len(value) == 10:
        return value + " 00:00:00"
    if len(value) == 16:
        return value + ":00"
    return value


def bound(text: str | None, *, end: bool, lang: Lang, name: str) -> str | None:
    """A period bound as 'YYYY-MM-DD HH:MM:SS'; a date-only end covers its whole day."""
    if text is None or not text.strip():
        return None
    match = _TIME.match(text.strip())
    if not match:
        raise_typed(
            InvalidInput,
            pick(
                lang,
                f"{name} must look like 2026-09-15 or 2026-09-15 08:00; got {text!r}.",
                f"{name} doit avoir la forme 2026-09-15 ou 2026-09-15 08:00 (reçu {text!r}).",
            ),
            lang,
        )
    year, month, day, hour, minute, second = match.groups()
    if end:
        if month is None:
            return f"{year}-12-31 23:59:59"
        if day is None:
            first_next = date(int(year) + (month == "12"), int(month) % 12 + 1, 1)
            last = first_next - timedelta(days=1)
            return f"{last:%Y-%m-%d} 23:59:59"
        if hour is None:
            return f"{year}-{month}-{day} 23:59:59"
    return f"{year}-{month or '01'}-{day or '01'} {hour or '00'}:{minute or '00'}:{second or '00'}"


def _in_period(time: str, start: str | None, end: str | None) -> bool:
    return (start is None or time >= start) and (end is None or time <= end)


def _shift(time: str, hours: int) -> str:
    try:
        moment = datetime.strptime(norm_time(time), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return time
    return f"{moment + timedelta(hours=hours):%Y-%m-%d %H:%M}"


def _allowed(host: str) -> bool:
    return host in constants.ALLOWED_HOSTS


async def _file(url: str, ttl: int, lang: Lang) -> tuple[bytes, bool]:
    async def fetch() -> file_download.Downloaded:
        return await file_download.download(
            url,
            allow_host=_allowed,
            limiter_for=lambda _host: _LIMITER,
            max_bytes=constants.MAX_FILE_BYTES,
            context="BC Ministry of Environment",
        )

    downloaded, cached = await file_download.cached_download(
        file_download.cache_key(url), ttl, fetch
    )
    return downloaded.body, cached


async def listing(url: str) -> dict[str, tuple[str, str]]:
    """{file name: (last modified, size)} from an Apache directory index."""

    async def fetch() -> dict[str, tuple[str, str]]:
        body, _ = await _file(url, constants.CACHE_TTL_HOURLY_SECONDS, "en")
        html = _decode(body)
        return {
            name: (modified.strip(), size.strip())
            for name, modified, size in _LISTING_ROW.findall(html)
        }

    result, _ = await cached_fetch(
        f"bc_env:listing:{url}", constants.CACHE_TTL_HOURLY_SECONDS, fetch
    )
    return result


def _newest(items: list[Any], limit: int) -> tuple[list[Any], bool]:
    return items[:limit], len(items) > limit


# ------------------------------------------------------------- range reader


async def _range(url: str, start: int, end: int) -> bytes:
    await _LIMITER.acquire()
    return await remote_zip.fetch_range(url, start, end)


def _line_text(raw: bytes) -> str:
    return _decode(raw.rstrip(b"\r"))


async def scan_sorted(
    url: str,
    key_of: Callable[[list[str]], Any],
    target: Any,
    stop: Callable[[Any], bool],
) -> tuple[list[list[str]], bool]:
    """Rows of a sorted remote CSV from the first key >= target until stop(key).

    Binary search over byte offsets (each probe reads one chunk and keys the
    first whole line in it), then a forward read. Returns (rows, cut_short):
    cut_short when the read hit RANGE_READ_MAX_BYTES before stop().
    """
    size = await remote_zip.remote_size(url)
    if size <= 0:
        return [], False
    chunk = constants.RANGE_CHUNK_BYTES

    def first_key(data: bytes) -> Any:
        lines = data.split(b"\n")
        for raw in lines[1:-1]:
            row = next(csv.reader([_line_text(raw)]), [])
            key = key_of([cell.strip() for cell in row]) if row else None
            if key is not None:
                return key
        return None

    low, high = 0, size
    while high - low > chunk:
        middle = (low + high) // 2
        key = first_key(await _range(url, middle, min(middle + chunk, size) - 1))
        if key is None or key >= target:
            high = middle
        else:
            low = middle
    rows: list[list[str]] = []
    position, carry, skip_first = low, b"", True
    read = 0
    while position < size:
        if read >= constants.RANGE_READ_MAX_BYTES:
            return rows, True
        data = await _range(url, position, min(position + chunk, size) - 1)
        read += len(data)
        position += len(data)
        lines = (carry + data).split(b"\n")
        carry = lines.pop() if position < size else b""
        for raw in lines:
            if skip_first:
                # The first line at `low` is partial, or the header at offset 0.
                skip_first = False
                continue
            text = _line_text(raw)
            if not text.strip():
                continue
            row = [cell.strip() for cell in next(csv.reader([text]), [])]
            key = key_of(row)
            if key is None or key < target:
                continue
            if stop(key):
                return rows, False
            rows.append(row)
    return rows, False


async def remote_header(url: str) -> list[str]:
    size = await remote_zip.remote_size(url)
    data = await _range(url, 0, min(size, 64 * 1024) - 1)
    first = data.split(b"\n", 1)[0]
    return [h.strip() for h in next(csv.reader([_line_text(first)]), [])]


# -------------------------------------------------------------------- air


async def _air_station_rows(lang: Lang) -> tuple[list[AirStation], bool]:
    body, cached = await _file(constants.AIR_STATIONS_URL, constants.CACHE_TTL_HOURLY_SECONDS, lang)
    header, rows = _rows(body)
    stations: list[AirStation] = []
    for row in rows:
        record = dict(zip(header, row, strict=False))
        units = {
            column.removesuffix("_UNIT"): value
            for column, value in record.items()
            if column.endswith("_UNIT") and value
        }
        stations.append(
            AirStation(
                ems_id=record.get("EMS_ID", ""),
                name=record.get("STATION_NAME", ""),
                city=record.get("CITY") or None,
                category=record.get("CATEGORY") or None,
                owner=record.get("STATION_OWNER") or None,
                latitude=_float(record.get("LATITUDE")),
                longitude=_float(record.get("LONGITUDE")),
                elevation_m=_float(record.get("HEIGHT(m)")),
                parameters=sorted(units),
                units=units,
                latest_hour_pst=record.get("DATE_PST") or None,
                page_url=record.get("URL") or None,
            )
        )
    return stations, cached


async def list_air_stations(
    query: str | None = None,
    parameter: str | None = None,
    owner: str | None = None,
    limit: int = constants.LIST_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> AirStationList:
    _check_limit(limit, constants.LIST_LIMIT_MAX, lang)
    stations, cached = await _air_station_rows(lang)
    if query:
        needle = query.casefold()
        stations = [
            s
            for s in stations
            if needle in s.name.casefold()
            or needle in (s.city or "").casefold()
            or needle == s.ems_id.casefold()
        ]
    if parameter:
        wanted = parameter.upper().replace(".", "")
        stations = [s for s in stations if wanted in {p.upper() for p in s.parameters}]
    if owner:
        stations = [s for s in stations if owner.casefold() in (s.owner or "").casefold()]
    return AirStationList(
        total_matched=len(stations),
        stations=stations[:limit],
        provenance=_provenance(
            constants.AIR_STATIONS_URL,
            cached,
            "AirStationList",
            lang,
            freshness=pick(
                lang,
                "Rewritten every hour (current-hour values).",
                "Réécrit toutes les heures (valeurs de l'heure courante).",
            ),
            coverage=pick(
                lang,
                "Stations reporting now; units are those of the current-hour file.",
                "Stations qui transmettent en ce moment ; les unités sont celles du fichier de "
                "l'heure courante.",
            ),
        ),
    )


async def _resolve_air_station(station: str, lang: Lang) -> AirStation:
    stations, _ = await _air_station_rows(lang)
    wanted = station.strip().casefold()
    exact = [s for s in stations if wanted in (s.ems_id.casefold(), s.name.casefold())]
    if exact:
        return exact[0]
    partial = [s for s in stations if wanted in s.name.casefold()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise_typed(
            NotFound,
            pick(
                lang,
                f"no air monitoring station matches {station!r}; use bc_env_list_air_stations.",
                f"aucune station de surveillance de l'air ne correspond à {station!r} ; utilisez "
                "bc_env_list_air_stations.",
            ),
            lang,
        )
    names = ", ".join(f"{s.name} ({s.ems_id})" for s in partial[:12])
    raise_typed(
        InvalidInput,
        pick(
            lang,
            f"{station!r} matches several stations: {names}.",
            f"{station!r} correspond à plusieurs stations : {names}.",
        ),
        lang,
    )


_UNIT_ALIASES = {"BAR": "PRESSURE", "PRECIP": "PRECIPITATION", "SNOW": "SNOWDEPTH"}


def _unit_for(column: str, units: dict[str, str]) -> str | None:
    base = column.split("_")[0].upper()
    if column.upper() in units:
        return units[column.upper()]
    return units.get(base) or units.get(_UNIT_ALIASES.get(base, base))


async def get_air_station_data(
    station: str,
    parameters: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> AirSeries:
    _check_limit(limit, constants.ROWS_LIMIT_MAX, lang)
    low = bound(start, end=False, lang=lang, name="start")
    high = bound(end, end=True, lang=lang, name="end")
    found = await _resolve_air_station(station, lang)
    url = f"{constants.AIR_RAW}/Station/{found.ems_id}.csv"
    body, cached = await _file(url, constants.CACHE_TTL_HOURLY_SECONDS, lang)
    header, rows = _rows(body)
    fixed = {"DATE_PST", "STATION", "EMS_ID", "LATITUDE", "LONGITUDE", "DATE_LOCAL", "DATE"}
    columns = [c for c in header if c not in fixed]
    if parameters:
        wanted = {p.upper() for p in parameters}
        columns = [c for c in columns if c.upper() in wanted]
        if not columns:
            available = ", ".join(c for c in header if c not in fixed)
            raise_typed(
                NotFound,
                pick(
                    lang,
                    f"{found.name} has none of {parameters}; it reports {available}.",
                    f"{found.name} ne mesure aucun de {parameters} ; elle mesure {available}.",
                ),
                lang,
            )
    readings: list[AirReading] = []
    for row in rows:
        record = dict(zip(header, row, strict=False))
        time_pst = record.get("DATE_PST", "")
        if not _in_period(norm_time(time_pst), low, high):
            continue
        for column in columns:
            value, code = _value(record.get(column))
            readings.append(
                AirReading(
                    time_pst=time_pst,
                    time_utc=_shift(time_pst, 8),
                    station=found.name,
                    ems_id=found.ems_id,
                    parameter=column,
                    value=value,
                    unit=_unit_for(column, found.units),
                    missing_code=code,
                )
            )
    kept, truncated = _newest(readings, limit)
    return AirSeries(
        station=found.name,
        total_matched=len(readings),
        truncated=truncated,
        readings=kept,
        notes=[
            pick(
                lang,
                "Unverified raw data: values can change or be removed when the ministry "
                "validates them. Verified historical data is published only on an ftp:// "
                "server, which this server cannot read.",
                "Données brutes non vérifiées : les valeurs peuvent changer ou disparaître "
                "quand le ministère les valide. Les données historiques vérifiées ne sont "
                "publiées que sur un serveur ftp://, que ce serveur ne peut pas lire.",
            ),
            pick(
                lang,
                "Units come from the station's current-hour record; _24 and _8 columns are "
                "rolling means in the base parameter's unit.",
                "Les unités viennent de l'enregistrement de l'heure courante de la station ; "
                "les colonnes _24 et _8 sont des moyennes mobiles dans l'unité du paramètre "
                "de base.",
            ),
        ],
        provenance=_provenance(
            url,
            cached,
            "AirSeries",
            lang,
            freshness=pick(
                lang,
                "Rewritten every hour; holds the last 30 days.",
                "Réécrit toutes les heures ; contient les 30 derniers jours.",
            ),
            limits=pick(lang, f"readings capped at {limit}", f"lectures limités à {limit}")
            if truncated
            else None,
        ),
    )


async def get_air_parameter_data(
    parameter: str,
    station: str | None = None,
    start: str | None = None,
    end: str | None = None,
    latest_only: bool = False,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> AirSeries:
    _check_limit(limit, constants.ROWS_LIMIT_MAX, lang)
    low = bound(start, end=False, lang=lang, name="start")
    high = bound(end, end=True, lang=lang, name="end")
    codes = {p.upper(): ("Air_Quality", p) for p in constants.AIR_QUALITY_PARAMETERS} | {
        p.upper(): ("Meteorological", p) for p in constants.MET_PARAMETERS
    }
    key = parameter.strip().upper().replace(".", "").replace("PM2,5", "PM25")
    if key not in codes:
        raise_typed(
            InvalidInput,
            pick(
                lang,
                f"unknown parameter {parameter!r}; use one of {', '.join(sorted(codes))}.",
                f"paramètre inconnu {parameter!r} ; utilisez l'un de {', '.join(sorted(codes))}.",
            ),
            lang,
        )
    folder, name = codes[key]
    url = f"{constants.AIR_RAW}/{folder}/{name}.csv"
    body, cached = await _file(url, constants.CACHE_TTL_HOURLY_SECONDS, lang)
    header, rows = _rows(body)
    wanted = station.strip().casefold() if station else None
    readings: list[AirReading] = []
    seen: set[str] = set()
    for row in rows:
        record = dict(zip(header, row, strict=False))
        ems = record.get("EMS_ID", "")
        name_ = record.get("STATION_NAME", "")
        if wanted and wanted != ems.casefold() and wanted not in name_.casefold():
            continue
        time_pst = record.get("DATE_PST", "")
        if not _in_period(norm_time(time_pst), low, high):
            continue
        raw, raw_code = _value(record.get("RAW_VALUE"))
        reported, reported_code = _value(record.get("REPORTED_VALUE"))
        if latest_only:
            # Rows are newest first per station; the first row with a value wins.
            if ems in seen or (raw is None and reported is None):
                continue
            seen.add(ems)
        readings.append(
            AirReading(
                time_pst=time_pst,
                time_utc=_shift(time_pst, 8),
                station=name_,
                ems_id=ems,
                parameter=record.get("PARAMETER") or name,
                value=reported if reported is not None else raw,
                raw_value=raw,
                unit=record.get("UNITS") or None,
                instrument=record.get("INSTRUMENT") or None,
                missing_code=reported_code or raw_code,
            )
        )
    readings.sort(key=lambda r: r.time_pst, reverse=True)
    kept, truncated = _newest(readings, limit)
    return AirSeries(
        parameter=name,
        station=station,
        total_matched=len(readings),
        truncated=truncated,
        readings=kept,
        notes=[
            pick(
                lang,
                "Unverified raw data (RAW_VALUE as measured, value = REPORTED_VALUE, "
                "rounded). Verified historical data is published only on an ftp:// server, "
                "which this server cannot read.",
                "Données brutes non vérifiées (RAW_VALUE telle que mesurée, value = "
                "REPORTED_VALUE, arrondie). Les données historiques vérifiées ne sont publiées "
                "que sur un serveur ftp://, que ce serveur ne peut pas lire.",
            ),
        ],
        provenance=_provenance(
            url,
            cached,
            "AirSeries",
            lang,
            freshness=pick(
                lang,
                "Rewritten every hour; holds the last 30 days for every station.",
                "Réécrit toutes les heures ; contient les 30 derniers jours pour chaque station.",
            ),
            limits=pick(lang, f"readings capped at {limit}", f"lectures limités à {limit}")
            if truncated
            else None,
        ),
    )


async def get_aqhi(
    area: str | None = None, history_hours: int = 0, lang: Lang = "en"
) -> AqhiResult:
    if not 0 <= history_hours <= 720:
        raise_typed(
            InvalidInput,
            pick(
                lang,
                "history_hours must be between 0 and 720.",
                "history_hours doit être compris entre 0 et 720.",
            ),
            lang,
        )
    body, cached = await _file(constants.AQHI_URL, constants.CACHE_TTL_HOURLY_SECONDS, lang)
    header, rows = _rows(body)
    areas: list[AqhiArea] = []
    for row in rows:
        record = dict(zip(header, row, strict=False))
        page = record.get("URL") or ""
        area_id = page.rpartition("id=")[2] if "id=" in page else ""
        risk = record.get("AQHICURRENT_Text1") or None
        areas.append(
            AqhiArea(
                area=record.get("AQHI_AREA", ""),
                area_id=area_id,
                latitude=_float(record.get("LATITUDE")),
                longitude=_float(record.get("LONGITUDE")),
                time_local=record.get("DATE_LOCAL") or None,
                time_pst=record.get("DATE_PST") or None,
                aqhi=record.get("VALUE_CHAR") or record.get("VALUE") or None,
                risk=risk,
                forecast_today=record.get("FORECAST_TODAY_CHAR") or None,
                forecast_tonight=record.get("FORECAST_TONIGHT_CHAR") or None,
                forecast_tomorrow=record.get("FORECAST_TOMORROW_CHAR") or None,
                forecast_tomorrow_night=record.get("FORECAST_TOMORROW_NIGHT_CHAR") or None,
                page_url=page or None,
            )
        )
    if area:
        needle = area.strip().casefold()
        areas = [a for a in areas if needle in a.area.casefold() or needle == a.area_id.casefold()]
        if not areas:
            raise_typed(
                NotFound,
                pick(
                    lang,
                    f"no AQHI area matches {area!r}.",
                    f"aucune zone de la cote air santé (CAS) ne correspond à {area!r}.",
                ),
                lang,
            )
    history: list[AqhiHour] = []
    url = constants.AQHI_URL
    if history_hours:
        if len(areas) != 1 or not areas[0].area_id:
            raise_typed(
                InvalidInput,
                pick(
                    lang,
                    "history_hours needs `area` naming exactly one area.",
                    "history_hours exige que `area` désigne une seule zone.",
                ),
                lang,
            )
        url = f"{constants.AIR_RAW}/Station/{areas[0].area_id}.csv"
        hist_body, cached = await _file(url, constants.CACHE_TTL_HOURLY_SECONDS, lang)
        hist_header, hist_rows = _rows(hist_body)
        for row in hist_rows[:history_hours]:
            record = dict(zip(hist_header, row, strict=False))
            value, _ = _value(record.get("AQHI"))
            history.append(
                AqhiHour(
                    time_pst=record.get("DATE_PST", ""),
                    time_local=record.get("DATE_LOCAL") or None,
                    station=record.get("STATION_NAME") or None,
                    aqhi=value,
                    aqhi_rounded=record.get("AQHI_CHAR") or None,
                )
            )
    return AqhiResult(
        areas=areas,
        history=history,
        provenance=_provenance(
            url,
            cached,
            "AqhiResult",
            lang,
            freshness=pick(
                lang,
                "Rewritten every hour; forecasts are issued by ECCC with the province.",
                "Réécrit toutes les heures ; les prévisions sont émises par ECCC avec la province.",
            ),
        ),
    )


# ------------------------------------------------------------------- snow


async def _wfs(
    layer: str, extra: dict[str, str] | None = None, lang: str = "en"
) -> list[dict[str, Any]]:
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": layer,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "count": "5000",
        **(extra or {}),
    }
    await _LIMITER.acquire()
    try:
        payload = await api_get(constants.WFS_URL, params=params, timeout=90.0)
    except Exception as exc:  # noqa: BLE001 (raise_localized re-raises it as UpstreamUnavailable)
        raise_localized(
            UpstreamUnavailable,
            f"the BC Geographic Warehouse ({layer}) did not answer: {type(exc).__name__}.",
            f"le BC Geographic Warehouse ({layer}) n'a pas répondu ({type(exc).__name__}).",
            lang,
        )
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise_localized(
            UpstreamError,
            f"the BC Geographic Warehouse returned no features for {layer}.",
            f"le BC Geographic Warehouse n'a renvoyé aucune entité pour {layer}.",
            lang,
        )
    return features


async def list_snow_stations(
    query: str | None = None,
    status: str | None = None,
    operator: str | None = None,
    limit: int = constants.LIST_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> SnowStationList:
    _check_limit(limit, constants.LIST_LIMIT_MAX, lang)

    async def fetch() -> list[SnowStation]:
        features = await _wfs(constants.SNOW_STATIONS_LAYER, lang=lang)
        out = []
        for feature in features:
            p = feature.get("properties") or {}
            out.append(
                SnowStation(
                    station_id=str(p.get("LOCATION_ID") or ""),
                    name=str(p.get("LOCATION_NAME") or ""),
                    elevation_m=_float(str(p.get("ELEVATION"))),
                    status=p.get("STATUS"),
                    operator=p.get("OPERATOR"),
                    latitude=_float(str(p.get("LATITUDE"))),
                    longitude=_float(str(p.get("LONGITUDE"))),
                )
            )
        return sorted(out, key=lambda s: s.station_id)

    stations, cached = await cached_fetch(
        "bc_env:snow_stations", constants.CACHE_TTL_LIST_SECONDS, fetch
    )
    if query:
        needle = query.casefold()
        stations = [
            s
            for s in stations
            if needle in s.name.casefold() or s.station_id.casefold().startswith(needle)
        ]
    if status:
        stations = [s for s in stations if (s.status or "").casefold() == status.casefold()]
    if operator:
        stations = [s for s in stations if operator.casefold() in (s.operator or "").casefold()]
    return SnowStationList(
        total_matched=len(stations),
        stations=stations[:limit],
        provenance=_provenance(
            constants.WFS_URL,
            cached,
            "SnowStationList",
            lang,
            coverage=pick(
                lang,
                "Automated snow weather stations (layer SSL_SNOW_ASWS_STNS_SP); "
                "manual snow courses are in bc_env_get_snow_surveys.",
                "Stations nivométéorologiques automatiques (couche SSL_SNOW_ASWS_STNS_SP) ; "
                "les parcours nivométriques manuels sont dans bc_env_get_snow_surveys.",
            ),
        ),
    )


async def get_snow_station_data(
    station: str,
    variables: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> SnowSeries:
    _check_limit(limit, constants.ROWS_LIMIT_MAX, lang)
    low = bound(start, end=False, lang=lang, name="start")
    high = bound(end, end=True, lang=lang, name="end")
    station_id = station.strip().upper()
    if not re.fullmatch(r"[0-9][A-Z][0-9]{2}[A-Z]?P", station_id):
        raise_typed(
            InvalidInput,
            pick(
                lang,
                f"station must be an automated snow station id such as 1A01P; got {station!r}.",
                "station doit être l'identifiant d'une station nivométrique automatique, p. ex. "
                "1A01P (reçu {station!r}).",
            ),
            lang,
        )
    url = f"{constants.SNOW_BASE}/SnowAll/{station_id}.csv"
    try:
        body, cached = await _file(url, constants.CACHE_TTL_HOURLY_SECONDS, lang)
    except NotFound:
        raise_typed(
            NotFound,
            pick(
                lang,
                f"no current-season file for snow station {station_id}.",
                f"aucun fichier de la saison en cours pour la station nivométrique {station_id}.",
            ),
            lang,
        )
    header, rows = _rows(body)
    measures = [c for c in header[7:] if not c.startswith(("Unit_", "Grade_"))]
    if variables:
        wanted = {v.casefold() for v in variables}
        measures = [m for m in measures if m.casefold() in wanted]
    readings: list[SnowReading] = []
    for row in rows:
        record = dict(zip(header, row, strict=False))
        time = norm_time(record.get("DateTime", ""))
        if not _in_period(time, low, high):
            continue
        for measure in measures:
            if not record.get(measure):
                continue
            readings.append(
                SnowReading(
                    time_utc=time,
                    station_id=record.get("Location ID", station_id),
                    station_name=record.get("Location Name") or None,
                    variable=measure,
                    value=_float(record.get(measure)),
                    unit=record.get(f"Unit_{measure}") or None,
                    grade=record.get(f"Grade_{measure}") or None,
                )
            )
    readings.reverse()
    kept, truncated = _newest(readings, limit)
    return SnowSeries(
        file=url,
        total_matched=len(readings),
        truncated=truncated,
        readings=kept,
        notes=[
            pick(
                lang,
                "Current season only (from 1 October); use bc_env_get_snow_readings with a "
                "start date for the archive since 2003. Values are provisional.",
                "Saison en cours seulement (depuis le 1er octobre) ; utilisez "
                "bc_env_get_snow_readings avec une date de début pour les archives depuis 2003. "
                "Les valeurs sont provisoires.",
            )
        ],
        provenance=_provenance(
            url,
            cached,
            "SnowSeries",
            lang,
            freshness=pick(
                lang,
                "Updated hourly during the season.",
                "Mis à jour toutes les heures pendant la saison.",
            ),
        ),
    )


def _snow_columns(header: list[str]) -> list[tuple[int, str, str]]:
    columns = []
    for index, title in enumerate(header[1:], start=1):
        station_id, _, name = title.partition(" ")
        if station_id:
            columns.append((index, station_id, name))
    return columns


def _pick_columns(
    columns: list[tuple[int, str, str]], stations: list[str] | None, lang: Lang
) -> list[tuple[int, str, str]]:
    if not stations:
        return columns
    wanted = [s.strip().casefold() for s in stations if s.strip()]
    picked = [
        c for c in columns if any(w == c[1].casefold() or w in c[2].casefold() for w in wanted)
    ]
    if not picked:
        raise_typed(
            NotFound,
            pick(
                lang,
                f"no station column matches {stations}.",
                f"aucune colonne de station ne correspond à {stations}.",
            ),
            lang,
        )
    return picked


async def get_snow_readings(
    variable: str,
    stations: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> SnowSeries:
    _check_limit(limit, constants.ROWS_LIMIT_MAX, lang)
    code = variable.strip().upper()
    if code not in constants.SNOW_VARIABLES:
        raise_typed(
            InvalidInput,
            pick(
                lang,
                f"variable must be one of {', '.join(constants.SNOW_VARIABLES)}; got {variable!r}.",
                f"variable doit valoir l'une des valeurs {', '.join(constants.SNOW_VARIABLES)} "
                "(reçu {variable!r}).",
            ),
            lang,
        )
    label, unit = constants.SNOW_VARIABLES[code]
    low = bound(start, end=False, lang=lang, name="start")
    high = bound(end, end=True, lang=lang, name="end")
    current_url = f"{constants.SNOW_BASE}/{constants.SNOW_CURRENT[code]}"
    body, cached = await _file(current_url, constants.CACHE_TTL_HOURLY_SECONDS, lang)
    header, rows = _rows(body)
    season_start = norm_time(rows[0][0]) if rows and rows[0] else None
    notes: list[str] = [
        pick(
            lang,
            f"{label} ({unit or 'unit not stated by the source'}), times in UTC.",
            f"{label} ({unit or 'unité non précisée par la source'}), heures en UTC "
            "(libellé de la source, en anglais).",
        )
    ]
    url = current_url
    cut_short = False
    if low is not None and season_start is not None and low < season_start:
        archive = constants.SNOW_ARCHIVES.get(code)
        if archive is None:
            raise_typed(
                InvalidInput,
                pick(
                    lang,
                    f"{code} has no archive; its current file starts at {season_start}.",
                    f"{code} n'a pas d'archive ; son fichier courant commence le {season_start}.",
                ),
                lang,
            )
        url = f"{constants.SNOW_BASE}/{archive}"
        cached = False
        if code == "SW_DAILY":
            body, cached = await _file(url, constants.CACHE_TTL_ARCHIVE_SECONDS, lang)
            header, rows = _rows(body)
        else:
            header = await remote_header(url)
            rows, cut_short = await scan_sorted(
                url,
                key_of=lambda row: norm_time(row[0]) if row and row[0][:1].isdigit() else None,
                target=low,
                stop=lambda key: high is not None and key > high,
            )
            if cut_short:
                notes.append(
                    pick(
                        lang,
                        "The archive read stopped at its byte cap; narrow the period.",
                        "La lecture de l'archive s'est arrêtée à sa limite d'octets ; "
                        "resserrez la période.",
                    )
                )
        notes.append(
            pick(
                lang,
                "Read from the archive (October 2003 onward, sorted by time).",
                "Lu dans l'archive (depuis octobre 2003, triée par date).",
            )
        )
    columns = _pick_columns(_snow_columns(header), stations, lang)
    readings: list[SnowReading] = []
    for row in rows:
        if not row:
            continue
        time = norm_time(row[0])
        if not _in_period(time, low, high):
            continue
        for index, station_id, name in columns:
            cell = row[index] if index < len(row) else ""
            if cell == "":
                continue
            readings.append(
                SnowReading(
                    time_utc=time,
                    station_id=station_id,
                    station_name=name or None,
                    variable=code,
                    value=_float(cell),
                    unit=unit,
                )
            )
    readings.sort(key=lambda r: (r.time_utc, r.station_id), reverse=True)
    kept, truncated = _newest(readings, limit)
    return SnowSeries(
        variable=code,
        file=url,
        total_matched=len(readings),
        truncated=truncated,
        readings=kept,
        notes=notes,
        provenance=_provenance(
            url,
            cached,
            "SnowSeries",
            lang,
            freshness=pick(
                lang,
                "Current-season files update hourly; archives daily.",
                "Fichiers de la saison en cours mis à jour toutes les heures ; archives chaque jour.",
            ),
            limits=pick(lang, f"readings capped at {limit}", f"lectures limités à {limit}")
            if truncated
            else None,
        ),
    )


async def get_snow_surveys(
    query: str | None = None,
    season: SurveySeason = "current",
    start: str | None = None,
    end: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> SnowSurveyList:
    _check_limit(limit, constants.ROWS_LIMIT_MAX, lang)
    low = bound(start, end=False, lang=lang, name="start")
    high = bound(end, end=True, lang=lang, name="end")
    name = "allmss_current.csv" if season == "current" else "allmss_archive.csv"
    url = f"{constants.SNOW_BASE}/{name}"
    body, cached = await _file(url, constants.CACHE_TTL_LIST_SECONDS, lang)
    _, rows = _rows(body)
    needle = query.strip().casefold() if query else None
    surveys: list[SnowSurvey] = []
    for row in rows:
        if len(row) < 10:
            continue
        course, number = row[0], row[1]
        if needle and needle not in course.casefold() and not number.casefold().startswith(needle):
            continue
        date = row[3].replace("/", "-")
        if not _in_period(norm_time(date), low, high):
            continue
        surveys.append(
            SnowSurvey(
                course=course,
                number=number,
                elevation_m=_float(row[2]),
                survey_date=date,
                snow_depth_cm=_float(row[4]),
                water_equivalent_mm=_float(row[5]),
                survey_code=row[6] or None,
                snow_line_m=_float(row[7]),
                density_pct=_float(row[8]),
                survey_period=row[9] or None,
            )
        )
    surveys.sort(key=lambda s: (s.survey_date, s.number), reverse=True)
    kept, truncated = _newest(surveys, limit)
    return SnowSurveyList(
        season=season,
        total_matched=len(surveys),
        truncated=truncated,
        surveys=kept,
        provenance=_provenance(
            url,
            cached,
            "SnowSurveyList",
            lang,
            freshness=pick(
                lang,
                "Updated after each survey round (1 January to 15 June).",
                "Mis à jour après chaque tournée de relevés (du 1er janvier au 15 juin).",
            ),
        ),
    )


# ------------------------------------------------------------ groundwater


async def _well_regions() -> dict[str, str]:
    body, _ = await _file(constants.WELL_REGIONS_URL, constants.CACHE_TTL_LIST_SECONDS, "en")
    header, rows = _rows(body)
    out: dict[str, str] = {}
    for row in rows:
        record = dict(zip(header, row, strict=False))
        number, region = record.get("Well_Num", ""), record.get("REGION_NAME", "")
        if number and region and region != "NA":
            out[f"OW{number.zfill(3)}"] = region
    return out


async def list_wells(
    query: str | None = None,
    status: str | None = None,
    region: str | None = None,
    with_data_only: bool = True,
    limit: int = constants.LIST_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> WellList:
    _check_limit(limit, constants.LIST_LIMIT_MAX, lang)

    async def fetch() -> list[Well]:
        features = await _wfs(
            constants.WELLS_LAYER,
            {"CQL_FILTER": "OBSERVATION_WELL_NUMBER IS NOT NULL"},
            lang=lang,
        )
        files = await listing(f"{constants.WELL_BASE}/")
        try:
            regions = await _well_regions()
        except (NotFound, UpstreamError, UpstreamUnavailable, InvalidInput):
            regions = {}
        wells: dict[str, Well] = {}
        for feature in features:
            p = feature.get("properties") or {}
            number = str(p.get("OBSERVATION_WELL_NUMBER") or "").strip()
            if not number:
                continue
            well_id = f"OW{number.zfill(3)}" if number.isdigit() else f"OW{number}"
            coords = (feature.get("geometry") or {}).get("coordinates") or [None, None]
            data_file = files.get(f"{well_id}-data.csv")
            wells[well_id] = Well(
                well_id=well_id,
                status=p.get("OBSERVATION_WELL_STATUS"),
                region=regions.get(well_id),
                city=p.get("CITY"),
                address=(p.get("STREET_ADDRESS") or "").strip() or None,
                latitude=coords[1],
                longitude=coords[0],
                well_tag_number=p.get("WELL_TAG_NUMBER"),
                aquifer_id=p.get("AQUIFER_ID"),
                aquifer_material=p.get("AQUIFER_MATERIAL"),
                finished_depth_ft=p.get("FINISHED_WELL_DEPTH"),
                ground_elevation_ft=p.get("GROUND_ELEVATION"),
                has_data_files=data_file is not None,
                data_updated=data_file[0] if data_file else None,
                details_url=p.get("WELL_DETAILS_URL"),
            )
        return sorted(wells.values(), key=lambda w: w.well_id)

    wells, cached = await cached_fetch("bc_env:wells", constants.CACHE_TTL_LIST_SECONDS, fetch)
    if with_data_only:
        wells = [w for w in wells if w.has_data_files]
    if query:
        needle = query.strip().casefold()
        wells = [
            w
            for w in wells
            if needle == w.well_id.casefold()
            or needle in (w.city or "").casefold()
            or needle in (w.address or "").casefold()
            or needle in (w.region or "").casefold()
        ]
    if status:
        wells = [w for w in wells if (w.status or "").casefold() == status.casefold()]
    if region:
        wells = [w for w in wells if region.casefold() in (w.region or "").casefold()]
    return WellList(
        total_matched=len(wells),
        wells=wells[:limit],
        provenance=_provenance(
            constants.WFS_URL,
            cached,
            "WellList",
            lang,
            coverage=pick(
                lang,
                "Wells come from the provincial wells layer (GW_WATER_WELLS_WRBC_SVW); "
                "region from the groundwater-trends indicator table; data files from "
                f"{constants.WELL_BASE}/. Depth and ground elevation are in feet as recorded.",
                "Les puits viennent de la couche provinciale des puits "
                "(GW_WATER_WELLS_WRBC_SVW) ; la région, du tableau de l'indicateur des "
                "tendances des eaux souterraines ; les fichiers de données, de "
                f"{constants.WELL_BASE}/. La profondeur et l'altitude du sol sont en pieds, "
                "comme consignées.",
            ),
        ),
    )


async def get_well_levels(
    well: str,
    series: WellSeriesKind = "daily",
    start: str | None = None,
    end: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> WellSeries:
    _check_limit(limit, constants.ROWS_LIMIT_MAX, lang)
    low = bound(start, end=False, lang=lang, name="start")
    high = bound(end, end=True, lang=lang, name="end")
    text = well.strip().upper().removeprefix("OW")
    if not text.isdigit():
        raise_typed(
            InvalidInput,
            pick(
                lang,
                f"well must look like OW002 or 2; got {well!r}.",
                f"well doit avoir la forme OW002 ou 2 (reçu {well!r}).",
            ),
            lang,
        )
    well_id = f"OW{text.zfill(3)}"
    suffix = {"daily": "average", "hourly": "recent", "all": "data"}[series]
    url = f"{constants.WELL_BASE}/{well_id}-{suffix}.csv"
    try:
        body, cached = await _file(url, constants.CACHE_TTL_HOURLY_SECONDS, lang)
    except NotFound:
        raise_typed(
            NotFound,
            pick(
                lang,
                f"no {series} file for observation well {well_id}.",
                f"aucun fichier {series} pour le puits d'observation {well_id}.",
            ),
            lang,
        )
    header, rows = _rows(body)
    levels: list[WellLevel] = []
    for row in rows:
        record = dict(zip(header, row, strict=False))
        time = record.get("Time") or record.get("QualifiedTime") or ""
        if not time or not _in_period(norm_time(time), low, high):
            continue
        levels.append(
            WellLevel(
                time=time,
                depth_to_water_m=_float(record.get("Value")),
                approval=record.get("Approval") or None,
            )
        )
    levels.reverse()
    kept, truncated = _newest(levels, limit)
    return WellSeries(
        well_id=well_id,
        series=series,
        total_matched=len(levels),
        truncated=truncated,
        levels=kept,
        provenance=_provenance(
            url,
            cached,
            "WellSeries",
            lang,
            freshness=pick(
                lang,
                "Active wells update daily; inactive wells keep their last file.",
                "Les puits actifs sont mis à jour chaque jour ; les puits inactifs gardent leur "
                "dernier fichier.",
            ),
            limits=pick(lang, f"levels capped at {limit}", f"niveaux limités à {limit}")
            if truncated
            else None,
        ),
    )


# ------------------------------------------------------------ hydrometric


def water_year_start(now: datetime | None = None) -> str:
    moment = now or datetime.now(UTC)
    year = moment.year if moment.month >= 10 else moment.year - 1
    return f"{year}-10-01 00:00:00"


_MONTHS = {"Oct": "10"}


def archive_span(name: str, prefix: str) -> tuple[str | None, str | None] | None:
    """(from, to) of an archive file name, e.g. Discharge_Archive_2015Oct_2017Oct.csv."""
    match = re.fullmatch(rf"{prefix}_Archive_(.+)\.csv", name)
    if not match:
        return None
    tag = match.group(1)
    if tag.startswith("Pre_"):
        day = tag[4:]
        return None, f"{day[:4]}-{day[4:6]}-{day[6:8]} 00:00:00"
    if tag.startswith("Post_"):
        day = tag[5:]
        return f"{day[:4]}-{day[4:6]}-{day[6:8]} 00:00:00", None
    parts = re.fullmatch(r"(\d{4})([A-Za-z]{3})_(\d{4})([A-Za-z]{3})", tag)
    if not parts or parts.group(2) not in _MONTHS or parts.group(4) not in _MONTHS:
        return None
    first = f"{parts.group(1)}-{_MONTHS[parts.group(2)]}-01 00:00:00"
    last = f"{parts.group(3)}-{_MONTHS[parts.group(4)]}-01 00:00:00"
    return first, last


async def list_hydrometric_stations(
    query: str | None = None,
    limit: int = constants.LIST_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> HydroStationList:
    _check_limit(limit, constants.LIST_LIMIT_MAX, lang)
    stations: dict[str, HydroStation] = {}
    cached_all = True
    for parameter, prefix in constants.HYDRO_FILES.items():
        url = f"{constants.WATER_BASE}/{prefix}.csv"
        body, cached = await _file(url, constants.CACHE_TTL_HOURLY_SECONDS, lang)
        cached_all = cached_all and cached
        _, rows = _rows(body)
        for row in rows:
            if len(row) < 10:
                continue
            entry = stations.get(row[0])
            time = norm_time(row[5])
            if entry is None:
                entry = stations[row[0]] = HydroStation(
                    station_id=row[0],
                    name=row[1],
                    status=row[2] or None,
                    latitude=_float(row[3]),
                    longitude=_float(row[4]),
                    parameters=[],
                )
            if parameter not in entry.parameters:
                entry.parameters.append(parameter)
            if entry.latest_utc is None or time > entry.latest_utc:
                entry.latest_utc = time
    found = sorted(stations.values(), key=lambda s: s.station_id)
    if query:
        needle = query.strip().casefold()
        found = [
            s for s in found if needle in s.name.casefold() or s.station_id.casefold() == needle
        ]
    return HydroStationList(
        total_matched=len(found),
        stations=found[:limit],
        notes=[
            pick(
                lang,
                "Provincial network only: station ids follow the Water Survey of Canada "
                "sub-basin scheme with four digits (08HA0022) or an H prefix for partner "
                "stations, and none is a Water Survey of Canada station (compared on "
                "2026-10-03 with ECCC's 2,324 BC stations); use eccc_ tools for the federal "
                "network.",
                "Réseau provincial seulement : les identifiants suivent le découpage en "
                "sous-bassins de Relevés hydrologiques du Canada avec quatre chiffres "
                "(08HA0022) ou un préfixe H pour les stations partenaires, et aucune n'est une "
                "station de Relevés hydrologiques du Canada (comparaison du 2026-10-03 avec "
                "les 2 324 stations d'ECCC en Colombie-Britannique) ; utilisez les outils "
                "eccc_ pour le réseau fédéral.",
            ),
            pick(
                lang,
                "Listed from the current water-year files (since 1 October); discontinued "
                "stations appear only in the archives.",
                "Liste tirée des fichiers de l'année hydrologique en cours (depuis le "
                "1er octobre) ; les stations fermées ne figurent que dans les archives.",
            ),
        ],
        provenance=_provenance(
            f"{constants.WATER_BASE}/Discharge.csv",
            cached_all,
            "HydroStationList",
            lang,
            freshness=pick(
                lang,
                "Rewritten hourly.",
                "Réécrit toutes les heures.",
            ),
        ),
    )


async def get_hydrometric_data(
    station: str,
    parameter: HydroParameter = "discharge",
    start: str | None = None,
    end: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> HydroSeries:
    _check_limit(limit, constants.ROWS_LIMIT_MAX, lang)
    station_id = station.strip().upper()
    if not re.fullmatch(r"H?\d{2}[A-Z]{2}\d{4}", station_id):
        raise_typed(
            InvalidInput,
            pick(
                lang,
                f"station must be a provincial id such as 08HA0022 or H08KC0844; got {station!r}.",
                "station doit être un identifiant provincial, p. ex. 08HA0022 ou H08KC0844 "
                "(reçu {station!r}).",
            ),
            lang,
        )
    low = bound(start, end=False, lang=lang, name="start")
    high = bound(end, end=True, lang=lang, name="end")
    prefix = constants.HYDRO_FILES[parameter]
    current_from = water_year_start()
    plan: list[tuple[str, str | None, str | None]] = []
    if low is None or (high or "9999") >= current_from:
        plan.append((f"{prefix}.csv", current_from, None))
    if low is not None and low < current_from:
        files = await listing(f"{constants.WATER_BASE}/")
        for name in sorted(files):
            span = archive_span(name, prefix)
            if span is None:
                continue
            first, last = span
            if (last is None or low < last) and (first is None or (high or "9999") >= first):
                plan.append((name, first, last))
    readings: dict[str, HydroReading] = {}
    station_name: str | None = None
    notes: list[str] = []
    cached_all = True
    for name, _first, _last in plan:
        url = f"{constants.WATER_BASE}/{name}"
        if name == f"{prefix}.csv":
            body, cached = await _file(url, constants.CACHE_TTL_HOURLY_SECONDS, lang)
            cached_all = cached_all and cached
            _, rows = _rows(body)
            rows = [r for r in rows if r and r[0] == station_id]
        else:
            cached_all = False
            target = (station_id, low or "")
            rows, cut = await scan_sorted(
                url,
                key_of=lambda row: (row[0], norm_time(row[5])) if len(row) >= 10 else None,
                target=target,
                stop=lambda key: key[0] != station_id or (high is not None and key[1] > high),
            )
            if cut:
                notes.append(
                    pick(
                        lang,
                        f"{name}: read stopped at its byte cap; narrow the period.",
                        f"{name} : lecture arrêtée à sa limite d'octets ; resserrez la période.",
                    )
                )
            if not rows:
                notes.append(
                    pick(
                        lang,
                        f"{name}: no rows for {station_id} in the period.",
                        f"{name} : aucune ligne pour {station_id} dans la période.",
                    )
                )
        for row in rows:
            if len(row) < 10:
                continue
            time = norm_time(row[5])
            if not _in_period(time, low, high):
                continue
            station_name = station_name or row[1]
            readings[time] = HydroReading(
                time_utc=time, value=_float(row[7]), unit=row[8] or None, grade=row[9] or None
            )
    ordered = [readings[k] for k in sorted(readings, reverse=True)]
    kept, truncated = _newest(ordered, limit)
    if not ordered and station_name is None:
        notes.append(
            pick(
                lang,
                f"No {parameter} rows for {station_id}; check the id with "
                "bc_env_list_streamflow_gauges, or widen the period.",
                f"Aucune ligne {parameter} pour {station_id} ; vérifiez l'identifiant avec "
                "bc_env_list_streamflow_gauges ou élargissez la période.",
            )
        )
    return HydroSeries(
        station_id=station_id,
        station_name=station_name,
        parameter=parameter,
        files=[name for name, _, _ in plan],
        total_matched=len(ordered),
        truncated=truncated,
        readings=kept,
        notes=notes,
        provenance=_provenance(
            f"{constants.WATER_BASE}/{plan[0][0] if plan else prefix + '.csv'}",
            cached_all,
            "HydroSeries",
            lang,
            freshness=pick(
                lang,
                "Current water-year file rewritten hourly; archives per water year.",
                "Fichier de l'année hydrologique en cours réécrit toutes les heures ; archives par "
                "année hydrologique.",
            ),
            limits=pick(lang, f"readings capped at {limit}", f"lectures limités à {limit}")
            if truncated
            else None,
        ),
    )
