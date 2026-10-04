"""Read a remote ZIP's file list and single members with HTTP range requests.

StatCan's PUMF zips run to 182 MB (Census 2021 individuals), but their
codebooks and command files are tens of KB. Confirmed live 2026-09-24:
www150.statcan.gc.ca answers `Accept-Ranges: bytes` and 206 Partial
Content, so the central directory (at the end of the file) and one
member can be fetched without downloading the archive: listing the
Census zip took 12 KB.

Only stored (0) and deflated (8) members are supported, which is what
every StatCan PUMF zip sampled uses. ZIP64 is supported (end-of-directory
locator and record, and the 0x0001 extra field of each directory entry):
StatCan's Delta File of 2026-10-01 is a 3.87 GB zip whose CSV inflates to
29 GB, so its directory entry carries 0xFFFFFFFF in the 32-bit size field.
"""

from __future__ import annotations

import ipaddress
import struct
import zlib
from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt

from maplestats_mcp.shared.errors import UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.fr_typography import call_error
from maplestats_mcp.shared.http import (
    is_retryable,
    new_client,
    request_headers,
    wait_honouring_retry_after,
)
from maplestats_mcp.shared.i18n import fr_number

_EOCD = b"PK\x05\x06"
_CENTRAL = b"PK\x01\x02"
_LOCAL = b"PK\x03\x04"
_EOCD64 = b"PK\x06\x06"
_LOCATOR64 = b"PK\x06\x07"
_MAX32 = 0xFFFFFFFF
_MAX16 = 0xFFFF
_TAIL_BYTES = 256 * 1024

# Object-storage hosts a publisher's link may hand off to (federal download
# links answer 302 to an Azure blob, Montreal's to Google Cloud Storage,
# confirmed 2026-10-02 in shared/file_download.py). Any other redirect must
# stay on the same site as the URL that issued it.
ALLOWED_REDIRECT_SUFFIXES = (
    ".blob.core.windows.net",
    ".storage.googleapis.com",
    "storage.googleapis.com",
    ".amazonaws.com",
    ".cloudfront.net",
)


def _site(host: str) -> str:
    """The registrable part of a host: statcan.gc.ca, gov.bc.ca, ttc.ca."""
    labels = host.lower().rstrip(".").split(".")
    keep = 2
    if (
        len(labels) >= 3
        and labels[-1] == "ca"
        and (labels[-2] in {"gc", "gov"} or len(labels[-2]) == 2)
    ):
        keep = 3
    return ".".join(labels[-keep:])


def redirect_allowed(source: httpx.URL, target: httpx.URL) -> bool:
    """Whether a redirect from `source` may be followed to `target`.

    Never to plain http from https, never to an IP address or localhost
    (a redirect is how a public link would reach a private network), and
    only to the same site or a known object-storage host.
    """
    host = (target.host or "").lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        ipaddress.ip_address(host.strip("[]"))
        return False
    except ValueError:
        pass
    if target.scheme != "https" and not (source.scheme == "http" and target.scheme == "http"):
        return False
    if _site(host) == _site(source.host or ""):
        return True
    return any(host == s.lstrip(".") or host.endswith(s) for s in ALLOWED_REDIRECT_SUFFIXES)


async def _check_redirect(response: httpx.Response) -> None:
    if not response.is_redirect:
        return
    location = response.headers.get("location", "")
    target = response.request.url.join(location)
    if not redirect_allowed(response.request.url, target):
        raise call_error(
            UpstreamError,
            f"{response.request.url} redirected to {target.host or location!r}, which is not "
            "the same site or a known file host, so the redirect was not followed.",
            f"{response.request.url} a redirigé vers {target.host or location!r}, qui n'est "
            "ni le même site ni un hôte de fichiers connu ; la redirection n'a pas été suivie.",
        )


_client = new_client(timeout=60.0, follow_redirects=True)
_client.event_hooks = {
    "request": _client.event_hooks["request"],
    "response": [*_client.event_hooks["response"], _check_redirect],
}


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
    wait=wait_honouring_retry_after,
    reraise=True,
)


@_RETRY
async def _get_range(url: str, start: int, end: int) -> httpx.Response:
    response = await _client.get(
        url, headers=request_headers(url, {"Range": f"bytes={start}-{end}"})
    )
    response.raise_for_status()
    return response


