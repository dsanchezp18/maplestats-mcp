"""Search reaction terms in the Canada Vigilance extract, read as a stream.

`shared/remote_zip` and `shared/zip_stream` jump to a ZIP's directory and
members by byte range. That does not work here: canada.ca answers a range
request only with gzip content encoding, over a gzip-compressed copy of
the ZIP (see constants.py), and a gzip stream can only be decoded from its
start. So this module reads the stream from byte 0, walks the ZIP's local
headers in order (every member is deflated with its sizes in the local
header: general-purpose flag 0, checked live 2026-10-03), skips the
members before reactions.txt, inflates that one, and stops reading as soon
as it ends, about 103 of 355 MB in. A ceiling on the compressed bytes and
a time limit stop the read earlier; the result then says it is partial.

reactions.txt rows, `$`-delimited and double-quoted, UTF-8:
reaction id, report id, duration, duration unit (English, French),
preferred term (English, French), system organ class (English, French),
MedDRA version. Rows come in roughly ascending report id order.
"""

from __future__ import annotations

import re
import struct
import time
import zlib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from maplestats_mcp.modules.health_products.vigilance import constants
from maplestats_mcp.shared.errors import UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import run_in_pool
from maplestats_mcp.shared.http import new_client, request_headers

_LOCAL = b"PK\x03\x04"
_CENTRAL = b"PK\x01\x02"
_INFLATE_STEP = 8 * 1024 * 1024
# canada.ca reset the HTTP/2 stream for this file on every try (2026-10-03,
# RST_STREAM error 2 before the headers); over HTTP/1.1 it streams normally.
_CLIENT = new_client(timeout=60.0, http2=False)


class ZipWalker:
    """Walks a ZIP fed in order, handing one member's inflated bytes to `sink`."""

    def __init__(self, member_suffix: str, sink: Callable[[bytes], None]) -> None:
        self.member_suffix = member_suffix
        self.sink = sink
        self.buffer = bytearray()
        self.remaining = 0  # compressed bytes left in the current member
        self.inflater: zlib._Decompress | None = None
        self.in_target = False
        self.found = False
        self.done = False
        self.folder: str | None = None

    def feed(self, data: bytes) -> None:
        self.buffer += data
        while not self.done:
            if self.remaining:
                take = min(self.remaining, len(self.buffer))
                if not take:
                    return
                chunk = bytes(self.buffer[:take])
                del self.buffer[:take]
                self.remaining -= take
                if self.in_target:
                    self._inflate(chunk)
                    if not self.remaining:
                        self.done = True
                continue
            if len(self.buffer) < 30:
                return
            signature = bytes(self.buffer[:4])
            if signature == _CENTRAL:
                # The directory follows the last member: the target was absent.
                self.done = True
                return
            if signature != _LOCAL:
                raise UpstreamError(
                    "The Canada Vigilance extract is not laid out as expected (no ZIP local "
                    "header where one should start)."
                )
            flags, method, csize, _usize, name_len, extra_len = struct.unpack(
                "<2xHH8xIIHH", self.buffer[4:30]
            )
            if len(self.buffer) < 30 + name_len + extra_len:
                return
            name = bytes(self.buffer[30 : 30 + name_len]).decode("utf-8", errors="replace")
            del self.buffer[: 30 + name_len + extra_len]
            if flags & 0x08:
                raise UpstreamError(
                    f"{name} in the Canada Vigilance extract has no sizes in its header, so it "
                    "cannot be read as a stream."
                )
            if "/" in name and self.folder is None:
                self.folder = name.split("/", 1)[0]
            self.remaining = csize
            self.in_target = name.endswith(self.member_suffix)
            if self.in_target:
                if method != 8:
                    raise UpstreamError(f"{name} uses ZIP compression method {method}.")
                self.found = True
                self.inflater = zlib.decompressobj(-15)
                if csize == 0:
                    self.done = True

    def _inflate(self, chunk: bytes) -> None:
        assert self.inflater is not None
        pending = chunk
        try:
            while pending:
                self.sink(self.inflater.decompress(pending, _INFLATE_STEP))
                pending = self.inflater.unconsumed_tail
        except zlib.error as exc:
            raise UpstreamError(
                f"The Canada Vigilance extract's reactions file is not valid deflate data ({exc})."
            ) from exc


