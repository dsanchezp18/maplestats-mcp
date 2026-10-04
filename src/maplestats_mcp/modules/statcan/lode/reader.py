"""Readers for the three formats LODE zips carry: GeoPackage, GeoJSON and CSV.

All three apply the same filters: province, census subdivision, type and
name (accent- and case-insensitive), a lon/lat bounding box, and exact
matches on any column. GeoPackages are SQLite files, read with the standard
library (an R-tree narrows bounding-box queries); CSVs are read with DuckDB,
already a dependency for the PUMF tools; GeoJSON is small enough to parse in
memory. These functions block, so callers run them in a thread.
"""

from __future__ import annotations

import codecs
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from maplestats_mcp.modules.statcan.lang import say
from maplestats_mcp.modules.statcan.lode import constants, geometry
from maplestats_mcp.modules.statcan.lode.schemas import LodeField, LodeLayer, Scalar
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError

ROLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "province": ("prov_terr", "province_code", "pruid", "province", "prov"),
    "csd": ("csdname", "csd_name"),
    "csduid": ("csduid",),
    "type": ("type", "facility_type", "odcaf_facility_type", "sub_type"),
    "name": ("name", "facility_name", "full_addr", "full_address", "csdname"),
}
_LAT = ("latitude", "lat")
_LON = ("longitude", "lon", "long")


def fold(value: object) -> str:
    """Lower-case text without accents, trimmed."""
    text = unicodedata.normalize("NFKD", str(value))
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


@dataclass
class QuerySpec:
    province: str | None = None
    csd: str | None = None
    type: str | None = None
    name: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    filters: dict[str, str] = field(default_factory=dict)
    limit: int = constants.RECORDS_DEFAULT
    layer: str | None = None

    def described(self) -> dict[str, str]:
        out = {
            k: v
            for k, v in (
                ("province", self.province),
                ("csd", self.csd),
                ("type", self.type),
                ("name", self.name),
            )
            if v
        }
        if self.bbox:
            out["bbox"] = ",".join(f"{v:g}" for v in self.bbox)
        out.update({f"filter:{k}": v for k, v in self.filters.items()})
        return out


@dataclass
class Outcome:
    columns: list[str]
    records: list[dict[str, Scalar]]
    total: int
    lower_bound: bool = False
    layer: str | None = None
    crs: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Cond:
    column: str
    op: str  # "eq", "has" (substring) or "in"
    value: str | frozenset[str]


def province_values(text: str) -> frozenset[str]:
    """Every spelling a province filter may match: code, PRUID, English and French name."""
    wanted = fold(text)
    wanted = fold(constants.PROVINCE_ALIASES.get(wanted, wanted))
    for code, (pruid, en, fr) in constants.PROVINCES.items():
        spellings = {code.lower(), pruid, fold(en), fold(fr)}
        if wanted in spellings:
            return frozenset(spellings)
    raise InvalidInput(
        say(
            f"province must be a code such as ON, a name or a PRUID, got {text!r}.",
            f"province doit être un code comme ON, un nom ou un PRUID, reçu {text!r}.",
        )
    )


def province_code(text: str) -> str:
    values = province_values(text)
    return next(code for code, (pruid, *_rest) in constants.PROVINCES.items() if pruid in values)


def role_column(columns: list[str], role: str) -> str | None:
    lower = {c.lower(): c for c in columns}
    for candidate in ROLE_COLUMNS[role]:
        if candidate in lower:
            return lower[candidate]
    return None


