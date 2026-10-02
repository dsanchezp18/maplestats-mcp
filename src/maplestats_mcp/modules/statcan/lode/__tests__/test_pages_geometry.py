"""Page parsers and coordinate maths, on excerpts of the real pages (2026-10-02)."""

from __future__ import annotations

import struct

import pytest

from maplestats_mcp.modules.statcan.lode import geometry, pages

LANDING = """
<section class="panel panel-default"><header class="panel-heading"><h3 class="panel-title h3">The Open Database of Healthcare Facilities</h3></header>
<div class="row panel-body"><div class="col-xs-12 col-sm-8"><p><a href="https://www150.statcan.gc.ca/n1/pub/13-26-0001/132600012020001-eng.htm">The Open Database of Healthcare Facilities (ODHF)</a> contains the names&nbsp;and addresses of facilities. About 22,000 records.</p><p>Release dates:</p><ul><li>September 24, 2026 &#8212; Version 2.0</li><li>August 7, 2020 &#8212; Version 1.1</li></ul></div></div></section>
<section class="panel panel-default"><header class="panel-heading"><h3 class="panel-title h3">La Base de données ouvertes sur les immeubles</h3></header>
<div class="row panel-body"><p><a href="https://www150.statcan.gc.ca/n1/pub/34-26-0001/342600012018001-fra.htm">BDOI</a> contient des empreintes.</p><p>Dates de diffusion&nbsp;:</p><ul><li>15 avril 2025 &#8212; Version&nbsp;3.0</li><li>1 er mars 2019 &#8212; Version 2.0</li></ul></div></section>
"""

PRODUCT = """
<p>It is released under the&nbsp; Open Government Licence &#8211; Canada and is a component.</p>
<p>The variables included in the <abbr title="Open Database of Healthcare Facilities">ODHF</abbr> are as follows:</p>
<ul><li>id: a unique identifier for the record;</li><li>type: the class defined by Statistics Canada;</li></ul>
<p>For more information, see the metadata.</p>
<a href="2020001/zip/odhf_v2_geojson.zip">ODHF v2 (GeoJSON)</a>
<a href="https://evil.example/x.zip">elsewhere</a>
<dl><dt>Release date:</dt><dd>September 24, 2026</dd></dl>
<p>Date modified:&#32; 2026-09-24</p>
"""


def test_landing_parsed_per_database_with_versions() -> None:
    entries = pages.parse_landing(LANDING)
    assert entries[0].title == "The Open Database of Healthcare Facilities"
    first = entries[0]
    assert first.page_url.endswith("132600012020001-eng.htm")
    assert "22,000 records" in first.description
    assert [(r.date, r.version) for r in first.releases] == [
        ("2026-09-24", "Version 2.0"),
        ("2020-08-07", "Version 1.1"),
    ]


def test_french_dates_with_the_stray_space_after_1() -> None:
    entries = pages.parse_landing(LANDING)
    assert [r.date for r in entries[1].releases] == ["2025-04-15", "2019-03-01"]
    assert pages.parse_date("24 septembre 2026") == "2026-09-24"
    assert pages.parse_date("no date here") is None


def test_product_page_fields_survive_abbr_tags_and_foreign_links_are_dropped() -> None:
    url = "https://www150.statcan.gc.ca/n1/pub/13-26-0001/132600012020001-eng.htm"
    product = pages.parse_product(PRODUCT, url)
    assert product.fields == [
        ("id", "a unique identifier for the record;".rstrip(";")),
        ("type", "the class defined by Statistics Canada"),
    ]
    assert [d.url for d in product.downloads] == [
        "https://www150.statcan.gc.ca/n1/pub/13-26-0001/2020001/zip/odhf_v2_geojson.zip"
    ]
    assert product.licence == "Open Government Licence - Canada"
    assert product.date_modified == "2026-09-24"


def test_variable_list_as_one_item_per_li_with_dashes() -> None:
    page = "<p>The variables included in the ODB are as follows:</p><ul><li>id - Unique building ID</li><li>csduid - Census subdivision unique identifier</li></ul><p>For more information</p>"
    assert pages.parse_fields(page) == [
        ("id", "Unique building ID"),
        ("csduid", "Census subdivision unique identifier"),
    ]


def test_file_format_and_province_from_names() -> None:
    assert pages.file_format("https://x/odhf_v2_geojson.zip") == "geojson"
    assert pages.file_format("https://x/ODB_v3_PE.zip") == "zip"
    assert pages.file_provinces("https://x/ODB_v3_QC_2.zip") == ["QC"]
    assert pages.file_provinces("https://x/ODA_NT_v1.zip") == ["NT"]
    assert pages.file_provinces("https://x/pmd-eng.zip") == []


def test_lambert_round_trip_and_known_point() -> None:
    # An ODG greenhouse stored in 3347 and as Latitude/Longitude (checked live).
    lon, lat = geometry.lambert_to_lonlat(7268009.287572, 853901.047269)
    assert lon == pytest.approx(-79.05217047, abs=1e-6)
    assert lat == pytest.approx(42.93512585, abs=1e-6)
    x, y = geometry.lonlat_to_lambert(-79.05217047, 42.93512585)
    assert x == pytest.approx(7268009.29, abs=0.05)
    assert y == pytest.approx(853901.05, abs=0.05)


def test_projected_bbox_contains_the_corners() -> None:
    box = geometry.projected_bbox((-75.9, 45.3, -75.5, 45.5))
    for lon, lat in ((-75.9, 45.3), (-75.5, 45.5), (-75.9, 45.5), (-75.5, 45.3)):
        x, y = geometry.lonlat_to_lambert(lon, lat)
        assert box[0] <= x <= box[2]
        assert box[1] <= y <= box[3]


def _gpkg_blob(flags: int, envelope: bytes, wkb: bytes) -> bytes:
    return b"GP" + bytes([0, flags]) + struct.pack("<i", 3347) + envelope + wkb


def test_gpkg_point_without_envelope_and_polygon_with_envelope() -> None:
    point = struct.pack("<BIdd", 1, 1, 10.0, 20.0)
    assert geometry.decode_gpkg_geometry(_gpkg_blob(0x01, b"", point)) == (10.0, 20.0, "Point")
    # ODB polygons carry a 32-byte envelope (flags 0x03); the centre is returned.
    polygon = struct.pack("<BII", 1, 3, 0)
    envelope = struct.pack("<4d", 0.0, 10.0, 100.0, 200.0)
    assert geometry.decode_gpkg_geometry(_gpkg_blob(0x03, envelope, polygon)) == (
        5.0,
        150.0,
        "Polygon",
    )
    # ODG multipolygons use envelope code 2 (48 bytes with z).
    multi = struct.pack("<BII", 1, 6, 0)
    xyz = struct.pack("<6d", 0.0, 2.0, 0.0, 4.0, 0.0, 0.0)
    assert geometry.decode_gpkg_geometry(_gpkg_blob(0x05, xyz, multi)) == (1.0, 2.0, "MultiPolygon")
    assert geometry.decode_gpkg_geometry(b"") is None
    assert geometry.decode_gpkg_geometry(_gpkg_blob(0x11, b"", point)) is None


def test_crs_kind() -> None:
    assert geometry.crs_kind(100000, "PROJCS[NAD83_Statistics_Canada_Lambert]") == "lambert"
    assert geometry.crs_kind(3347) == "lambert"
    assert geometry.crs_kind(4326) == "lonlat"
    assert geometry.crs_kind(3857) == "unknown"
