"""Stream a large remote ZIP member a range at a time, and re-enter it later.

`shared/remote_zip.read_member` returns a whole member in memory (20 MB
cap). A StatCan Delta File CSV is up to 3.9 GB compressed and 29 GB
inflated (2026-10-01), so a caller that needs a few rows of a sorted file
reads it as a stream: ranges are fetched in order, inflated incrementally
(bounded output per step, so a deflate bomb cannot balloon memory) and
handed over as batches of complete lines.

This reader bounds the bytes it *scans*, not the member's size: the member
may be gigabytes as long as the caller stops reading (`break` out of
`batches()`) before the ceiling. Hitting the ceiling raises
`ScanLimitExceeded`, carrying the bytes scanned.

Re-entering a deflate stream. Deflate cannot be started at an arbitrary
byte, but it can be started at a block boundary given the 32 KiB of output
before it (zlib's zran.c "access points"). Python's zlib has no Z_BLOCK
flag to report boundaries, so they are found by parsing candidate dynamic
block headers bit by bit and then *verified*: the candidate is inflated
with the window from the main stream and must reproduce the main stream's
own output byte for byte. A stream records one verified access point every
`point_spacing` compressed bytes (`points`) and can start from one
(`start`), so a later scan resumes where an earlier one stopped.

Measured 2026-10-03 on the 20261001 Delta CSV: dynamic blocks start about
every 27 KB of compressed data; a block start entered with an all-zero
window instead of the real one decoded 4 MB with 71% of its bytes still
copied from the unknown window (whole lines repeat by back-reference), so
a real window, from an earlier sequential pass, is required.
"""

from __future__ import annotations

import asyncio
import struct
import time
import zlib
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator
from dataclasses import dataclass

from maplestats_mcp.shared import remote_zip
from maplestats_mcp.shared.errors import UpstreamError
from maplestats_mcp.shared.remote_zip import ZipMember

_LOCAL = b"PK\x03\x04"
_INFLATE_STEP = 16 * 1024 * 1024
WINDOW_BYTES = 32 * 1024
# A dynamic block header is at most about 560 bytes (19 code-length codes
# and 316 code lengths of up to 14 bits each).
_HEADER_SPAN = 600
_CODE_LENGTH_ORDER = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15)
# Compressed bytes inflated from a candidate block start to verify it.
_VERIFY_BYTES = 64 * 1024
_VERIFY_MIN_OUTPUT = 4096
_POINT_SEARCH_BYTES = 512 * 1024


class ScanLimitExceeded(UpstreamError):
    """The stream reached its compressed-bytes or time ceiling before the caller stopped."""

    def __init__(self, message: str, scanned: int) -> None:
        super().__init__(message)
        self.scanned = scanned


@dataclass(frozen=True)
class AccessPoint:
    """A deflate block start the member's stream can be re-entered at."""

    bit_offset: int  # bits from the member's first data byte
    out_offset: int  # inflated bytes before the block
    window: bytes  # up to 32 KiB of output just before the block


def _complete(lengths: list[int]) -> bool:
    """Whether Huffman code lengths form a complete prefix code (Kraft sum of 1)."""
    total = 0
    for length in lengths:
        if length:
            total += 1 << (15 - length)
    return total == 1 << 15


def _dynamic_header_ok(bits: int) -> bool:
    """Whether `bits` (LSB first) start with a valid, non-final dynamic block header."""
    hlit, hdist = (bits >> 3) & 31, (bits >> 8) & 31
    if hlit > 29 or hdist > 29:
        return False
    count = ((bits >> 13) & 15) + 4
    code_lengths = [0] * 19
    for i in range(count):
        code_lengths[_CODE_LENGTH_ORDER[i]] = (bits >> (17 + 3 * i)) & 7
    if not _complete(code_lengths):
        return False

    # Canonical code: codes are assigned in order of (length, symbol) and
    # read from the stream bit-reversed.
    table: dict[tuple[int, int], int] = {}
    code = 0
    for length in range(1, 8):
        for symbol in range(19):
            if code_lengths[symbol] == length:
                reversed_code = int(f"{code:0{length}b}"[::-1], 2)
                table[(length, reversed_code)] = symbol
                code += 1
        code <<= 1

    pos = 17 + 3 * count
    needed = hlit + 257 + hdist + 1
    lengths: list[int] = []
    while len(lengths) < needed:
        symbol = None
        for length in range(1, 8):
            symbol = table.get((length, (bits >> pos) & ((1 << length) - 1)))
            if symbol is not None:
                pos += length
                break
        if symbol is None:
            return False
        if symbol < 16:
            lengths.append(symbol)
        elif symbol == 16:
            if not lengths:
                return False
            lengths.extend([lengths[-1]] * (3 + ((bits >> pos) & 3)))
            pos += 2
        elif symbol == 17:
            lengths.extend([0] * (3 + ((bits >> pos) & 7)))
            pos += 3
        else:
            lengths.extend([0] * (11 + ((bits >> pos) & 127)))
            pos += 7
        if pos > _HEADER_SPAN * 8:
            return False
    if len(lengths) != needed:
        return False
    literals, distances = lengths[: hlit + 257], lengths[hlit + 257 :]
    if literals[256] == 0 or not _complete(literals):
        return False
    # zlib accepts a distance code with a single code (an incomplete set).
    return sum(1 for d in distances if d) <= 1 or _complete(distances)