def conditions(spec: QuerySpec, columns: list[str]) -> list[Cond]:
    out: list[Cond] = []

    def need(role: str, what: str) -> str:
        column = role_column(columns, role)
        if column is None:
            raise InvalidInput(
                say(
                    f"This file has no {what} column, so that filter cannot apply. "
                    f"Columns: {', '.join(columns)}.",
                    f"Ce fichier n'a pas de colonne {what}, donc ce filtre ne peut pas s'appliquer. Colonnes : {', '.join(columns)}.",
                )
            )
        return column

    if spec.province:
        out.append(Cond(need("province", "province"), "in", province_values(spec.province)))
    if spec.csd:
        if spec.csd.strip().isdigit() and role_column(columns, "csduid"):
            out.append(Cond(need("csduid", "csduid"), "eq", fold(spec.csd)))
        else:
            out.append(Cond(need("csd", "census subdivision name"), "eq", fold(spec.csd)))
    if spec.type:
        out.append(Cond(need("type", "type"), "eq", fold(spec.type)))
    if spec.name:
        out.append(Cond(need("name", "name"), "has", fold(spec.name)))
    lower = {c.lower(): c for c in columns}
    for key, value in spec.filters.items():
        column = lower.get(key.lower())
        if column is None:
            raise InvalidInput(
                say(
                    f"No column {key!r}. Columns: {', '.join(columns)}.",
                    f"Aucune colonne {key!r}. Colonnes : {', '.join(columns)}.",
                )
            )
        out.append(Cond(column, "eq", fold(value)))
    return out


def tidy(value: Any) -> Scalar:
    # StatCan prints ".." for "not available"; blanks and bytes are not data.
    if isinstance(value, bytes):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return None if stripped in ("", "..") else stripped
    return value


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _in_box(lon: float | None, lat: float | None, box: tuple[float, float, float, float]) -> bool:
    return (
        lon is not None and lat is not None and box[0] <= lon <= box[2] and box[1] <= lat <= box[3]
    )


def _validate_bbox(box: tuple[float, float, float, float]) -> None:
    west, south, east, north = box
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise InvalidInput(
            say(
                "bbox must be west,south,east,north in degrees, e.g. -75.8,45.3,-75.6,45.5.",
                "bbox doit être ouest,sud,est,nord en degrés, p. ex. -75.8,45.3,-75.6,45.5.",
            )
        )


def _matches(row: dict[str, Any], conds: list[Cond]) -> bool:
    for cond in conds:
        cell = row.get(cond.column)
        text = "" if cell is None else fold(cell)
        if cond.op == "in" and text not in cond.value:
            return False
        if cond.op == "eq" and text != cond.value:
            return False
        if cond.op == "has" and str(cond.value) not in text:
            return False
    return True


# --- GeoPackage ---------------------------------------------------------


def gpkg_layers(path: Path) -> list[LodeLayer]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        layers: list[LodeLayer] = []
        for table, srs in con.execute(
            "SELECT table_name, srs_id FROM gpkg_contents WHERE data_type = 'features'"
        ).fetchall():
            geom = con.execute(
                "SELECT geometry_type_name FROM gpkg_geometry_columns WHERE table_name = ?",
                (table,),
            ).fetchone()
            count = con.execute(f"SELECT count(*) FROM {_quote(table)}").fetchone()[0]
            layers.append(
                LodeLayer(
                    name=table,
                    geometry_type=geom[0] if geom else None,
                    crs=f"EPSG:{srs}" if srs is not None else None,
                    feature_count=int(count),
                )
            )
        return layers
    except sqlite3.DatabaseError as exc:
        raise UpstreamError(
            say(f"Not a readable GeoPackage: {exc}", f"GeoPackage illisible : {exc}")
        ) from exc
    finally:
        con.close()


def gpkg_schema(path: Path, layer: str | None) -> tuple[list[LodeField], str]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        table, geom_col, _ = _gpkg_table(con, layer)
        fields = [
            LodeField(name=row[1], type=row[2] or None)
            for row in con.execute(f"PRAGMA table_info({_quote(table)})")
            if row[1] != geom_col
        ]
        return fields, table
    finally:
        con.close()


def _gpkg_table(con: sqlite3.Connection, layer: str | None) -> tuple[str, str, str]:
    rows = con.execute(
        "SELECT c.table_name, g.column_name, c.srs_id FROM gpkg_contents c "
        "JOIN gpkg_geometry_columns g ON g.table_name = c.table_name "
        "WHERE c.data_type = 'features'"
    ).fetchall()
    if not rows:
        raise UpstreamError(
            say(
                "The GeoPackage has no feature layer.", "Le GeoPackage n'a aucune couche d'entités."
            )
        )
    if layer:
        for table, column, srs in rows:
            if table.lower() == layer.lower():
                return table, column, _gpkg_crs(con, srs)
        names = ", ".join(r[0] for r in rows)
        raise InvalidInput(
            say(
                f"No layer {layer!r}. Layers: {names}.",
                f"Aucune couche {layer!r}. Couches : {names}.",
            )
        )
    table, column, srs = rows[0]
    return table, column, _gpkg_crs(con, srs)


