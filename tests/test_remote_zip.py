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


def _zip64_archive(*, claimed_usize: int) -> bytes:
    """A small real archive whose directory is rewritten the ZIP64 way.

    The first member gets 0xFFFFFFFF in the size and offset slots (values
    in the 0x0001 extra field, as in StatCan's 3.87 GB Delta File, whose
    CSV inflates to 29 GB), and the end record is replaced by a ZIP64
    record plus locator with 0xFFFF/0xFFFFFFFF placeholders.
    """
    plain = _archive()
    archive = zipfile.ZipFile(io.BytesIO(plain))
    infos = archive.infolist()
    cd_start = archive.start_dir
    body = bytearray(plain[:cd_start])
    directory = bytearray()
    for index, info in enumerate(infos):
        name = info.filename.encode("cp437" if info.flag_bits & 0x800 == 0 else "utf-8")
        if index == 0:
            extra = struct.pack(
                "<HHQQQ", 1, 24, claimed_usize, info.compress_size, info.header_offset
            )
            usize = csize = offset = 0xFFFFFFFF
        else:
            extra, usize, csize, offset = (
                b"",
                info.file_size,
                info.compress_size,
                info.header_offset,
            )
        directory += struct.pack(
            "<4sHHHHHHIIIHHHHHII",
            b"PK\x01\x02",
            45,
            45,
            info.flag_bits,
            info.compress_type,
            0,
            0,
            info.CRC,
            csize,
            usize,
            len(name),
            len(extra),
            0,
            0,
            0,
            0,
            offset,
        )
        directory += name + extra
    record_offset = len(body) + len(directory)
    end64 = struct.pack(
        "<4sQHHIIQQQQ",
        b"PK\x06\x06",
        44,
        45,
        45,
        0,
        0,
        len(infos),
        len(infos),
        len(directory),
        cd_start,
    )
    locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, record_offset, 1)
    eocd = struct.pack("<4sHHHHIIH", b"PK\x05\x06", 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    return bytes(body + directory + end64 + locator + eocd)


async def test_zip64_directory_sizes_come_from_the_extra_field(httpx_mock):
    body = _zip64_archive(claimed_usize=29_000_000_000)
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    members, total = await remote_zip.list_members(URL)
    assert total == len(body)
    first, second = members
    assert first.name == "data.csv"
    assert first.size == 29_000_000_000
    assert first.header_offset == 0
    assert second.name == "Français/codebook.txt"
    assert second.size == len("étiquette".encode())
    # The real compressed member is still readable through the ZIP64 offset.
    assert (await remote_zip.read_member(URL, first)).startswith(b"a,b\n1,2")


async def test_zip64_record_beyond_the_tail_is_read_by_range(httpx_mock, monkeypatch):
    monkeypatch.setattr(remote_zip, "_TAIL_BYTES", 120)
    body = _zip64_archive(claimed_usize=5_000_000_000)
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    members, _ = await remote_zip.list_members(URL)
    assert members[0].size == 5_000_000_000


async def test_zip64_without_locator_is_an_error(httpx_mock):
    body = bytearray(_zip64_archive(claimed_usize=5_000_000_000))
    body[-42:-38] = b"XXXX"
    httpx_mock.add_callback(_serve(bytes(body)), url=URL, is_reusable=True)
    with pytest.raises(UpstreamError, match="locator"):
        await remote_zip.list_members(URL)
