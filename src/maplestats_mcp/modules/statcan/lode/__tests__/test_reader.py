"""Readers, on small files built with the same quirks as the real ones."""

from __future__ import annotations

import json
import sqlite3
import struct
from pathlib import Path

import pytest

from maplestats_mcp.modules.statcan.lode import geometry, reader
from maplestats_mcp.shared.errors import InvalidInput

# Ottawa, Montreal, Halifax as (name, type, province, csd, lon, lat).
PLACES = [
    ("Hôpital général", "Hospital", "ON", "Ottawa", -75.70, 45.40),
    ("Hôpital Santa Cabrini", "Hospital", "QC", "Montréal", -73.57, 45.58),
    ("Halifax Pharmacy", "Pharmacy", "NS", "Halifax", -63.57, 44.65),
]


def _lambert_point(lon: float, lat: float) -> bytes:
    x, y = geometry.lonlat_to_lambert(lon, lat)
    return b"GP\x00\x01" + struct.pack("<i", 3347) + struct.pack("<BIdd", 1, 1, x, y)


def make_gpkg(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT, srs_id INTEGER, organization TEXT,
            organization_coordsys_id INTEGER, definition TEXT, description TEXT);
        INSERT INTO gpkg_spatial_ref_sys VALUES ('NAD83 / Statistics Canada Lambert', 3347,
            'EPSG', 3347, 'PROJCS["NAD83 / Statistics Canada Lambert"]', NULL);
        CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT, srs_id INTEGER);
        INSERT INTO gpkg_contents VALUES ('places', 'features', 3347);
        CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT,
            geometry_type_name TEXT, srs_id INTEGER, z INTEGER, m INTEGER);
        INSERT INTO gpkg_geometry_columns VALUES ('places', 'geom', 'POINT', 3347, 0, 0);
        CREATE TABLE places (fid INTEGER PRIMARY KEY, geom BLOB, name TEXT, type TEXT,
            prov_terr TEXT, csdname TEXT, address TEXT);
        CREATE VIRTUAL TABLE rtree_places_geom USING rtree(id, minx, maxx, miny, maxy);
        """
    )
    for i, (name, kind, prov, csd, lon, lat) in enumerate(PLACES, start=1):
        x, y = geometry.lonlat_to_lambert(lon, lat)
        con.execute(
            "INSERT INTO places VALUES (?, ?, ?, ?, ?, ?, ?)",
            (i, _lambert_point(lon, lat), name, kind, prov, csd, ".." if i == 1 else "1 Main St"),
        )
        con.execute("INSERT INTO rtree_places_geom VALUES (?, ?, ?, ?, ?)", (i, x, x, y, y))
    con.commit()
    con.close()
    return path


def make_geojson(path: Path) -> Path:
    features = []
    for name, kind, prov, csd, lon, lat in PLACES:
        x, y = geometry.lonlat_to_lambert(lon, lat)
        features.append(
            {
                "type": "Feature",
                "properties": {"name": name, "type": kind, "prov_terr": prov, "csdname": csd},
                "geometry": {"type": "Point", "coordinates": [x, y]},
            }
        )
    crs = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3347"}}
    path.write_text(
        json.dumps({"type": "FeatureCollection", "crs": crs, "features": features}), "utf-8"
    )
    return path


def test_gpkg_filters_accent_insensitive_and_converts_coordinates(tmp_path: Path) -> None:
    path = make_gpkg(tmp_path / "p.gpkg")
    out = reader.query_gpkg(path, reader.QuerySpec(name="hopital", province="Quebec"))
    assert out.total == 1
    record = out.records[0]
    assert record["name"] == "Hôpital Santa Cabrini"
    assert record["longitude"] == pytest.approx(-73.57, abs=1e-5)
    assert record["latitude"] == pytest.approx(45.58, abs=1e-5)
    assert record["geometry_type"] == "Point"
    assert "geom" not in record


def test_gpkg_dots_become_null_and_limit_keeps_exact_total(tmp_path: Path) -> None:
    path = make_gpkg(tmp_path / "p.gpkg")
    out = reader.query_gpkg(path, reader.QuerySpec(type="hospital", limit=1))
    assert out.total == 2
    assert len(out.records) == 1
    assert out.records[0]["address"] is None


def test_gpkg_bbox_uses_the_rtree_and_exact_lonlat(tmp_path: Path) -> None:
    path = make_gpkg(tmp_path / "p.gpkg")
    out = reader.query_gpkg(path, reader.QuerySpec(bbox=(-76.0, 45.0, -75.0, 46.0)))
    assert [r["name"] for r in out.records] == ["Hôpital général"]
    assert out.total == 1
    assert out.crs == "EPSG:3347 (converted to WGS 84)"


def test_gpkg_layers_and_schema(tmp_path: Path) -> None:
    path = make_gpkg(tmp_path / "p.gpkg")
    layer = reader.gpkg_layers(path)[0]
    assert (layer.name, layer.geometry_type, layer.feature_count) == ("places", "POINT", 3)
    fields, table = reader.gpkg_schema(path, None)
    assert table == "places"
    assert "geom" not in [f.name for f in fields]


def test_unknown_filter_column_and_province_are_input_errors(tmp_path: Path) -> None:
    path = make_gpkg(tmp_path / "p.gpkg")
    with pytest.raises(InvalidInput, match="No column"):
        reader.query_gpkg(path, reader.QuerySpec(filters={"nope": "x"}))
    with pytest.raises(InvalidInput, match="province must be"):
        reader.query_gpkg(path, reader.QuerySpec(province="Atlantis"))
    with pytest.raises(InvalidInput, match="bbox must be"):
        reader.query_gpkg(path, reader.QuerySpec(bbox=(1, 2, 0, 3)))


def test_geojson_declared_3347_is_converted(tmp_path: Path) -> None:
    path = make_geojson(tmp_path / "p.geojson")
    out = reader.query_geojson(path, reader.QuerySpec(csd="Halifax"))
    assert out.total == 1
    assert out.records[0]["longitude"] == pytest.approx(-63.57, abs=1e-5)
    out = reader.query_geojson(path, reader.QuerySpec(province="ON", bbox=(-76, 45, -75, 46)))
    assert out.total == 1


def test_csv_with_stray_bytes_blank_header_and_wkt(tmp_path: Path) -> None:
    # ODCAF mixes UTF-8 with bytes that are neither UTF-8 nor Latin-1; ODEF stores
    # POINT (lon lat); the remoteness file has an unnamed first column.
    path = tmp_path / "d.csv"
    rows = [
        b",province_code,facility_name,geometry\n",
        b'0,ON,"Caf\xc3\xa9 \xff School","POINT (-75.7 45.4)"\n',
        b'1,BC,Other,"POINT (-123.3 48.4)"\n',
    ]
    path.write_bytes(b"".join(rows))
    out = reader.query_csv(path, reader.QuerySpec(province="Ontario", name="cafe"))
    assert out.total == 1
    record = out.records[0]
    assert record["longitude"] == pytest.approx(-75.7)
    assert record["latitude"] == pytest.approx(45.4)
    assert "School" in str(record["facility_name"])
    assert reader.query_csv(path, reader.QuerySpec(bbox=(-124, 48, -123, 49))).total == 1


def test_csv_without_coordinates_rejects_bbox(tmp_path: Path) -> None:
    path = tmp_path / "d.csv"
    path.write_text("Pruid,CSDname\n62,Iqaluit\n", "utf-8")
    assert reader.query_csv(path, reader.QuerySpec(csd="iqaluit")).total == 1
    with pytest.raises(InvalidInput, match="no coordinates"):
        reader.query_csv(path, reader.QuerySpec(bbox=(-70, 60, -60, 70)))


def test_province_values_accept_code_name_pruid_and_alias() -> None:
    assert "ab" in reader.province_values("Alberta")
    assert "48" in reader.province_values("AB")
    assert reader.province_code("Québec") == "QC"
    assert reader.province_code("Yukon Territory") == "YT"
    assert reader.province_code("35") == "ON"