def _gpkg_crs(con: sqlite3.Connection, srs_id: int) -> str:
    row = con.execute(
        "SELECT srs_name, definition FROM gpkg_spatial_ref_sys WHERE srs_id = ?", (srs_id,)
    ).fetchone()
    return geometry.crs_kind(srs_id, row[1] if row else None, row[0] if row else None)


def query_gpkg(path: Path, spec: QuerySpec) -> Outcome:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.create_function("fold", 1, lambda v: None if v is None else fold(v), deterministic=True)
    try:
        table, geom_col, kind = _gpkg_table(con, spec.layer)
        info = con.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
        columns = [r[1] for r in info if r[1] != geom_col]
        pk = next((r[1] for r in info if r[5]), None)
        conds = conditions(spec, columns)
        where: list[str] = []
        params: list[Any] = []
        for cond in conds:
            col = f"fold({_quote(cond.column)})"
            if cond.op == "in":
                values = sorted(cond.value)
                where.append(f"{col} IN ({','.join('?' * len(values))})")
                params.extend(values)
            elif cond.op == "has":
                where.append(f"instr({col}, ?) > 0")
                params.append(cond.value)
            else:
                where.append(f"{col} = ?")
                params.append(cond.value)
        notes: list[str] = []
        if spec.bbox:
            _validate_bbox(spec.bbox)
            if kind == "unknown":
                raise InvalidInput(
                    say(
                        "This file's coordinate system is not supported for bbox.",
                        "Le système de coordonnées de ce fichier n'est pas pris en charge pour bbox.",
                    )
                )
            rtree = f"rtree_{table}_{geom_col}"
            has_rtree = con.execute(
                "SELECT 1 FROM sqlite_master WHERE name = ?", (rtree,)
            ).fetchone()
            if has_rtree and pk:
                x0, y0, x1, y1 = (
                    geometry.projected_bbox(spec.bbox) if kind == "lambert" else spec.bbox
                )
                where.append(
                    f"{_quote(pk)} IN (SELECT id FROM {_quote(rtree)} "
                    "WHERE minx <= ? AND maxx >= ? AND miny <= ? AND maxy >= ?)"
                )
                params.extend([x1, x0, y1, y0])
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        select = ", ".join(_quote(c) for c in columns)
        if kind == "lambert":
            crs = "EPSG:3347 (converted to WGS 84)"
        elif kind == "lonlat":
            crs = "WGS 84"
        else:
            crs = "unsupported; coordinates not converted"
        total_is_exact = not spec.bbox
        records: list[dict[str, Scalar]] = []
        total = 0
        lower = False
        if total_is_exact:
            total = con.execute(f"SELECT count(*) FROM {_quote(table)}{clause}", params).fetchone()[
                0
            ]
        cursor = con.execute(
            f"SELECT {select}, {_quote(geom_col)} FROM {_quote(table)}{clause}", params
        )
        scanned = 0
        for row in cursor:
            scanned += 1
            if scanned > constants.SCAN_ROWS_MAX:
                lower = True
                break
            decoded = geometry.decode_gpkg_geometry(row[-1])
            lon: float | None = None
            lat: float | None = None
            gtype: str | None = None
            if decoded:
                lon, lat = geometry.to_lonlat(decoded[0], decoded[1], kind)
                gtype = decoded[2]
            if spec.bbox and not _in_box(lon, lat, spec.bbox):
                continue
            if not total_is_exact:
                total += 1
            if len(records) < spec.limit:
                record: dict[str, Scalar] = {
                    c: tidy(v) for c, v in zip(columns, row[:-1], strict=True)
                }
                record["longitude"] = None if lon is None else round(lon, 6)
                record["latitude"] = None if lat is None else round(lat, 6)
                record["geometry_type"] = gtype
                records.append(record)
            elif total_is_exact:
                break
        if lower:
            notes.append(
                say(
                    f"Stopped after {constants.SCAN_ROWS_MAX:,} rows; total_matched is a lower "
                    "bound. Add province, csd or a smaller bbox.",
                    f"Arrêt après {constants.SCAN_ROWS_MAX:,} lignes ; total_matched est une borne "
                    "inférieure. Ajoutez province, csd ou une bbox plus petite.",
                )
            )
        return Outcome(columns, records, total, lower, table, crs, notes)
    except sqlite3.DatabaseError as exc:
        raise UpstreamError(
            say(f"GeoPackage could not be read: {exc}", f"Le GeoPackage n'a pas pu être lu : {exc}")
        ) from exc
    finally:
        con.close()


