"""Client behaviour with the upstream mocked at the transport level."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from maplestats_mcp.modules.statcan.lode import client, constants, files
from maplestats_mcp.modules.statcan.lode.__tests__.test_pages_geometry import LANDING, PRODUCT
from maplestats_mcp.modules.statcan.lode.__tests__.test_reader import make_geojson, make_gpkg
from maplestats_mcp.modules.statcan.lode.schemas import LodeFile
from maplestats_mcp.shared import cache, remote_zip
from maplestats_mcp.shared.errors import InvalidInput, NotFound

ZIP_URL = "https://www150.statcan.gc.ca/n1/pub/46-26-0002/2022001/202606.zip"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache._caches.clear()
    monkeypatch.setenv("MAPLE_LODE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("MAPLE_LODE_MAX_DOWNLOAD_MB", raising=False)


def _file(name: str, provinces: list[str] | None = None, label: str = "") -> LodeFile:
    return LodeFile(
        label=label or name,
        url=f"https://www150.statcan.gc.ca/n1/pub/x/{name}",
        filename=name,
        format="zip",
        provinces=provinces or [],
        queryable=True,
    )


def test_choose_files_requires_a_province_for_per_province_databases() -> None:
    db = constants.BY_KEY["odb"]
    listing = [
        _file("ODB_v3_PE.zip", ["PE"]),
        _file("ODB_v3_ON_1.zip", ["ON"]),
        _file("ODB_v3_ON_2.zip", ["ON"]),
    ]
    with pytest.raises(InvalidInput, match="one file per province"):
        client.choose_files(db, listing, None, None)
    chosen, by_province = client.choose_files(db, listing, None, "Ontario")
    assert [f.filename for f in chosen] == ["ODB_v3_ON_1.zip", "ODB_v3_ON_2.zip"]
    assert by_province
    with pytest.raises(InvalidInput, match="no file for NS"):
        client.choose_files(db, listing, None, "NS")


def test_choose_files_default_prefers_geojson_and_skips_parquet() -> None:
    db = constants.BY_KEY["odsrf"]
    listing = [
        _file("odsrf_v2_gpkg.zip"),
        _file("odsrf_v2_parquet.zip").model_copy(update={"queryable": False}),
    ]
    chosen, _ = client.choose_files(db, listing, None, None)
    assert chosen[0].filename == "odsrf_v2_gpkg.zip"
    with pytest.raises(InvalidInput, match="No file matches"):
        client.choose_files(db, listing, "parquet", None)


def test_pick_data_member_prefers_geojson_skips_layouts_and_flags_ambiguity() -> None:
    def member(name: str, size: int = 10) -> remote_zip.ZipMember:
        return remote_zip.ZipMember(name, size, size, 8, 0)

    members = [
        member("record_layout.csv"),
        member("a.csv", 5),
        member("d.geojson", 3),
        member("x/"),
    ]
    picked = client.pick_data_member(members)
    assert picked is not None
    assert picked.name == "d.geojson"
    csvs = [member("acs_a.csv", 5), member("acs_b.csv", 7), member("data_sources.csv")]
    with pytest.raises(InvalidInput, match="pass member"):
        client.pick_data_member(csvs, strict=True)
    chosen = client.pick_data_member(csvs, "acs_a", strict=True)
    assert chosen is not None
    assert chosen.name == "acs_a.csv"


def test_parse_dictionary_handles_both_header_styles() -> None:
    odef = "field_name,data_type,description\nunique_id,string,Unique school identifier\n"
    remote = (
        "Field name,Description,Field type\nPruid,Uniquely identifies a province,Geographic code\n"
    )
    first = client.parse_dictionary(odef)[0]
    assert (first.name, first.type, first.description) == (
        "unique_id",
        "string",
        "Unique school identifier",
    )
    second = client.parse_dictionary(remote)[0]
    assert (second.type, second.description) == (
        "Geographic code",
        "Uniquely identifies a province",
    )


async def test_list_databases_reads_landing_and_product_pages(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=constants.LANDING_URL["en"], text=LANDING)
    for db in constants.DATABASES:
        if db.key != "odhf":
            httpx_mock.add_response(
                url=db.page_en, text="<p>Release date: June 26, 2026</p>", is_optional=True
            )
    result = await client.list_databases("en")
    odhf = next(d for d in result.databases if d.key == "odhf")
    assert odhf.latest_release == "2026-09-24"
    assert [r.version for r in odhf.releases] == ["Version 2.0", "Version 1.1"]
    assert odhf.licence == constants.OGL
    nar = next(d for d in result.databases if d.key == "nar")
    assert nar.latest_release == "2026-06-26"
    assert not nar.queryable
    assert len(result.databases) == len(constants.DATABASES)


async def test_list_files_with_sizes_from_head(httpx_mock: HTTPXMock) -> None:
    page = constants.BY_KEY["odhf"].page_en
    httpx_mock.add_response(url=page, text=PRODUCT)
    httpx_mock.add_response(
        method="HEAD",
        url="https://www150.statcan.gc.ca/n1/pub/13-26-0001/2020001/zip/odhf_v2_geojson.zip",
        headers={"content-length": "2292416", "last-modified": "Thu, 24 Sep 2026 12:30:41 GMT"},
    )
    result = await client.list_files("odhf")
    assert result.release_date == "2026-09-24"
    assert result.files[0].size_bytes == 2292416
    assert result.files[0].format == "geojson"
    assert result.files[0].queryable
    assert result.max_download_bytes == 300_000_000


async def test_list_files_no_downloads_is_not_found(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=constants.BY_KEY["odhf"].page_en, text="<p>nothing</p>")
    with pytest.raises(NotFound):
        await client.list_files("odhf", sizes=False)


async def test_unknown_database_is_input_error() -> None:
    with pytest.raises(InvalidInput, match="Unknown database"):
        await client.list_files("nope")


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _serve_ranges(httpx_mock: HTTPXMock, url: str, blob: bytes) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": str(len(blob))})
        match = re.match(r"bytes=(\d+)-(\d+)", request.headers["range"])
        assert match
        start, end = int(match.group(1)), int(match.group(2))
        part = blob[start : end + 1]
        headers = {"content-range": f"bytes {start}-{start + len(part) - 1}/{len(blob)}"}
        return httpx.Response(206, content=part, headers=headers)

    httpx_mock.add_callback(respond, url=url, is_reusable=True)


async def test_preview_member_reads_a_prefix_by_range_and_matches_rows(
    httpx_mock: HTTPXMock,
) -> None:
    header = "LOC_GUID,CSD_CODE,BG_LATITUDE\n"
    body = "".join(f"g{i},6204018,{60 + i / 1000}\n" for i in range(3000))
    blob = _zip_bytes(
        {"guide.pdf": b"x" * 50, "Locations/Location_62.csv": (header + body).encode()}
    )
    _serve_ranges(httpx_mock, ZIP_URL, blob)
    listing = await client.list_zip(ZIP_URL)
    assert {e.name for e in listing.entries} == {"guide.pdf", "Locations/Location_62.csv"}
    preview = await client.preview_member(ZIP_URL, "location_62.csv", rows=2)
    assert preview.columns == ["LOC_GUID", "CSD_CODE", "BG_LATITUDE"]
    assert [r["LOC_GUID"] for r in preview.rows] == ["g0", "g1"]
    assert preview.scan_complete
    hit = await client.preview_member(
        ZIP_URL, "Locations/Location_62.csv", match={"loc_guid": "G2999"}
    )
    assert hit.rows_returned == 1
    assert hit.rows[0]["BG_LATITUDE"] == "62.999"
    with pytest.raises(InvalidInput, match="No column"):
        await client.preview_member(ZIP_URL, "Locations/Location_62.csv", match={"nope": "1"})
    with pytest.raises(NotFound):
        await client.preview_member(ZIP_URL, "missing.csv")
    with pytest.raises(InvalidInput, match="not a text table"):
        await client.preview_member(ZIP_URL, "guide.pdf")


async def test_preview_stops_at_the_scan_cap_and_drops_the_cut_line(httpx_mock: HTTPXMock) -> None:
    body = "".join(f"{i:07d},{'x' * 40}\n" for i in range(200_000))
    blob = _zip_bytes({"big.csv": ("id,pad\n" + body).encode()})
    # Stored compressed size is small, so shrink the cap below it.
    _serve_ranges(httpx_mock, ZIP_URL, blob)
    members, _, _ = await client._members(ZIP_URL)
    chunks, read, complete = await files.stream_member(ZIP_URL, members[0], 20_000)
    assert not complete
    assert read == 20_000
    header, rows = files.read_rows(chunks, complete, {}, 10**9)
    assert header == ["id", "pad"]
    assert rows[-1]["pad"] == "x" * 40  # a half-read last line is not returned


async def test_query_end_to_end_with_cached_member(
    httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpkg = make_gpkg(tmp_path / "places.gpkg")
    page = constants.BY_KEY["odhf"].page_en
    urls = "".join(
        f'<a href="2020001/zip/odhf_v2_{n}.zip">ODHF v2 ({n})</a>' for n in ("gpkg", "parquet")
    )
    httpx_mock.add_response(url=page, text=urls)
    gpkg_url = "https://www150.statcan.gc.ca/n1/pub/13-26-0001/2020001/zip/odhf_v2_gpkg.zip"
    blob = _zip_bytes({"odhf_v2.gpkg": gpkg.read_bytes(), "meta.pdf": b"%PDF"})
    _serve_ranges(httpx_mock, gpkg_url, blob)

    async def fake_member(url: str, member: str) -> tuple[Path, bool]:
        assert (url, member) == (gpkg_url, "odhf_v2.gpkg")
        return gpkg, True

    monkeypatch.setattr(files, "local_member", fake_member)
    result = await client.query("odhf", province="QC", type="hospital", limit=5)
    assert result.total_matched == 1
    assert result.records[0]["name"] == "Hôpital Santa Cabrini"
    assert result.downloaded
    assert result.format == "gpkg"
    assert result.layer == "places"
    assert result.filters["province"] == "QC"


async def test_query_refuses_a_download_over_the_cap(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAPLE_LODE_MAX_DOWNLOAD_MB", "0")
    httpx_mock.add_response(
        url=constants.BY_KEY["odef"].page_en, text='<a href="2022001/ODEF_v3.0.zip">ODEF</a>'
    )
    url = "https://www150.statcan.gc.ca/n1/pub/37-26-0001/2022001/ODEF_v3.0.zip"
    _serve_ranges(httpx_mock, url, _zip_bytes({"odef.csv": b"a,b\n" + b"1,2\n" * 5000}))
    with pytest.raises(InvalidInput, match="per-call cap"):
        await client.query("odef")


async def test_query_on_the_nar_points_to_range_tools() -> None:
    with pytest.raises(InvalidInput, match="statcan_lode_preview_member"):
        await client.query("nar")


async def test_query_rejects_bad_limit_and_bbox() -> None:
    with pytest.raises(InvalidInput, match="limit"):
        await client.query("odhf", limit=501)
    with pytest.raises(InvalidInput, match="four numbers"):
        await client.query("odhf", bbox=[1, 2, 3])


async def test_local_member_downloads_once_and_reuses(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    geojson = make_geojson(tmp_path / "p.geojson")
    url = "https://www150.statcan.gc.ca/n1/pub/13-26-0001/2020001/zip/odhf_v2_geojson.zip"
    httpx_mock.add_response(url=url, content=_zip_bytes({"odhf_v2.geojson": geojson.read_bytes()}))
    path, fresh = await files.local_member(url, "odhf_v2.geojson")
    assert fresh
    assert path.read_bytes() == geojson.read_bytes()
    again, fresh_again = await files.local_member(url, "odhf_v2.geojson")
    assert again == path
    assert not fresh_again


def test_check_url_only_allows_statcan_zips() -> None:
    assert files.check_url(ZIP_URL) == ZIP_URL
    for bad in (
        "http://www150.statcan.gc.ca/a.zip",
        "https://evil.example/a.zip",
        ZIP_URL[:-4] + ".csv",
    ):
        with pytest.raises(InvalidInput):
            files.check_url(bad)
