"""Read a remote ZIP's file list and single members with HTTP range requests.

StatCan's PUMF zips run to 182 MB (Census 2021 individuals), but their
codebooks and command files are tens of KB. Confirmed live 2026-09-24:
www150.statcan.gc.ca answers `Accept-Ranges: bytes` and 206 Partial
Content, so the central directory (at the end of the file) and one
member can be fetched without downloading the archive: listing the
Census zip took 12 KB.

Only stored (0) and deflated (8) members are supported, which is what
every StatCan PUMF zip sampled uses. ZIP64 archives are rejected with a
clear error rather than misread.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import httpx

from maple_data_mcp.shared.errors import UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import new_client

_EOCD = b"PK\x05\x06"
_CENTRAL = b"PK\x01\x02"
_LOCAL = b"PK\x03\x04"
_TAIL_BYTES = 256 * 1024
_client = new_client(timeout=60.0, follow_redirects=True)


@dataclass(frozen=True)
class ZipMember:
    name: str
    compressed_size: int
    size: int
    method: int
    header_offset: int


async def _range(url: str, start: int, end: int) -> bytes:
    try:
        response = await _client.get(url, headers={"Range": f"bytes={start}-{end}"})
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(f"{url} returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"{url} could not be reached.") from exc
    if response.status_code != 206:
        raise UpstreamError(f"{url} does not support range requests (HTTP {response.status_code}).")
    return response.content


async def _size(url: str) -> int:
    try:
        response = await _client.head(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"{url} could not be reached.") from exc
    length = response.headers.get("content-length")
    if not length:
        raise UpstreamError(f"{url} reports no size, so it cannot be read by range.")
    return int(length)


def _decode_name(raw: bytes, flags: int) -> str:
    # Bit 11 marks UTF-8 names; StatCan's zips use CP437 (French folders
    # such as "Français/" otherwise decode wrongly).
    return raw.decode("utf-8" if flags & 0x800 else "cp437", errors="replace")


async def list_members(url: str) -> tuple[list[ZipMember], int]:
    """The archive's members and its total size in bytes."""
    total = await _size(url)
    tail_start = max(0, total - _TAIL_BYTES)
    tail = await _range(url, tail_start, total - 1)
    eocd = tail.rfind(_EOCD)
    if eocd < 0:
        raise UpstreamError(f"{url} is not a ZIP file (no end-of-directory record).")
    _, _, _, _, count, cd_size, cd_offset, _ = struct.unpack("<4sHHHHIIH", tail[eocd : eocd + 22])
    if cd_offset == 0xFFFFFFFF or count == 0xFFFF:
        raise UpstreamError(f"{url} is a ZIP64 archive, which this reader does not support.")
    if cd_offset >= tail_start:
        directory = tail[cd_offset - tail_start : cd_offset - tail_start + cd_size]
    else:
        directory = await _range(url, cd_offset, cd_offset + cd_size - 1)

    members: list[ZipMember] = []
    pos = 0
    for _ in range(count):
        if directory[pos : pos + 4] != _CENTRAL:
            raise UpstreamError(f"{url}: malformed ZIP central directory.")
        (flags, method, csize, usize, name_len, extra_len, comment_len, offset) = struct.unpack(
            # versions (4), flags, method, time/date/crc (8), sizes, name/extra/
            # comment lengths, disk/attributes (8), local header offset.
            "<4xHH8xIIHHH8xI",
            directory[pos + 4 : pos + 46],
        )
        name = _decode_name(directory[pos + 46 : pos + 46 + name_len], flags)
        members.append(ZipMember(name, csize, usize, method, offset))
        pos += 46 + name_len + extra_len + comment_len
    return members, total


async def read_member(url: str, member: ZipMember, *, max_bytes: int = 20_000_000) -> bytes:
    if member.compressed_size > max_bytes:
        raise UpstreamError(
            f"{member.name} is {member.compressed_size:,} bytes compressed, over this reader's "
            f"{max_bytes:,}-byte limit."
        )
    if member.method not in (0, 8):
        raise UpstreamError(f"{member.name} uses ZIP compression method {member.method}.")
    header = await _range(url, member.header_offset, member.header_offset + 29)
    if header[:4] != _LOCAL:
        raise UpstreamError(f"{url}: malformed ZIP local header for {member.name}.")
    name_len, extra_len = struct.unpack("<HH", header[26:30])
    start = member.header_offset + 30 + name_len + extra_len
    data = (
        await _range(url, start, start + member.compressed_size - 1)
        if member.compressed_size
        else b""
    )
    return data if member.method == 0 else zlib.decompress(data, -15)