# --- GeoJSON ------------------------------------------------------------


def _geojson_kind(data: dict[str, Any]) -> str:
    crs = data.get("crs")
    name = ""
    if isinstance(crs, dict):
        props = crs.get("properties")
        if isinstance(props, dict):
            name = str(props.get("name", ""))
    match = re.search(r"EPSG::?(\d+)", name)
    return geometry.crs_kind(int(match.group(1)) if match else None, None, name)


def read_geojson(path: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        data = json.loads(path.read_bytes())
    except ValueError as exc:
        raise UpstreamError(
            say(
                f"GeoJSON could not be parsed: {exc}", f"Le GeoJSON n'a pas pu être analysé : {exc}"
            )
        ) from exc
    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list):
        raise UpstreamError(
            say("GeoJSON has no features list.", "Le GeoJSON n'a pas de liste features.")
        )
    kind = _geojson_kind(data)
    if kind == "unknown" and isinstance(data.get("crs"), dict):
        raise InvalidInput(
            say(
                "This GeoJSON uses a coordinate system that is not supported.",
                "Ce GeoJSON utilise un système de coordonnées non pris en charge.",
            )
        )
    return features, "lonlat" if kind == "unknown" else kind


def query_geojson(path: Path, spec: QuerySpec) -> Outcome:
    features, kind = read_geojson(path)
    first = features[0].get("properties", {}) if features else {}
    columns = list(first)
    conds = conditions(spec, columns)
    if spec.bbox:
        _validate_bbox(spec.bbox)
    records: list[dict[str, Scalar]] = []
    total = 0
    for feature in features:
        props = feature.get("properties") or {}
        if not _matches(props, conds):
            continue
        centre = geometry.geojson_centre(feature.get("geometry"))
        lon = lat = None
        gtype = None
        if centre:
            lon, lat = geometry.to_lonlat(centre[0], centre[1], kind)
            gtype = centre[2]
        if spec.bbox and not _in_box(lon, lat, spec.bbox):
            continue
        total += 1
        if len(records) < spec.limit:
            record: dict[str, Scalar] = {c: tidy(props.get(c)) for c in columns}
            record["longitude"] = None if lon is None else round(lon, 6)
            record["latitude"] = None if lat is None else round(lat, 6)
            record["geometry_type"] = gtype
            records.append(record)
    crs = "EPSG:3347 (converted to WGS 84)" if kind == "lambert" else "WGS 84"
    return Outcome(columns, records, total, False, None, crs)


# --- CSV ----------------------------------------------------------------


def clean_utf8(path: Path) -> Path:
    """The file itself when it is valid UTF-8, else a cleaned copy.

    ODCAF's CSV (checked live 2026-10-02) mixes UTF-8 with stray bytes that
    are neither UTF-8 nor Latin-1, which DuckDB rejects under either
    encoding; the copy replaces them with U+FFFD and sits beside the original.
    """
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1 << 20):
                decoder.decode(chunk)
            decoder.decode(b"", final=True)
        return path
    except UnicodeDecodeError:
        pass
    target = path.with_suffix(".utf8.csv")
    if not target.exists():
        lenient = codecs.getincrementaldecoder("utf-8")(errors="replace")
        with path.open("rb") as source, target.open("w", encoding="utf-8", newline="") as sink:
            while chunk := source.read(1 << 20):
                sink.write(lenient.decode(chunk))
            sink.write(lenient.decode(b"", final=True))
    return target


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _csv_relation(path: Path) -> str:
    return (
        f"read_csv({_literal(str(clean_utf8(path)))}, header = true, all_varchar = true, "
        "null_padding = true)"
    )