def block_candidates(data: bytes, limit: int, begin: int = 0) -> Iterator[int]:
    """Bit offsets in `data[begin:limit]` that parse as a dynamic block header.

    A candidate is not proof: it must still be verified against real output.
    """
    end = min(limit, len(data) - _HEADER_SPAN)
    for byte in range(max(0, begin), max(0, end)):
        word = data[byte] | data[byte + 1] << 8 | data[byte + 2] << 16
        for bit in range(8):
            head = word >> bit
            # BFINAL 0 and BTYPE 2 (dynamic), then HLIT and HDIST in range.
            if head & 7 != 4 or (head >> 3) & 31 > 29 or (head >> 8) & 31 > 29:
                continue
            bits = int.from_bytes(data[byte : byte + _HEADER_SPAN], "little") >> bit
            if _dynamic_header_ok(bits):
                yield byte * 8 + bit


class _BitShifter:
    """Re-align a byte stream that starts `shift` bits into its first byte."""

    def __init__(self, shift: int) -> None:
        self.shift = shift
        self.held = b""

    def feed(self, raw: bytes) -> bytes:
        if not self.shift:
            return raw
        buffer = self.held + raw
        if not buffer:
            return b""
        value = int.from_bytes(buffer, "little") >> self.shift
        # The last byte still lacks the bits the next range will bring.
        self.held = buffer[-1:]
        return value.to_bytes(len(buffer), "little")[:-1]

    def flush(self) -> bytes:
        if not self.shift or not self.held:
            return b""
        return bytes([self.held[0] >> self.shift])


