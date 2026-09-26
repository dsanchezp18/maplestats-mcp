"""shared/remote_zip.py against a real ZIP served through range requests."""

from __future__ import annotations

import io
import re
import struct
import zipfile

import httpx
import pytest

from maplestats_mcp.shared import remote_zip
from maplestats_mcp.shared.errors import UpstreamError

URL = "https://www150.statcan.gc.ca/n1/pub/x/file.zip"


def _archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("data.csv", "a,b\n" + "1,2\n" * 5000, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("Français/codebook.txt", "étiquette", compress_type=zipfile.ZIP_STORED)
    return buffer.getvalue()


def _serve(body: bytes):
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": str(len(body))})
        start, end = map(int, re.findall(r"\d+", request.headers["range"]))
        return httpx.Response(206, content=body[start : end + 1])

    return respond


async def test_lists_and_reads_members_by_range(httpx_mock):
    body = _archive()
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    members, total = await remote_zip.list_members(URL)
    assert total == len(body)
    assert [m.name for m in members] == ["data.csv", "Français/codebook.txt"]
    by_name = {m.name: m for m in members}
    assert (await remote_zip.read_member(URL, by_name["data.csv"])).startswith(b"a,b\n1,2")
    assert (
        await remote_zip.read_member(URL, by_name["Français/codebook.txt"])
    ).decode() == "étiquette"


async def test_server_without_range_support_is_an_error(httpx_mock):
    httpx_mock.add_response(method="HEAD", url=URL, headers={"content-length": "100"})
    httpx_mock.add_response(method="GET", url=URL, status_code=200, content=b"x" * 100)
    with pytest.raises(UpstreamError, match="range"):
        await remote_zip.list_members(URL)


def _member(archive: bytes, name: str) -> remote_zip.ZipMember:
    info = zipfile.ZipFile(io.BytesIO(archive)).getinfo(name)
    return remote_zip.ZipMember(
        name, info.compress_size, info.file_size, info.compress_type, info.header_offset
    )


async def test_short_range_response_is_an_error(httpx_mock):
    body = _archive()

    def short(request: httpx.Request) -> httpx.Response:
        start, end = map(int, re.findall(r"\d+", request.headers["range"]))
        return httpx.Response(206, content=body[start:end])  # one byte short

    httpx_mock.add_callback(short, url=URL)
    with pytest.raises(UpstreamError, match="range"):
        await remote_zip.read_member(URL, _member(body, "data.csv"))


async def test_member_decompressing_past_the_limit_is_an_error(httpx_mock):
    # ~1 MB of zeros deflates to about 1 KB: under the compressed cap, far
    # over the decompressed one.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("bomb.txt", b"\0" * 1_000_000, compress_type=zipfile.ZIP_DEFLATED)
    body = buffer.getvalue()
    member = _member(body, "bomb.txt")
    assert member.compressed_size < 10_000
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    with pytest.raises(UpstreamError, match="limit"):
        await remote_zip.read_member(URL, member, max_bytes=10_000)
    # Exactly at the limit is still allowed.
    data = await remote_zip.read_member(URL, member, max_bytes=1_000_000)
    assert len(data) == 1_000_000


async def test_corrupt_deflate_data_is_an_error(httpx_mock):
    body = bytearray(_archive())
    member = _member(bytes(body), "data.csv")
    name_len, extra_len = struct.unpack(
        "<HH", body[member.header_offset + 26 : member.header_offset + 30]
    )
    start = member.header_offset + 30 + name_len + extra_len
    # 0xFF opens a deflate block with the reserved block type 3.
    body[start : start + member.compressed_size] = b"\xff" * member.compressed_size
    httpx_mock.add_callback(_serve(bytes(body)), url=URL, is_reusable=True)
    with pytest.raises(UpstreamError, match="deflate"):
        await remote_zip.read_member(URL, member)