async def _range(url: str, start: int, end: int) -> bytes:
    try:
        response = await _get_range(url, start, end)
    except httpx.HTTPStatusError as exc:
        raise call_error(
            UpstreamError,
            f"{url} returned HTTP {exc.response.status_code}.",
            f"{url} a renvoyé HTTP {exc.response.status_code}.",
        ) from exc
    except httpx.HTTPError as exc:
        raise call_error(
            UpstreamUnavailable, f"{url} could not be reached.", f"{url} est injoignable."
        ) from exc
    if response.status_code != 206:
        raise call_error(
            UpstreamError,
            f"{url} does not support range requests (HTTP {response.status_code}).",
            f"{url} ne prend pas en charge les requêtes par plage (HTTP {response.status_code}).",
        )
    # A 206 can still be short (a truncated transfer, or a server that
    # clamps the range); slicing ZIP structures out of a short body would
    # misread them silently, so the length is checked, not assumed.
    expected = end - start + 1
    if len(response.content) != expected:
        raise call_error(
            UpstreamError,
            f"{url} returned {len(response.content):,} bytes for a {expected:,}-byte range.",
            f"{url} a renvoyé {fr_number(len(response.content))} octets pour une plage de "
            f"{fr_number(expected)} octets.",
        )
    return response.content


async def fetch_range(url: str, start: int, end: int) -> bytes:
    """Bytes `start..end` inclusive, exactly, or a typed error (for streaming readers)."""
    return await _range(url, start, end)


async def _size(url: str) -> int:
    # HEAD first; some hosts answer it with a 502 far more often than a
    # ranged GET (Toronto's open-data host, 2026-10-01), so any HEAD
    # failure falls back to reading the total from a one-byte range.
    try:
        response = await _client.head(url, headers=request_headers(url, None))
        response.raise_for_status()
        length = response.headers.get("content-length")
        if length:
            return int(length)
    except httpx.HTTPError:
        pass
    try:
        ranged = await _get_range(url, 0, 0)
    except httpx.HTTPError as exc:
        raise call_error(
            UpstreamUnavailable, f"{url} could not be reached.", f"{url} est injoignable."
        ) from exc
    total = ranged.headers.get("content-range", "").rpartition("/")[2]
    if not total.isdigit():
        raise call_error(
            UpstreamError,
            f"{url} reports no size, so it cannot be read by range.",
            f"{url} n'indique pas sa taille ; il ne peut donc pas être lu par plages.",
        )
    return int(total)


async def remote_size(url: str) -> int:
    """Total bytes of a remote file (HEAD, or a one-byte range), for range readers."""
    return await _size(url)


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
        raise call_error(
            UpstreamError,
            f"{url} is not a ZIP file (no end-of-directory record).",
            f"{url} n'est pas un fichier ZIP (aucun enregistrement de fin de répertoire).",
        )
    _, _, _, _, count, cd_size, cd_offset, _ = struct.unpack("<4sHHHHIIH", tail[eocd : eocd + 22])
    if _MAX32 in (cd_offset, cd_size) or count == _MAX16:
        count, cd_size, cd_offset = await _zip64_directory(url, tail, tail_start, eocd)
    if cd_offset >= tail_start:
        directory = tail[cd_offset - tail_start : cd_offset - tail_start + cd_size]
    else:
        directory = await _range(url, cd_offset, cd_offset + cd_size - 1)

    members: list[ZipMember] = []
    pos = 0
    for _ in range(count):
        if directory[pos : pos + 4] != _CENTRAL:
            raise call_error(
                UpstreamError,
                f"{url}: malformed ZIP central directory.",
                f"{url} : répertoire central ZIP mal formé.",
            )
        (flags, method, csize, usize, name_len, extra_len, comment_len, offset) = struct.unpack(
            # versions (4), flags, method, time/date/crc (8), sizes, name/extra/
            # comment lengths, disk/attributes (8), local header offset.
            "<4xHH8xIIHHH8xI",
            directory[pos + 4 : pos + 46],
        )
        name = _decode_name(directory[pos + 46 : pos + 46 + name_len], flags)
        extra = directory[pos + 46 + name_len : pos + 46 + name_len + extra_len]
        usize, csize, offset = _zip64_sizes(extra, usize, csize, offset)
        members.append(ZipMember(name, csize, usize, method, offset))
        pos += 46 + name_len + extra_len + comment_len
    return members, total


