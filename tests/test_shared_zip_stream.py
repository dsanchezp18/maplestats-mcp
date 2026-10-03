"""Streaming a deflated ZIP member by range and re-entering it at access points.

The member text imitates the 20261001 Delta CSV (LF line endings, no BOM,
long runs of near-identical rows, fiscal-year periods): repetitive text is
what makes deflate copy whole lines from the previous 32 KiB, which is why
a resume point needs the real window and not a placeholder.
"""

from __future__ import annotations

import asyncio
import io
import random
import re
import struct
import time
import zipfile
import zlib
from itertools import pairwise

import httpx
import pytest

from maplestats_mcp.shared import remote_zip
from maplestats_mcp.shared.remote_zip import ZipMember
from maplestats_mcp.shared.zip_stream import (
    AccessPoint,
    MemberStream,
    ScanLimitExceeded,
    _BitShifter,
    block_candidates,
)

URL = "https://www150.statcan.gc.ca/n1/delta/20261001.zip"
HEADER = (
    "productId,coordinate,vectorId,refPer,refPer2,symbolCode,statusCode,securityLevelCode,"
    "value,releaseTime,scalarFactorCode,decimals,frequencyCode"
)


def _delta_text(rows: int) -> str:
    rng = random.Random(42)
    lines = [HEADER]
    pid = 35100027
    for n in range(rows):
        if n and n % 9000 == 0:
            pid += 1
        year = 2005 + n % 15
        value = "" if n % 11 == 3 else str(rng.randint(0, 900))
        status = 1 if not value else 0
        lines.append(
            f"{pid},{n % 13}.{n % 40}.{n % 5}.{n % 4}.{n % 6}.{n % 7}.0.0.0.0,{55300000 + n},"
            f"{year},{year + 1},0,{status},0,{value},2013-06-13T08:30,0,0,12"
        )
    return "\n".join(lines) + "\n"


def _member_zip(text: str, method: int = zipfile.ZIP_DEFLATED) -> tuple[bytes, ZipMember]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("20261001.csv", text, compress_type=method)
    info = zipfile.ZipFile(io.BytesIO(buffer.getvalue())).getinfo("20261001.csv")
    member = ZipMember(
        "20261001.csv", info.compress_size, info.file_size, info.compress_type, info.header_offset
    )
    return buffer.getvalue(), member


def _serve(body: bytes, starts: list[tuple[float, str]] | None = None):
    def respond(request: httpx.Request) -> httpx.Response:
        if starts is not None:
            starts.append((time.monotonic(), request.headers["range"]))
        start, end = map(int, re.findall(r"\d+", request.headers["range"]))
        return httpx.Response(206, content=body[start : end + 1])

    return respond


async def _read_all(stream: MemberStream) -> bytes:
    return b"\n".join([block async for block in stream.blocks()])


def test_bit_shifter_realigns_a_stream_across_ranges():
    data = bytes(random.Random(1).randrange(256) for _ in range(500))
    for shift in range(8):
        shifter = _BitShifter(shift)
        out = shifter.feed(data[:7]) + shifter.feed(data[7:300]) + shifter.feed(data[300:])
        out += shifter.flush()
        expected = (int.from_bytes(data, "little") >> shift).to_bytes(len(data), "little")
        assert out == expected


def test_block_candidates_include_the_true_block_starts():
    text = _delta_text(30000).encode()
    raw = zlib.compressobj(6, zlib.DEFLATED, -15)
    stream = raw.compress(text) + raw.flush()
    found = list(block_candidates(stream, 4096))
    # The stream itself begins with a dynamic block header.
    assert found[0] == 0


