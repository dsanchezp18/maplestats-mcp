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
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from maplestats_mcp.shared.errors import UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import is_retryable, new_client

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


# Some hosts answer a share of otherwise valid requests with a transient
# 502 or a dropped connection (Toronto's open-data download host failed
# about half of its range requests on 2026-10-01 and served the same ones
# a moment later), so each request is retried on the shared retryable set.
_RETRY = retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
    reraise=True,
)


@_RETRY
async def _get_range(url: str, start: int, end: int) -> httpx.Response:
    response = await _client.get(url, headers={"Range": f"bytes={start}-{end}"})
    response.raise_for_status()
    return response


async def _range(url: str, start: int, end: int) -> bytes:
    try:
        response = await _get_range(url, start, end)
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(f"{url} returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"{url} could not be reached.") from exc
    if response.status_code != 206:
        raise UpstreamError(f"{url} does not support range requests (HTTP {response.status_code}).")
    # A 206 can still be short (a truncated transfer, or a server that
    # clamps the range); slicing ZIP structures out of a short body would
    # misread them silently, so the length is checked, not assumed.
    expected = end - start + 1
    if len(response.content) != expected:
        raise UpstreamError(
            f"{url} returned {len(response.content):,} bytes for a {expected:,}-byte range."
        )
    return response.content


async def _size(url: str) -> int:
    # HEAD first; some hosts answer it with a 502 far more often than a
    # ranged GET (Toronto's open-data host, 2026-10-01), so any HEAD
    # failure falls back to reading the total from a one-byte range.
    try:
        response = await _client.head(url)
        response.raise_for_status()
        length = response.headers.get("content-length")
        if length:
            return int(length)
    except httpx.HTTPError:
        pass
    try:
        ranged = await _get_range(url, 0, 0)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"{url} could not be reached.") from exc
    total = ranged.headers.get("content-range", "").rpartition("/")[2]
    if not total.isdigit():
        raise UpstreamError(f"{url} reports no size, so it cannot be read by range.")
    return int(total)


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
    """One member's contents, at most `max_bytes` both compressed and
    decompressed. The callers read codebooks and layout files (tens of KB
    to a few MB), so 20 MB is generous for them while still stopping a
    deflate bomb, whose tiny compressed size the first check alone passes.
    """
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
    return data if member.method == 0 else _inflate(data, member.name, max_bytes)


def _inflate(data: bytes, name: str, max_bytes: int) -> bytes:
    # The central directory's `size` is whatever the archive claims, so the
    # bound is enforced on the actual output: ask for one byte past the
    # limit, and anything left over means the member is too large.
    inflater = zlib.decompressobj(-15)
    try:
        out = inflater.decompress(data, max_bytes + 1)
        if len(out) > max_bytes or inflater.unconsumed_tail:
            raise UpstreamError(
                f"{name} decompresses to over this reader's {max_bytes:,}-byte limit."
            )
        out += inflater.flush()
    except zlib.error as exc:
        raise UpstreamError(f"{name} is not valid deflate data: {exc}.") from exc
    if len(out) > max_bytes:
        raise UpstreamError(f"{name} decompresses to over this reader's {max_bytes:,}-byte limit.")
    if not inflater.eof:
        raise UpstreamError(f"{name}: deflate stream is truncated.")
    return out