async def _zip64_directory(
    url: str, tail: bytes, tail_start: int, eocd: int
) -> tuple[int, int, int]:
    """Entry count, directory size and offset from the ZIP64 end record."""
    locator = tail[max(0, eocd - 20) : eocd]
    if len(locator) != 20 or locator[:4] != _LOCATOR64:
        raise call_error(
            UpstreamError,
            f"{url} is a ZIP64 archive without a ZIP64 end-of-directory locator.",
            f"{url} est une archive ZIP64 sans localisateur de fin de répertoire ZIP64.",
        )
    record_offset = struct.unpack("<4xIQI", locator)[1]
    if record_offset >= tail_start:
        record = tail[record_offset - tail_start : record_offset - tail_start + 56]
    else:
        record = await _range(url, record_offset, record_offset + 55)
    if len(record) != 56 or record[:4] != _EOCD64:
        raise call_error(
            UpstreamError,
            f"{url}: malformed ZIP64 end-of-directory record.",
            f"{url} : enregistrement de fin de répertoire ZIP64 mal formé.",
        )
    # signature, record size, versions (2 + 2), disk numbers (4 + 4), entries
    # on this disk, total entries, directory size, directory offset.
    _, _, _, _, _, _, _, count, cd_size, cd_offset = struct.unpack("<4sQHHIIQQQQ", record)
    return count, cd_size, cd_offset


def _zip64_sizes(extra: bytes, usize: int, csize: int, offset: int) -> tuple[int, int, int]:
    """Replace each 0xFFFFFFFF field by its value from the 0x0001 extra field.

    The extra field lists, in this fixed order, only the values whose 32-bit
    slot holds 0xFFFFFFFF: uncompressed size, compressed size, header offset.
    """
    if _MAX32 not in (usize, csize, offset):
        return usize, csize, offset
    pos = 0
    while pos + 4 <= len(extra):
        tag, length = struct.unpack("<HH", extra[pos : pos + 4])
        if tag == 1:
            body = extra[pos + 4 : pos + 4 + length]
            values = [struct.unpack("<Q", body[i : i + 8])[0] for i in range(0, len(body) - 7, 8)]
            take = iter(values)
            try:
                if usize == _MAX32:
                    usize = next(take)
                if csize == _MAX32:
                    csize = next(take)
                if offset == _MAX32:
                    offset = next(take)
            except StopIteration as exc:
                raise call_error(
                    UpstreamError,
                    "A ZIP64 extra field is shorter than its sizes need.",
                    "Un champ supplémentaire ZIP64 est plus court que ses tailles ne l'exigent.",
                ) from exc
            return usize, csize, offset
        pos += 4 + length
    raise call_error(
        UpstreamError,
        "A ZIP entry marks a size as ZIP64 but has no ZIP64 extra field.",
        "Une entrée ZIP indique une taille ZIP64 mais n'a pas de champ supplémentaire ZIP64.",
    )


async def read_member(url: str, member: ZipMember, *, max_bytes: int = 20_000_000) -> bytes:
    """One member's contents, at most `max_bytes` both compressed and
    decompressed. The callers read codebooks and layout files (tens of KB
    to a few MB), so 20 MB is generous for them while still stopping a
    deflate bomb, whose tiny compressed size the first check alone passes.
    """
    if member.compressed_size > max_bytes:
        raise call_error(
            UpstreamError,
            f"{member.name} is {member.compressed_size:,} bytes compressed, over this reader's "
            f"{max_bytes:,}-byte limit.",
            f"{member.name} fait {fr_number(member.compressed_size)} octets compressés, au-delà "
            f"de la limite de {fr_number(max_bytes)} octets de ce lecteur.",
        )
    if member.method not in (0, 8):
        raise call_error(
            UpstreamError,
            f"{member.name} uses ZIP compression method {member.method}.",
            f"{member.name} utilise la méthode de compression ZIP {member.method}.",
        )
    header = await _range(url, member.header_offset, member.header_offset + 29)
    if header[:4] != _LOCAL:
        raise call_error(
            UpstreamError,
            f"{url}: malformed ZIP local header for {member.name}.",
            f"{url} : en-tête local ZIP mal formé pour {member.name}.",
        )
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
            raise call_error(
                UpstreamError,
                f"{name} decompresses to over this reader's {max_bytes:,}-byte limit.",
                f"{name} dépasse une fois décompressé la limite de {fr_number(max_bytes)} octets "
                "de ce lecteur.",
            )
        out += inflater.flush()
    except zlib.error as exc:
        raise call_error(
            UpstreamError,
            f"{name} is not valid deflate data: {exc}.",
            f"{name} n'est pas un flux deflate valide : {exc}.",
        ) from exc
    if len(out) > max_bytes:
        raise call_error(
            UpstreamError,
            f"{name} decompresses to over this reader's {max_bytes:,}-byte limit.",
            f"{name} dépasse une fois décompressé la limite de {fr_number(max_bytes)} octets de ce lecteur.",
        )
    if not inflater.eof:
        raise call_error(
            UpstreamError,
            f"{name}: deflate stream is truncated.",
            f"{name} : le flux deflate est tronqué.",
        )
    return out
