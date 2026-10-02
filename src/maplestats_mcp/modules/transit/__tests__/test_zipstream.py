"""Range-streaming a large ZIP member in small chunks."""

from __future__ import annotations

import io
import re
import zipfile

import httpx
import pytest

from maplestats_mcp.modules.transit import constants, zipstream
from maplestats_mcp.shared.errors import UpstreamError
from maplestats_mcp.shared.remote_zip import ZipMember

URL = "https://example.test/feed.zip"


def _archive(text: str, method: int = zipfile.ZIP_DEFLATED) -> tuple[bytes, ZipMember]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("stop_times.txt", text, compress_type=method)
    info = zipfile.ZipFile(io.BytesIO(buffer.getvalue())).getinfo("stop_times.txt")
    member = ZipMember(
        "stop_times.txt", info.compress_size, info.file_size, info.compress_type, info.header_offset
    )
    return buffer.getvalue(), member


def _serve(body: bytes):
    def respond(request: httpx.Request) -> httpx.Response:
        start, end = map(int, re.findall(r"\d+", request.headers["range"]))
        return httpx.Response(206, content=body[start : end + 1])

    return respond


async def _lines(member: ZipMember) -> list[bytes]:
    return [line async for batch in zipstream.stream_member_lines(URL, member) for line in batch]


@pytest.mark.parametrize("method", [zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED])
async def test_streams_complete_lines_across_chunk_boundaries(httpx_mock, monkeypatch, method):
    rows = [f"T{i},08:00:00,08:00:00,{i},1" for i in range(2000)]
    text = "trip_id,arrival_time,departure_time,stop_id,stop_sequence\r\n" + "\r\n".join(rows)
    body, member = _archive(text, method)
    monkeypatch.setattr(constants, "SCAN_CHUNK_BYTES", 1024)
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    lines = await _lines(member)
    assert lines[0].startswith(b"trip_id,")
    assert lines[1:] == [r.encode() for r in rows]
    # Several ranges were needed, not one download of the archive.
    assert len(httpx_mock.get_requests()) > 3


async def test_member_over_the_scan_limit_is_refused(monkeypatch):
    monkeypatch.setattr(constants, "SCAN_MAX_COMPRESSED_BYTES", 10)
    _, member = _archive("a,b\n" * 1000)
    with pytest.raises(UpstreamError, match="scan limit"):
        await _lines(member)


async def test_inflating_past_the_limit_is_refused(httpx_mock, monkeypatch):
    body, member = _archive("a,b\n" * 5000)
    monkeypatch.setattr(constants, "SCAN_MAX_UNCOMPRESSED_BYTES", 1000)
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    with pytest.raises(UpstreamError, match="scan limit"):
        await _lines(member)


async def test_server_ignoring_ranges_is_an_error(httpx_mock):
    body, member = _archive("a,b\n" * 10)
    httpx_mock.add_response(url=URL, status_code=200, content=body)
    with pytest.raises(UpstreamError, match="byte range"):
        await _lines(member)


async def test_replaced_archive_is_reported(httpx_mock):
    body, member = _archive("a,b\n" * 10)
    garbage = b"x" * len(body)
    httpx_mock.add_callback(_serve(garbage), url=URL, is_reusable=True)
    with pytest.raises(UpstreamError, match="changed"):
        await _lines(member)


@pytest.mark.parametrize("method", [zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED])
async def test_streams_from_a_zip_held_in_memory_without_requests(httpx_mock, monkeypatch, method):
    rows = [f"T{i},08:00:00,08:00:00,{i},1" for i in range(2000)]
    text = "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n" + "\n".join(rows)
    body, _ = _archive(text, method)
    [member] = zipstream.members_of(body, URL)
    monkeypatch.setattr(constants, "SCAN_CHUNK_BYTES", 1024)
    lines = [
        line
        async for batch in zipstream.stream_member_lines(URL, member, blob=body)
        for line in batch
    ]
    assert lines[1:] == [r.encode() for r in rows]
    assert httpx_mock.get_requests() == []


def test_blob_member_read_is_bounded():
    body, _ = _archive("a,b\n" + "1,2\n" * 1000)
    [member] = zipstream.members_of(body, URL)
    assert zipstream.read_blob_member(body, member, max_bytes=10_000).startswith(b"a,b")
    with pytest.raises(UpstreamError, match="limit"):
        zipstream.read_blob_member(body, member, max_bytes=100)
    with pytest.raises(UpstreamError, match="not a valid ZIP"):
        zipstream.members_of(b"not a zip", URL)
