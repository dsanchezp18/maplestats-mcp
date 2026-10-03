"""Stream the start of a large remote ZIP member, a range at a time.

`shared/remote_zip.read_member` returns a whole member in memory (20 MB
cap). A StatCan Delta File CSV is up to 3.9 GB compressed and 29 GB
inflated (2026-10-01), so a caller that needs only the first rows of a
sorted file reads it as a stream: ranges of `chunk_bytes` are fetched in
order, inflated incrementally (bounded output per step, so a deflate bomb
cannot balloon memory) and handed over as batches of complete lines.

Unlike `modules/transit/zipstream.py`, which refuses a member whose whole
compressed size is over its limit, this reader bounds the bytes it
*scans*: the member may be gigabytes as long as the caller stops reading
(`break` out of `batches()`) before the ceiling. Hitting the ceiling raises
`ScanLimitExceeded`, carrying the bytes scanned, so a caller can point the
user at a bulk-download route instead of streaming gigabytes.
"""

from __future__ import annotations

import struct
import time
import zlib
from collections.abc import AsyncGenerator, Awaitable, Callable

from maplestats_mcp.shared import remote_zip
from maplestats_mcp.shared.errors import UpstreamError
from maplestats_mcp.shared.remote_zip import ZipMember

_LOCAL = b"PK\x03\x04"
_INFLATE_STEP = 16 * 1024 * 1024


class ScanLimitExceeded(UpstreamError):
    """The stream reached its compressed-bytes ceiling before the caller stopped."""

    def __init__(self, message: str, scanned: int) -> None:
        super().__init__(message)
        self.scanned = scanned


class MemberStream:
    """Complete lines of one ZIP member, fetched by range and inflated as they arrive."""

    def __init__(
        self,
        url: str,
        member: ZipMember,
        *,
        chunk_bytes: int,
        max_scan_bytes: int,
        max_inflated_bytes: int,
        max_seconds: float | None = None,
        first_chunk_bytes: int = 1024 * 1024,
        before_fetch: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.url = url
        self.member = member
        self.chunk_bytes = chunk_bytes
        self.max_scan_bytes = max_scan_bytes
        self.max_inflated_bytes = max_inflated_bytes
        self.max_seconds = max_seconds
        self.first_chunk_bytes = first_chunk_bytes
        self.before_fetch = before_fetch
        self.scanned = 0  # compressed bytes fetched so far
        self.inflated = 0  # bytes produced so far

    async def _fetch(self, start: int, end: int) -> bytes:
        if self.before_fetch is not None:
            await self.before_fetch()
        return await remote_zip.fetch_range(self.url, start, end)

    async def batches(self) -> AsyncGenerator[list[bytes]]:
        """Yield lists of complete lines, line endings removed.

        The first line of the first batch is the CSV header. Raises
        UpstreamError for an unsupported compression method, a member that
        changed under the stored offsets, or a deflate error; raises
        ScanLimitExceeded at the compressed ceiling.
        """
        member = self.member
        if member.method not in (0, 8):
            raise UpstreamError(f"{member.name} uses ZIP compression method {member.method}.")
        header = await self._fetch(member.header_offset, member.header_offset + 29)
        if header[:4] != _LOCAL:
            raise UpstreamError(f"{self.url}: the archive changed while it was being read; retry.")
        name_len, extra_len = struct.unpack("<HH", header[26:30])
        data_start = member.header_offset + 30 + name_len + extra_len
        position = data_start
        end = data_start + member.compressed_size
        inflater = zlib.decompressobj(-15) if member.method == 8 else None
        carry = b""
        started = time.monotonic()
        # Doubling from a small first range: a table near the start of the
        # file is found after one small request, a deep one with few large ones.
        chunk = min(self.first_chunk_bytes, self.chunk_bytes)
        while position < end:
            if position - data_start >= self.max_scan_bytes:
                raise ScanLimitExceeded(
                    f"{member.name}: scanned {self.scanned:,} compressed bytes without reaching "
                    "the requested rows.",
                    self.scanned,
                )
            if self.max_seconds is not None and time.monotonic() - started > self.max_seconds:
                raise ScanLimitExceeded(
                    f"{member.name}: {self.max_seconds:.0f} s passed after scanning "
                    f"{self.scanned:,} compressed bytes.",
                    self.scanned,
                )
            stop = min(position + chunk, end, data_start + self.max_scan_bytes) - 1
            raw = await self._fetch(position, stop)
            self.scanned += len(raw)
            position = stop + 1
            chunk = min(chunk * 2, self.chunk_bytes)
            pieces: list[bytes] = []
            if inflater is None:
                pieces.append(raw)
            else:
                try:
                    pending = raw
                    produced = 0
                    while pending:
                        # Never inflate more than one byte past the ceiling: a
                        # deflate bomb in one chunk is stopped here, before the
                        # whole chunk's output is held in memory.
                        room = self.max_inflated_bytes - self.inflated - produced + 1
                        piece = inflater.decompress(pending, max(1, min(_INFLATE_STEP, room)))
                        pieces.append(piece)
                        produced += len(piece)
                        if self.inflated + produced > self.max_inflated_bytes:
                            raise ScanLimitExceeded(
                                f"{member.name} inflated past {self.max_inflated_bytes:,} bytes.",
                                self.scanned,
                            )
                        pending = inflater.unconsumed_tail
                except zlib.error as exc:
                    raise UpstreamError(
                        f"{member.name} is not valid deflate data ({exc}); the archive may have "
                        "been replaced while it was being read, retry."
                    ) from exc
            data = carry + b"".join(pieces)
            self.inflated += len(data) - len(carry)
            if self.inflated > self.max_inflated_bytes:
                raise ScanLimitExceeded(
                    f"{member.name} inflated past {self.max_inflated_bytes:,} bytes.",
                    self.scanned,
                )
            lines = data.split(b"\n")
            carry = lines.pop()
            if lines:
                yield [line.rstrip(b"\r") for line in lines]
        if carry.strip():
            yield [carry.rstrip(b"\r")]