@dataclass
class ReactionMatcher:
    """Collects reactions.txt rows whose term or organ class matches."""

    reaction: str
    soc: str
    min_report_id: int
    lang: str
    carry: bytes = b""
    rows: int = 0
    newest_report_id: int = 0
    hits: dict[int, tuple[set[str], set[str]]] = field(default_factory=dict)
    terms: Counter[str] = field(default_factory=Counter)
    socs: Counter[str] = field(default_factory=Counter)

    def __post_init__(self) -> None:
        # The cheap block-level test: a line is parsed only if the block
        # contains the rarer of the two words, ignoring ASCII case.
        probe = self.reaction or self.soc
        self._probe = re.compile(re.escape(probe.encode("utf-8")), re.IGNORECASE)
        self._reaction = self.reaction.casefold()
        self._soc = self.soc.casefold()

    def feed(self, data: bytes) -> None:
        data = self.carry + data
        cut = data.rfind(b"\n")
        if cut < 0:
            self.carry = data
            return
        self.carry = data[cut + 1 :]
        block = data[: cut + 1]
        self._track_newest(block)
        seen: set[int] = set()
        for match in self._probe.finditer(block):
            start = block.rfind(b"\n", 0, match.start()) + 1
            if start in seen:
                continue
            seen.add(start)
            end = block.find(b"\n", match.end())
            self._line(block[start:end])

    def finish(self) -> None:
        if self.carry.strip():
            self._track_newest(self.carry)
            if self._probe.search(self.carry):
                self._line(self.carry)
        self.carry = b""

    def _track_newest(self, block: bytes) -> None:
        tail = block.rstrip(b"\r\n")
        last = tail[tail.rfind(b"\n") + 1 :]
        parts = last.split(b'"$"')
        if len(parts) > 1 and parts[1].isdigit():
            self.newest_report_id = max(self.newest_report_id, int(parts[1]))

    def _line(self, raw: bytes) -> None:
        fields = raw.decode("utf-8", errors="replace").strip().strip('"').split('"$"')
        if len(fields) < 9 or not fields[1].isdigit():
            return
        report_id = int(fields[1])
        if report_id < self.min_report_id:
            return
        pt_en, pt_fr, soc_en, soc_fr = fields[5], fields[6], fields[7], fields[8]
        if self._reaction and not (
            self._reaction in pt_en.casefold() or self._reaction in pt_fr.casefold()
        ):
            return
        if self._soc and not (self._soc in soc_en.casefold() or self._soc in soc_fr.casefold()):
            return
        pt = (pt_fr or pt_en) if self.lang == "fr" else pt_en
        soc = (soc_fr or soc_en) if self.lang == "fr" else soc_en
        self.rows += 1
        self.terms[pt] += 1
        self.socs[soc] += 1
        terms, classes = self.hits.setdefault(report_id, (set(), set()))
        terms.add(pt)
        classes.add(soc)


@dataclass
class ScanOutcome:
    matcher: ReactionMatcher
    complete: bool
    scanned_bytes: int
    folder: str | None
    last_modified: str | None
    stop_reason: str | None


class _Pipeline:
    """gzip-decoded ZIP bytes -> ZipWalker -> ReactionMatcher, run off the event loop."""

    def __init__(self, matcher: ReactionMatcher) -> None:
        self.matcher = matcher
        self.walker = ZipWalker("/" + constants.REACTIONS_MEMBER, matcher.feed)

    def feed(self, data: bytes) -> bool:
        self.walker.feed(data)
        return self.walker.done


async def scan_reactions(
    matcher: ReactionMatcher, *, max_bytes: int, max_seconds: float
) -> ScanOutcome:
    pipeline = _Pipeline(matcher)
    started = time.monotonic()
    stop_reason: str | None = None
    complete = False
    headers = request_headers(constants.EXTRACT_URL, {"Accept-Encoding": "gzip"})
    try:
        async with _CLIENT.stream("GET", constants.EXTRACT_URL, headers=headers) as response:
            if response.status_code != 200:
                raise UpstreamError(
                    f"canada.ca answered HTTP {response.status_code} for the Canada Vigilance "
                    "extract."
                )
            last_modified = response.headers.get("last-modified")
            pending = b""
            async for chunk in response.aiter_bytes():
                pending += chunk
                if len(pending) < 1024 * 1024:
                    continue
                if await run_in_pool(pipeline.feed, pending):
                    complete = True
                    break
                pending = b""
                if response.num_bytes_downloaded >= max_bytes:
                    stop_reason = f"the {max_bytes / 1e6:.0f} MB read ceiling"
                    break
                if time.monotonic() - started > max_seconds:
                    stop_reason = f"the {max_seconds:.0f} s time limit"
                    break
            else:
                if pending and await run_in_pool(pipeline.feed, pending):
                    complete = True
            scanned = response.num_bytes_downloaded
    except httpx.TimeoutException as exc:
        raise UpstreamUnavailable("canada.ca stopped sending the Canada Vigilance extract.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"The Canada Vigilance extract could not be read ({type(exc).__name__})."
        ) from exc
    if not complete and stop_reason is None:
        if not pipeline.walker.found:
            raise UpstreamError("The Canada Vigilance extract has no reactions.txt file.")
        raise UpstreamError("The Canada Vigilance extract ended inside reactions.txt.")
    if complete and not pipeline.walker.found:
        raise UpstreamError("The Canada Vigilance extract has no reactions.txt file.")
    matcher.finish()
    return ScanOutcome(
        matcher=matcher,
        complete=complete,
        scanned_bytes=scanned,
        folder=pipeline.walker.folder,
        last_modified=last_modified,
        stop_reason=stop_reason,
    )