async def test_points_are_recorded_and_resume_byte_exact(httpx_mock):
    text = _delta_text(60000)
    body, member = _member_zip(text)
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    stream = MemberStream(
        URL,
        member,
        chunk_bytes=48 * 1024,
        first_chunk_bytes=48 * 1024,
        max_scan_bytes=10**9,
        max_inflated_bytes=10**9,
        point_spacing=40 * 1024,
    )
    assert (await _read_all(stream)).decode() == text.rstrip("\n")
    assert len(stream.points) >= 3
    # Real block starts fall anywhere in a byte; re-alignment is exercised.
    assert any(point.bit_offset % 8 for point in stream.points)
    encoded = text.encode()
    for point in stream.points:
        assert len(point.window) == 32 * 1024
        assert encoded[point.out_offset - len(point.window) : point.out_offset] == point.window
    for point in (stream.points[0], stream.points[len(stream.points) // 2], stream.points[-1]):
        resumed = MemberStream(
            URL,
            member,
            chunk_bytes=48 * 1024,
            max_scan_bytes=10**9,
            max_inflated_bytes=10**9,
            start=point,
            point_spacing=40 * 1024,
        )
        tail = await _read_all(resumed)
        # The partial line at the point is dropped; the rest is identical.
        first_line_start = encoded.index(b"\n", point.out_offset - 1) + 1
        assert tail == encoded[first_line_start:].rstrip(b"\n")
        assert resumed.offset == member.compressed_size
        assert all(p.bit_offset > point.bit_offset for p in resumed.points)


async def test_a_wrong_window_cannot_pass_as_a_point(httpx_mock):
    text = _delta_text(40000)
    body, member = _member_zip(text)
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    stream = MemberStream(
        URL,
        member,
        chunk_bytes=64 * 1024,
        first_chunk_bytes=64 * 1024,
        max_scan_bytes=10**9,
        max_inflated_bytes=10**9,
        point_spacing=60 * 1024,
    )
    await _read_all(stream)
    point = stream.points[0]
    # Inflating from the point with a blank window yields placeholder bytes
    # all through: lines, newlines included, are copied from the window.
    name_len, extra_len = struct.unpack("<HH", body[26:30])
    data = body[30 + name_len + extra_len :][: member.compressed_size]
    aligned = _BitShifter(point.bit_offset % 8).feed(data[point.bit_offset // 8 :])
    out = zlib.decompressobj(-15, zdict=b"\0" * 32768).decompress(aligned)
    truth = text.encode()[point.out_offset :]
    assert out.count(0) > len(out) // 4
    assert all(a == b for a, b in zip(out, truth, strict=False) if a)
    real = zlib.decompressobj(-15, zdict=point.window).decompress(aligned)
    assert truth.startswith(real)
    assert len(real) > len(truth) - 1024


async def test_stored_members_have_no_points_and_cannot_be_resumed(httpx_mock):
    text = _delta_text(5000)
    body, member = _member_zip(text, zipfile.ZIP_STORED)
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    stream = MemberStream(
        URL,
        member,
        chunk_bytes=4096,
        max_scan_bytes=10**9,
        max_inflated_bytes=10**9,
        point_spacing=4096,
    )
    assert (await _read_all(stream)).decode() == text.rstrip("\n")
    assert stream.points == []
    with pytest.raises(ValueError, match="deflated"):
        MemberStream(
            URL,
            member,
            chunk_bytes=4096,
            max_scan_bytes=1,
            max_inflated_bytes=1,
            start=AccessPoint(8, 1, b"x"),
        )


async def test_prefetch_keeps_order_and_spaces_request_starts(httpx_mock, monkeypatch):
    text = _delta_text(20000)
    body, member = _member_zip(text)
    starts: list[tuple[float, str]] = []
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    fetch_range = remote_zip.fetch_range

    async def timed(url: str, start: int, end: int) -> bytes:
        starts.append((time.monotonic(), f"bytes={start}-{end}"))
        return await fetch_range(url, start, end)

    monkeypatch.setattr(remote_zip, "fetch_range", timed)
    stream = MemberStream(
        URL,
        member,
        chunk_bytes=40 * 1024,
        first_chunk_bytes=40 * 1024,
        max_scan_bytes=10**9,
        max_inflated_bytes=10**9,
        prefetch=3,
        min_request_interval=0.1,
    )
    assert (await _read_all(stream)).decode() == text.rstrip("\n")
    gaps = [later[0] - earlier[0] for earlier, later in pairwise(starts)]
    # Windows clocks tick every 15.6 ms.
    assert min(gaps) >= 0.08
    ranges = [tuple(map(int, re.findall(r"\d+", r))) for _, r in starts[1:]]
    assert all(b[0] == a[1] + 1 for a, b in pairwise(ranges))


async def test_breaking_early_cancels_the_ranges_in_flight(httpx_mock):
    text = _delta_text(20000)
    body, member = _member_zip(text)
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    stream = MemberStream(
        URL,
        member,
        chunk_bytes=8192,
        first_chunk_bytes=8192,
        max_scan_bytes=10**9,
        max_inflated_bytes=10**9,
        prefetch=3,
    )
    blocks = stream.blocks()
    first = await anext(blocks)
    await blocks.aclose()
    assert first.startswith(HEADER.encode())
    assert stream.scanned < member.compressed_size
    # No task is left running after the generator closes.
    await asyncio.sleep(0)
    assert not [t for t in asyncio.all_tasks() if "_fetch" in repr(t.get_coro())]


async def test_time_ceiling_raises_with_bytes_scanned(httpx_mock):
    text = _delta_text(20000)
    body, member = _member_zip(text)
    httpx_mock.add_callback(_serve(body), url=URL, is_reusable=True)
    stream = MemberStream(
        URL,
        member,
        chunk_bytes=8192,
        max_scan_bytes=10**9,
        max_inflated_bytes=10**9,
        max_seconds=-1.0,
    )
    with pytest.raises(ScanLimitExceeded, match="passed") as caught:
        await _read_all(stream)
    assert caught.value.scanned == 0


async def test_a_slow_range_does_not_outlive_the_deadline(httpx_mock):
    text = _delta_text(20000)
    body, member = _member_zip(text)
    serve = _serve(body)

    async def slow(request: httpx.Request) -> httpx.Response:
        if request.headers["range"] != f"bytes={member.header_offset}-{member.header_offset + 29}":
            await asyncio.sleep(2.0)
        return serve(request)

    httpx_mock.add_callback(slow, url=URL, is_reusable=True)
    stream = MemberStream(
        URL,
        member,
        chunk_bytes=8192,
        max_scan_bytes=10**9,
        max_inflated_bytes=10**9,
        max_seconds=0.3,
        prefetch=2,
    )
    started = time.monotonic()
    with pytest.raises(ScanLimitExceeded, match="passed"):
        await _read_all(stream)
    assert time.monotonic() - started < 1.5
