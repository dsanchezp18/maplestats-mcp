"""Coordinates in LODE files: GeoPackage blobs and Statistics Canada Lambert.

StatCan publishes these databases in EPSG:3347 (Statistics Canada Lambert,
metres), including the GeoJSON (ODHF's file declares
`urn:ogc:def:crs:EPSG::3347` yet GeoJSON readers expect degrees) and the
GeoPackages (srs_id 3347, or a custom 100000 defined as
"NAD83_Statistics_Canada_Lambert" in ODI). Without a projection library,
the conversion is the standard two-parallel Lambert conformal conic on the
GRS80 ellipsoid. Checked 2026-10-02 against the ODG GeoPackage, which stores
both a 3347 geometry and Latitude/Longitude columns: the inverse agrees to
1e-9 degrees.
"""

from __future__ import annotations

import math
import struct

_A = 6378137.0
_F = 1 / 298.257222101
_E = math.sqrt(2 * _F - _F * _F)
_LAT1, _LAT2, _LAT0, _LON0 = (math.radians(v) for v in (49.0, 77.0, 63.390675, -91.86666666666666))
_X0, _Y0 = 6200000.0, 3000000.0

_GEOMETRY_NAMES = {
    1: "Point",
    2: "LineString",
    3: "Polygon",
    4: "MultiPoint",
    5: "MultiLineString",
    6: "MultiPolygon",
    7: "GeometryCollection",
}
_ENVELOPE_BYTES = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}


def _m(phi: float) -> float:
    s = math.sin(phi)
    return math.cos(phi) / math.sqrt(1 - _E * _E * s * s)


def _t(phi: float) -> float:
    s = math.sin(phi)
    return math.tan(math.pi / 4 - phi / 2) / ((1 - _E * s) / (1 + _E * s)) ** (_E / 2)


_N = (math.log(_m(_LAT1)) - math.log(_m(_LAT2))) / (math.log(_t(_LAT1)) - math.log(_t(_LAT2)))
_BIG_F = _m(_LAT1) / (_N * _t(_LAT1) ** _N)
_RHO0 = _A * _BIG_F * _t(_LAT0) ** _N


def lambert_to_lonlat(x: float, y: float) -> tuple[float, float]:
    """EPSG:3347 metres to (longitude, latitude) in degrees."""
    dx, dy = x - _X0, _RHO0 - (y - _Y0)
    rho = math.hypot(dx, dy)
    tt = (rho / (_A * _BIG_F)) ** (1 / _N)
    theta = math.atan2(dx, dy)
    phi = math.pi / 2 - 2 * math.atan(tt)
    for _ in range(8):
        s = math.sin(phi)
        phi = math.pi / 2 - 2 * math.atan(tt * ((1 - _E * s) / (1 + _E * s)) ** (_E / 2))
    return math.degrees(theta / _N + _LON0), math.degrees(phi)


def lonlat_to_lambert(lon: float, lat: float) -> tuple[float, float]:
    rho = _A * _BIG_F * _t(math.radians(lat)) ** _N
    theta = _N * (math.radians(lon) - _LON0)
    return _X0 + rho * math.sin(theta), _Y0 + _RHO0 - rho * math.cos(theta)


def projected_bbox(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """The EPSG:3347 box that contains a lon/lat box (west, south, east, north).

    A rectangle in degrees is curved in Lambert, so the edges are sampled
    (a 9 x 9 grid) and a 100 m margin added. This only narrows the rows an
    R-tree returns; the exact test is done on each feature's lon/lat.
    """
    west, south, east, north = bbox
    points = [
        lonlat_to_lambert(west + (east - west) * i / 8, south + (north - south) * j / 8)
        for i in range(9)
        for j in range(9)
    ]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs) - 100, min(ys) - 100, max(xs) + 100, max(ys) + 100


def crs_kind(srs_id: int | None, definition: str | None = None, name: str | None = None) -> str:
    """'lambert', 'lonlat' or 'unknown' from an SRS id and, if given, its WKT or name."""
    text = f"{definition or ''} {name or ''}".lower()
    if srs_id in (3347, 100000) or "statistics_canada_lambert" in text or "3347" in text:
        return "lambert"
    if srs_id in (4326, 4269, 4617) or "crs84" in text:
        return "lonlat"
    return "unknown"


def to_lonlat(x: float, y: float, kind: str) -> tuple[float | None, float | None]:
    if kind == "lambert":
        return lambert_to_lonlat(x, y)
    if kind == "lonlat":
        return x, y
    return None, None


def decode_gpkg_geometry(blob: bytes | None) -> tuple[float, float, str | None] | None:
    """(x, y, geometry type) of a GeoPackage geometry blob, in its own CRS.

    A point returns its coordinates; any other type returns the centre of
    the header's bounding box. None for an empty or unreadable geometry.
    """
    if not blob or len(blob) < 8 or blob[:2] != b"GP":
        return None
    flags = blob[3]
    if flags & 0x10:  # empty geometry
        return None
    order = "<" if flags & 1 else ">"
    envelope = (flags >> 1) & 7
    header = 8 + _ENVELOPE_BYTES.get(envelope, 0)
    wkb = blob[header:]
    if len(wkb) < 5:
        return None
    wkb_order = "<" if wkb[0] == 1 else ">"
    code = struct.unpack(wkb_order + "I", wkb[1:5])[0] % 1000
    name = _GEOMETRY_NAMES.get(code)
    if code == 1 and len(wkb) >= 21:
        x, y = struct.unpack(wkb_order + "2d", wkb[5:21])
        return x, y, name
    if envelope in _ENVELOPE_BYTES and envelope:
        min_x, max_x, min_y, max_y = struct.unpack(order + "4d", blob[8:40])
        return (min_x + max_x) / 2, (min_y + max_y) / 2, name
    return None


def geojson_centre(geometry: dict[str, object] | None) -> tuple[float, float, str | None] | None:
    """(x, y, type) of a GeoJSON geometry: the point itself, else the box centre."""
    if not isinstance(geometry, dict):
        return None
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "Point" and isinstance(coordinates, list) and len(coordinates) >= 2:
        return float(coordinates[0]), float(coordinates[1]), "Point"
    xs: list[float] = []
    ys: list[float] = []

    def walk(node: object) -> None:
        if isinstance(node, list):
            if len(node) >= 2 and all(isinstance(v, (int, float)) for v in node[:2]):
                xs.append(float(node[0]))
                ys.append(float(node[1]))
            else:
                for child in node:
                    walk(child)

    walk(coordinates)
    if not xs:
        return None
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, str(kind) if kind else None
