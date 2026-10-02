"""Stream one large member of a remote ZIP, a range at a time.

`shared/remote_zip.read_member` returns a whole member in memory, capped
at 20 MB; a transit feed's `stop_times.txt` is 92 to 373 MB inflated, so
it is read here as a stream instead: ranges of `SCAN_CHUNK_BYTES` are
fetched in order, inflated incrementally (bounded output per step, so a
deflate bomb cannot balloon memory) and handed to the caller as batches
of complete lines. Confirmed live 2026-10-01 against all four feeds'
servers: each answers 206 with exactly the requested bytes.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import AsyncIterator

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from maplestats_mcp.modules.transit import constants
from maplestats_mcp.shared.errors import UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import is_retryable, new_client
from maplestats_mcp.shared.rate_limiter import get_limiter
from maplestats_mcp.shared.remote_zip import ZipMember

_LOCAL = b"PK\x03\x04"
_INFLATE_STEP = 16 * 1024 * 1024
_LIMITER = get_limiter(
    constants.SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_client = new_client(timeout=90.0, follow_redirects=True)


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
    reraise=True,
)
async def _get_range(url: str, start: int, end: int) -> httpx.Response:
    await _LIMITER.acquire()
    response = await _client.get(url, headers={"Range": f"bytes={start}-{end}"})
    response.raise_for_status()
    return response


async def head(url: str) -> httpx.Response:
    """Headers of the feed, following redirects (Calgary's link goes to a CDN).

    One HEAD first; the City of Toronto's host answered HEAD with a 502
    far more often than a ranged GET on 2026-10-01, so a failed HEAD falls
    back to a one-byte range (retried), whose headers carry the same
    Last-Modified and, in Content-Range, the total size.
    """
    await _LIMITER.acquire()
    try:
        response = await _client.head(url)
        response.raise_for_status()
        return response
    except httpx.HTTPError:
        pass
    try:
        return await _get_range(url, 0, 0)
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(f"{url} returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"{url} could not be reached.") from exc


def total_bytes(response: httpx.Response) -> int | None:
    """Size of the whole file from Content-Range (a ranged reply) or Content-Length."""
    total = response.headers.get("content-range", "").rpartition("/")[2]
    if total.isdigit():
        return int(total)
    length = response.headers.get("content-length")
    return int(length) if length and length.isdigit() else None


async def fetch_range(url: str, start: int, end: int) -> bytes:
    """Bytes `start..end` inclusive, exactly, or a typed error."""
    try:
        response = await _get_range(url, start, end)
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(f"{url} returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"{url} could not be reached.") from exc
    expected = end - start + 1
    if response.status_code != 206 or len(response.content) != expected:
        raise UpstreamError(
            f"{url} did not honour the byte range {start}-{end} "
            f"(HTTP {response.status_code}, {len(response.content):,} bytes)."
        )
    return response.content


async def stream_member_lines(url: str, member: ZipMember) -> AsyncIterator[list[bytes]]:
    """Yield batches of the member's complete lines, line endings removed.

    The first line of the first batch is the CSV header. Raises
    UpstreamError when the member is over the configured bounds, uses an
    unsupported compression method, or the archive changed under the
    stored offsets (a replaced feed): callers should drop their cached
    directory and retry once.
    """
    if member.compressed_size > constants.SCAN_MAX_COMPRESSED_BYTES:
        raise UpstreamError(
            f"{member.name} is {member.compressed_size:,} bytes compressed, over the "
            f"{constants.SCAN_MAX_COMPRESSED_BYTES:,}-byte scan limit."
        )
    if member.method not in (0, 8):
        raise UpstreamError(f"{member.name} uses ZIP compression method {member.method}.")
    header = await fetch_range(url, member.header_offset, member.header_offset + 29)
    if header[:4] != _LOCAL:
        raise UpstreamError(f"{url}: the feed changed while it was being read; retry.")
    name_len, extra_len = struct.unpack("<HH", header[26:30])
    position = member.header_offset + 30 + name_len + extra_len
    end = position + member.compressed_size
    inflater = zlib.decompressobj(-15) if member.method == 8 else None
    carry = b""
    produced = 0
    while position < end:
        stop = min(position + constants.SCAN_CHUNK_BYTES, end) - 1
        raw = await fetch_range(url, position, stop)
        position = stop + 1
        pieces: list[bytes] = []
        if inflater is None:
            pieces.append(raw)
        else:
            try:
                pending = raw
                while pending:
                    pieces.append(inflater.decompress(pending, _INFLATE_STEP))
                    pending = inflater.unconsumed_tail
            except zlib.error as exc:
                raise UpstreamError(
                    f"{member.name} is not valid deflate data ({exc}); the feed may have "
                    "been replaced while it was being read, retry."
                ) from exc
        data = carry + b"".join(pieces)
        produced += len(data) - len(carry)
        if produced > constants.SCAN_MAX_UNCOMPRESSED_BYTES:
            raise UpstreamError(
                f"{member.name} inflates past the {constants.SCAN_MAX_UNCOMPRESSED_BYTES:,}-byte "
                "scan limit."
            )
        lines = data.split(b"\n")
        carry = lines.pop()
        if lines:
            yield [line.rstrip(b"\r") for line in lines]
    if carry.strip():
        yield [carry.rstrip(b"\r")]