def csv_columns(path: Path) -> list[str]:
    con = duckdb.connect()
    try:
        return [
            r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {_csv_relation(path)}").fetchall()
        ]
    except duckdb.Error as exc:
        raise UpstreamError(
            say(f"CSV could not be read: {exc}", f"Le CSV n'a pas pu être lu : {exc}")
        ) from exc
    finally:
        con.close()


def _coordinate_sql(columns: list[str]) -> tuple[str, str] | None:
    lower = {c.lower(): c for c in columns}
    lat = next((lower[c] for c in _LAT if c in lower), None)
    lon = next((lower[c] for c in _LON if c in lower), None)
    if lat and lon:
        return f"TRY_CAST({_quote(lon)} AS DOUBLE)", f"TRY_CAST({_quote(lat)} AS DOUBLE)"
    wkt = next((lower[c] for c in ("geometry", "wkt") if c in lower), None)
    if wkt:
        pattern = _literal(r"POINT\s*\(\s*(-?[0-9.]+)\s+(-?[0-9.]+)")
        return (
            f"TRY_CAST(regexp_extract({_quote(wkt)}, {pattern}, 1) AS DOUBLE)",
            f"TRY_CAST(regexp_extract({_quote(wkt)}, {pattern}, 2) AS DOUBLE)",
        )
    return None


def query_csv(path: Path, spec: QuerySpec) -> Outcome:
    columns = csv_columns(path)
    conds = conditions(spec, columns)
    coords = _coordinate_sql(columns)
    where: list[str] = []
    params: list[Any] = []
    for cond in conds:
        col = f"trim(strip_accents(lower({_quote(cond.column)})))"
        if cond.op == "in":
            values = sorted(cond.value)
            where.append(f"{col} IN ({','.join('?' * len(values))})")
            params.extend(values)
        elif cond.op == "has":
            where.append(f"contains({col}, ?)")
            params.append(cond.value)
        else:
            where.append(f"{col} = ?")
            params.append(cond.value)
    if spec.bbox:
        _validate_bbox(spec.bbox)
        if coords is None:
            raise InvalidInput(
                say(
                    "This file has no coordinates, so bbox cannot apply.",
                    "Ce fichier n'a pas de coordonnées, donc bbox ne peut pas s'appliquer.",
                )
            )
        where.append("__lon BETWEEN ? AND ? AND __lat BETWEEN ? AND ?")
        params.extend([spec.bbox[0], spec.bbox[2], spec.bbox[1], spec.bbox[3]])
    lon_sql, lat_sql = coords if coords else ("NULL", "NULL")
    source = f"(SELECT *, {lon_sql} AS __lon, {lat_sql} AS __lat FROM {_csv_relation(path)}) AS src"
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    con = duckdb.connect()
    try:
        total = con.execute(f"SELECT count(*) FROM {source}{clause}", params).fetchone()[0]  # type: ignore[index]
        select = ", ".join(_quote(c) for c in columns)
        rows = con.execute(
            f"SELECT {select}, __lon, __lat FROM {source}{clause} LIMIT {int(spec.limit)}", params
        ).fetchall()
    except duckdb.Error as exc:
        raise UpstreamError(
            say(f"CSV could not be queried: {exc}", f"Le CSV n'a pas pu être interrogé : {exc}")
        ) from exc
    finally:
        con.close()
    own = {c.lower() for c in columns}
    records: list[dict[str, Scalar]] = []
    for row in rows:
        record: dict[str, Scalar] = {c: tidy(v) for c, v in zip(columns, row[:-2], strict=True)}
        if coords and "longitude" not in own and "latitude" not in own:
            record["longitude"] = row[-2]
            record["latitude"] = row[-1]
        records.append(record)
    return Outcome(columns, records, int(total), False, None, "WGS 84" if coords else None)


def csv_sample(path: Path) -> list[LodeField]:
    con = duckdb.connect()
    try:
        cursor = con.execute(f"SELECT * FROM {_csv_relation(path)} LIMIT 1")
        names = [d[0] for d in cursor.description]
        row = cursor.fetchone() or [None] * len(names)
    except duckdb.Error as exc:
        raise UpstreamError(
            say(f"CSV could not be read: {exc}", f"Le CSV n'a pas pu être lu : {exc}")
        ) from exc
    finally:
        con.close()
    return [LodeField(name=n, example=tidy(v)) for n, v in zip(names, row, strict=True)]