class MemberStream:
    """Complete lines of one ZIP member, fetched by range and inflated as they arrive.

    `start` resumes at an access point (lines then begin at the first line
    starting at or after it, with no CSV header); `point_spacing` records a
    verified access point about every that many compressed bytes;
    `prefetch` keeps that many range requests in flight, each started at
    least `min_request_interval` seconds after the previous one.
    """

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
        start: AccessPoint | None = None,
        point_spacing: int | None = None,
        prefetch: int = 1,
        min_request_interval: float = 0.0,
    ) -> None:
        if start is not None and member.method != 8:
            raise ValueError("Only a deflated member can be resumed at an access point.")
        self.url = url
        self.member = member
        self.chunk_bytes = chunk_bytes
        self.max_scan_bytes = max_scan_bytes
        self.max_inflated_bytes = max_inflated_bytes
        self.max_seconds = max_seconds
        self.first_chunk_bytes = first_chunk_bytes
        self.before_fetch = before_fetch
        self.start = start
        self.point_spacing = point_spacing if member.method == 8 else None
        self.prefetch = max(1, prefetch)
        self.min_request_interval = min_request_interval
        self.scanned = 0  # compressed bytes fetched by this stream
        self.inflated = 0  # bytes produced by this stream
        self.offset = start.bit_offset // 8 if start else 0  # member bytes consumed so far
        self.points: list[AccessPoint] = []
        self._last_request = 0.0
        self._pace = asyncio.Lock()

    async def _fetch(self, start: int, end: int) -> bytes:
        if self.min_request_interval > 0:
            # Requests start one at a time and at least min_request_interval
            # apart (a host's requested delay); they may then overlap in flight.
            async with self._pace:
                wait = self._last_request + self.min_request_interval - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_request = time.monotonic()
        if self.before_fetch is not None:
            await self.before_fetch()
        return await remote_zip.fetch_range(self.url, start, end)

    def _check_time(self, started: float) -> None:
        if self.max_seconds is not None and time.monotonic() - started > self.max_seconds:
            raise ScanLimitExceeded(
                f"{self.member.name}: {self.max_seconds:.0f} s passed after scanning "
                f"{self.scanned:,} compressed bytes.",
                self.scanned,
            )

    async def batches(self) -> AsyncGenerator[list[bytes]]:
        """Yield lists of complete lines, line endings (LF or CRLF) removed.

        Without `start`, the first line of the first batch is the CSV header.
        """
        blocks = self.blocks()
        try:
            async for block in blocks:
                yield [line.rstrip(b"\r") for line in block.split(b"\n")]
        finally:
            await blocks.aclose()

    async def blocks(self) -> AsyncGenerator[bytes]:
        """Yield runs of complete lines as bytes joined by b"\\n" (no final newline).

        Cheaper than `batches()` for a caller that skips most of the data by
        looking only at a run's first and last line: splitting 29 GB into
        lines costs more than inflating it. A CRLF file keeps its b"\\r".
        Raises UpstreamError for an unsupported compression method, a member
        that changed under the stored offsets, or a deflate error; raises
        ScanLimitExceeded at the compressed or time ceiling.
        """
        member = self.member
        if member.method not in (0, 8):
            raise UpstreamError(f"{member.name} uses ZIP compression method {member.method}.")
        header = await self._fetch(member.header_offset, member.header_offset + 29)
        if header[:4] != _LOCAL:
            raise UpstreamError(f"{self.url}: the archive changed while it was being read; retry.")
        name_len, extra_len = struct.unpack("<HH", header[26:30])
        data_start = member.header_offset + 30 + name_len + extra_len
        end = data_start + member.compressed_size
        start_bit = self.start.bit_offset if self.start else 0
        first_byte = data_start + start_bit // 8
        limit = min(end, first_byte + self.max_scan_bytes)
        shifter = _BitShifter(start_bit % 8)
        if member.method == 8:
            window = self.start.window if self.start else b""
            inflater = zlib.decompressobj(-15, zdict=window) if window else zlib.decompressobj(-15)
        else:
            window, inflater = b"", None
        out_offset = self.start.out_offset if self.start else 0
        # Lines begin at a line start: resuming mid-line drops the partial one.
        skip_partial = bool(self.start and window and not window.endswith(b"\n"))
        logical = 0  # re-aligned bytes handed to the inflater so far
        last_point = 0  # re-aligned offset of the last recorded access point
        carry = b""
        started = time.monotonic()
        pending: deque[asyncio.Task[bytes]] = deque()
        next_start = first_byte
        # Doubling from a small first range: a table near the start of the
        # file is found after one small request, a deep one with few large ones.
        chunk = min(self.first_chunk_bytes, self.chunk_bytes)

        def schedule() -> None:
            nonlocal next_start, chunk
            while len(pending) < self.prefetch and next_start < limit:
                stop = min(next_start + chunk, limit) - 1
                pending.append(asyncio.ensure_future(self._fetch(next_start, stop)))
                next_start = stop + 1
                chunk = min(chunk * 2, self.chunk_bytes)

        chunk_out = 0  # bytes inflated from the range being processed

        def inflate(piece: bytes) -> bytes:
            nonlocal window, chunk_out
            if inflater is None:
                return piece
            pieces: list[bytes] = []
            try:
                pending_input = piece
                while pending_input:
                    # Never inflate more than one byte past the ceiling: a
                    # deflate bomb in one range is stopped here, before the
                    # whole range's output is held in memory.
                    room = self.max_inflated_bytes - self.inflated - chunk_out + 1
                    out_piece = inflater.decompress(pending_input, max(1, min(_INFLATE_STEP, room)))
                    pieces.append(out_piece)
                    chunk_out += len(out_piece)
                    if self.inflated + chunk_out > self.max_inflated_bytes:
                        raise ScanLimitExceeded(
                            f"{member.name} inflated past {self.max_inflated_bytes:,} bytes.",
                            self.scanned,
                        )
                    # Past the final block, zlib keeps any bytes left (the
                    # re-aligned stream's last partial byte) as unconsumed
                    # input when max_length is given; they are not data.
                    if inflater.eof:
                        break
                    pending_input = inflater.unconsumed_tail
            except zlib.error as exc:
                raise UpstreamError(
                    f"{member.name} is not valid deflate data ({exc}); the archive may have "
                    "been replaced while it was being read, retry."
                ) from exc
            out = b"".join(pieces)
            window = (window + out[-WINDOW_BYTES:])[-WINDOW_BYTES:]
            return out

        def process(raw: bytes, last: bool) -> bytes:
            """Re-align, record a due access point and inflate one range (in a thread)."""
            nonlocal logical, last_point, out_offset, chunk_out
            chunk_out = 0
            aligned = shifter.feed(raw)
            if last:
                aligned += shifter.flush()
            produced: list[bytes] = []
            consumed = 0
            due = (
                self.point_spacing is not None
                and logical + len(aligned) - last_point >= self.point_spacing
            )
            if due and inflater is not None and self.point_spacing is not None:
                # Not right after the previous point (or the stream's start).
                begin = max(0, last_point + self.point_spacing // 2 - logical)
                found = self._find_point(
                    aligned, inflater, window, start_bit, logical, out_offset, begin
                )
                if found is not None:
                    cut, point_out, point = found
                    head = inflate(aligned[:cut])
                    if len(head) != point_out:
                        raise UpstreamError(f"{member.name}: inconsistent inflate at a block.")
                    produced.append(head)
                    consumed = cut
                    self.points.append(point)
                    last_point = logical + cut
            produced.append(inflate(aligned[consumed:]))
            logical += len(aligned)
            data = b"".join(produced)
            out_offset += len(data)
            return data

        try:
            schedule()
            while pending:
                self._check_time(started)
                task = pending.popleft()
                if self.max_seconds is None:
                    raw = await task
                else:
                    # A slow range must not carry the call past its deadline.
                    left = self.max_seconds - (time.monotonic() - started)
                    try:
                        raw = await asyncio.wait_for(task, max(left, 0.001))
                    except TimeoutError as exc:
                        raise ScanLimitExceeded(
                            f"{member.name}: {self.max_seconds:.0f} s passed after scanning "
                            f"{self.scanned:,} compressed bytes.",
                            self.scanned,
                        ) from exc
                self.scanned += len(raw)
                self.offset += len(raw)
                schedule()
                # zlib releases the GIL while inflating, so the ranges in
                # flight keep downloading while this one is inflated.
                data = await asyncio.to_thread(process, raw, next_start >= end and not pending)
                self.inflated += len(data)
                if self.inflated > self.max_inflated_bytes:
                    raise ScanLimitExceeded(
                        f"{member.name} inflated past {self.max_inflated_bytes:,} bytes.",
                        self.scanned,
                    )
                data = carry + data
                cut = data.rfind(b"\n")
                if cut < 0:
                    carry = data
                    continue
                block, carry = data[:cut], data[cut + 1 :]
                if skip_partial:
                    newline = block.find(b"\n")
                    block = block[newline + 1 :] if newline >= 0 else b""
                    skip_partial = False
                if block:
                    yield block
            if next_start < end:
                raise ScanLimitExceeded(
                    f"{member.name}: scanned {self.scanned:,} compressed bytes without reaching "
                    "the requested rows.",
                    self.scanned,
                )
            if carry.strip() and not skip_partial:
                yield carry
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    def _find_point(
        self,
        aligned: bytes,
        inflater: zlib._Decompress,
        previous: bytes,
        start_bit: int,
        logical: int,
        out_offset: int,
        begin: int,
    ) -> tuple[int, int, AccessPoint] | None:
        """A verified block start near the beginning of `aligned`.

        Returns (bytes of `aligned` to feed before it, output that feed
        yields, the access point), leaving `inflater` untouched.
        """
        probe = inflater.copy()
        fed = 0
        produced = 0
        tail = previous
        try:
            for bit in block_candidates(aligned, begin + _POINT_SEARCH_BYTES, begin):
                cut = bit // 8 + 1
                if cut > fed:
                    # Feeding through the byte that holds the block's first
                    # bit completes the previous block's end-of-block code and
                    # nothing of the next block (its header is longer than
                    # the 7 bits left), so the output is exactly the
                    # output before the block.
                    out = probe.decompress(aligned[fed:cut])
                    produced += len(out)
                    tail = (tail + out[-WINDOW_BYTES:])[-WINDOW_BYTES:]
                    fed = cut
                # Verify: the main stream and the candidate must inflate the
                # next bytes identically (a false header decodes to an error
                # or to other bytes).
                truth = probe.copy().decompress(aligned[cut : cut + _VERIFY_BYTES])
                if len(truth) < _VERIFY_MIN_OUTPUT:
                    # Too close to the range's end to prove anything.
                    return None
                candidate = zlib.decompressobj(-15, zdict=tail) if tail else zlib.decompressobj(-15)
                shifted = _BitShifter(bit % 8).feed(aligned[bit // 8 : cut + _VERIFY_BYTES])
                try:
                    guess = candidate.decompress(shifted)
                except zlib.error:
                    continue
                if guess and len(guess) >= len(truth) - 1024 and truth.startswith(guess):
                    point = AccessPoint(
                        bit_offset=start_bit + 8 * logical + bit,
                        out_offset=out_offset + produced,
                        window=tail,
                    )
                    return cut, produced, point
        except zlib.error:
            return None
        return None
