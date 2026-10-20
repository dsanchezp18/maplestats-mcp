"""Getting bytes out of LODE zips: cached member downloads and range-read previews.

A member is unpacked into MAPLE_LODE_CACHE_DIR once and reused. The archive
is downloaded whole (a deflated member cannot be read from the middle), only
after its size is checked against the per-call cap. A download that outlives
the tool timeout keeps running (asyncio.shield), so a retry finds it done.

Previews never download the archive: they read the member's compressed
stream with Range requests from the start and inflate it as it arrives, so
the first rows of a 400 MB CSV inside a 1.67 GB zip cost a few MB.
"""

from __future__ import annotations

import asyncio
import codecs
import csv
import hashlib
import logging
import struct
import zipfile
import zlib
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt

from maplestats_mcp.modules.statcan.lang import say
from maplestats_mcp.modules.statcan.lode import constants
from maplestats_mcp.shared import remote_zip
from maplestats_mcp.shared.capped_io import FileTooLarge, check_size, copy_capped
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.executor import run_in_pool
from maplestats_mcp.shared.file_download import check_redirect
from maplestats_mcp.shared.fr_typography import call_error
from maplestats_mcp.shared.http import (
    is_retryable,
    new_client,
    request_headers,
    wait_honouring_retry_after,
)

# Redirects are followed by _open, which checks every hop against the data host.
_client = new_client(timeout=600.0, follow_redirects=False)
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 4
_downloads: dict[str, asyncio.Task[Path]] = {}
_log = logging.getLogger(__name__)


def _allow_host(host: str) -> bool:
    return host == constants.ALLOWED_HOST


@asynccontextmanager
async def _open(method: str, url: str, headers: dict[str, str]) -> AsyncIterator[httpx.Response]:
    """The final response of a request, following redirects only to https on the data host."""
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        if current != url:
            check_redirect(url, current, _allow_host, "statcan_lode")
        async with _client.stream(method, current, headers=headers) as response:
            location = response.headers.get("location")
            if response.status_code in _REDIRECT_STATUSES and location:
                current = urljoin(str(response.url), location)
                continue
            yield response
            return
    raise call_error(
        UpstreamError,
        f"statcan_lode: {url} redirected more than {_MAX_REDIRECTS} times.",
        f"statcan_lode : {url} a redirigé plus de {_MAX_REDIRECTS} fois.",
    )


def _missing(url: str) -> NotFound:
    return NotFound(
        say(
            f"statcan_lode: no file at {url} (HTTP 404); the link may have moved. "
            "Search the catalogue again for the current link.",
            f"statcan_lode : aucun fichier à {url} (HTTP 404) ; le lien a peut-être changé. "
            "Cherchez de nouveau dans le catalogue le lien actuel.",
        )
    )


def check_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != constants.ALLOWED_HOST:
        raise InvalidInput(
            say(
                f"url must be a {constants.ALLOWED_HOST} download link, got {url!r}.",
                f"url doit être un lien de téléchargement de {constants.ALLOWED_HOST}, reçu {url!r}.",
            )
        )
    if not parsed.path.lower().endswith(".zip"):
        raise InvalidInput(
            say(
                f"url must point to a .zip file, got {url!r}.",
                f"url doit pointer vers un fichier .zip, reçu {url!r}.",
            )
        )
    return url


def cache_path(url: str, member: str) -> Path:
    key = hashlib.sha1(f"{url}|{member}".encode()).hexdigest()[:16]
    return constants.cache_dir() / key / Path(member).name


def cached(url: str, member: str) -> Path | None:
    target = cache_path(url, member)
    return target if target.exists() else None


def _enforce_cap(keep: Path) -> None:
    """Remove the least recently used cached files until the cache fits its cap.

    Never removes `keep` (the member the current call just unpacked and is
    about to read), and never a `.part` file: that is another call's download
    in progress. A file that cannot be removed (Windows refuses while a reader
    has it open) or that vanishes mid-scan is logged and skipped, because
    failing to make room must not fail a call whose own data is already on disk.
    """
    root = constants.cache_dir()
    entries: list[tuple[float, int, Path]] = []
    for path in root.rglob("*"):
        if path.name.endswith(".part") or not path.is_file():
            continue
        try:
            info = path.stat()
        except OSError:
            continue
        entries.append((info.st_mtime, info.st_size, path))
    entries.sort(key=lambda entry: entry[0])
    total = sum(size for _, size, _ in entries)
    for _, size, path in entries:
        if total <= constants.cache_max_bytes():
            break
        if path == keep:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            _log.warning("LODE cache: could not remove %s: %s", path.name, exc)
            continue
        total -= size


async def _download(url: str, member: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    archive = target.parent / "archive.zip.part"
    try:
        async with _open("GET", url, request_headers(url, None)) as response:
            response.raise_for_status()
            written = 0
            with archive.open("wb") as handle:
                async for chunk in response.aiter_bytes(1 << 20):
                    written += len(chunk)
                    check_size(written, constants.cache_max_bytes(), url)
                    handle.write(chunk)
    except (FileTooLarge, UpstreamError):
        archive.unlink(missing_ok=True)
        raise
    except httpx.HTTPStatusError as exc:
        archive.unlink(missing_ok=True)
        if exc.response.status_code in (404, 410):
            raise _missing(url) from exc
        raise UpstreamUnavailable(
            say(
                f"statcan_lode: download of {url} failed: {exc}",
                f"statcan_lode : le téléchargement de {url} a échoué : {exc}",
            )
        ) from exc
    except Exception as exc:
        archive.unlink(missing_ok=True)
        raise UpstreamUnavailable(
            say(
                f"statcan_lode: download of {url} failed: {exc}",
                f"statcan_lode : le téléchargement de {url} a échoué : {exc}",
            )
        ) from exc

    def extract() -> None:
        part = target.with_suffix(target.suffix + ".part")
        try:
            with zipfile.ZipFile(archive) as zf, zf.open(member) as source, part.open("wb") as sink:
                copy_capped(source, sink, constants.cache_max_bytes(), f"{member} in {url}")
            part.replace(target)
        except FileTooLarge:
            part.unlink(missing_ok=True)
            raise
        except (zipfile.BadZipFile, KeyError, OSError) as exc:
            part.unlink(missing_ok=True)
            raise UpstreamError(
                say(
                    f"{url} could not be unpacked: {exc}",
                    f"{url} n'a pas pu être décompressé : {exc}",
                )
            ) from exc
        finally:
            archive.unlink(missing_ok=True)
        _enforce_cap(target)

    await run_in_pool(extract)
    return target


async def local_member(url: str, member: str) -> tuple[Path, bool]:
    """The unpacked member's path and whether this call had to download it."""
    target = cache_path(url, member)
    if target.exists():
        target.touch()
        return target, False
    key = str(target)
    task = _downloads.get(key)
    if task is None or task.done():
        task = asyncio.create_task(_download(url, member, target))
        _downloads[key] = task
    return await asyncio.shield(task), True


# --- range previews -----------------------------------------------------


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(5),
    wait=wait_honouring_retry_after,
    reraise=True,
)
async def _get_range(url: str, start: int, end: int) -> httpx.Response:
    async with _open(
        "GET", url, request_headers(url, {"Range": f"bytes={start}-{end}"})
    ) as response:
        await response.aread()
    response.raise_for_status()
    return response


async def _range(url: str, start: int, end: int) -> bytes:
    try:
        response = await _get_range(url, start, end)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 410):
            raise _missing(url) from exc
        raise UpstreamError(
            say(
                f"{url} returned HTTP {exc.response.status_code}.",
                f"{url} a renvoyé HTTP {exc.response.status_code}.",
            )
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            say(f"{url} could not be reached.", f"{url} est injoignable.")
        ) from exc
    if response.status_code != 206:
        raise UpstreamError(
            say(
                f"{url} does not support range requests (HTTP {response.status_code}).",
                f"{url} n'accepte pas les requêtes de plage (HTTP {response.status_code}).",
            )
        )
    return response.content


async def head_size(url: str) -> tuple[int | None, str | None]:
    """(size in bytes, Last-Modified) from a HEAD request; None where the server omits them."""
    try:
        async with _open("HEAD", url, request_headers(url, None)) as response:
            await response.aread()
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 410):
            raise _missing(url) from exc
        raise UpstreamError(
            say(
                f"{url} returned HTTP {exc.response.status_code}.",
                f"{url} a renvoyé HTTP {exc.response.status_code}.",
            )
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            say(f"{url} could not be reached.", f"{url} est injoignable.")
        ) from exc
    length = response.headers.get("content-length")
    return (int(length) if length and length.isdigit() else None), response.headers.get(
        "last-modified"
    )


async def stream_member(
    url: str, member: remote_zip.ZipMember, max_compressed: int
) -> tuple[list[bytes], int, bool]:
    """Inflated chunks from the start of a member, the compressed bytes read, and
    whether the whole member was read. Stored and deflated members only.
    """
    if member.method not in (0, 8):
        raise UpstreamError(
            say(
                f"{member.name} uses ZIP compression method {member.method}.",
                f"{member.name} utilise la méthode de compression ZIP {member.method}.",
            )
        )
    header = await _range(url, member.header_offset, member.header_offset + 29)
    if header[:4] != b"PK\x03\x04":
        raise UpstreamError(
            say(
                f"{url}: malformed ZIP local header for {member.name}.",
                f"{url} : en-tête local ZIP mal formé pour {member.name}.",
            )
        )
    name_len, extra_len = struct.unpack("<HH", header[26:30])
    start = member.header_offset + 30 + name_len + extra_len
    inflater = zlib.decompressobj(-15) if member.method == 8 else None
    chunks: list[bytes] = []
    read = 0
    while read < member.compressed_size and read < max_compressed:
        end = min(
            start + read + constants.RANGE_CHUNK_BYTES - 1,
            start + member.compressed_size - 1,
            start + max_compressed - 1,
        )
        data = await _range(url, start + read, end)
        read += len(data)
        chunks.append(inflater.decompress(data) if inflater else data)
        if inflater and inflater.eof:
            break
    return chunks, read, read >= member.compressed_size


def decode_lines(chunks: list[bytes], complete: bool) -> Iterator[str]:
    """Text lines (with endings) from inflated chunks; a cut final line is dropped
    unless the member was read to its end. UTF-8 first, CP1252 when that fails.
    """
    raw = b"".join(chunks)
    text = None
    for encoding in ("utf-8-sig", "cp1252"):
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
        try:
            text = decoder.decode(raw, final=complete)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("latin-1")
    lines = text.splitlines(keepends=True)
    if lines and not complete and not lines[-1].endswith(("\n", "\r")):
        lines.pop()
    yield from lines


def read_rows(
    chunks: list[bytes], complete: bool, match: dict[str, str], limit: int
) -> tuple[list[str], list[dict[str, str | None]]]:
    """Header and up to `limit` rows whose columns equal every `match` value
    (case-insensitive, trimmed)."""
    reader = csv.reader(decode_lines(chunks, complete))
    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration:
        return [], []
    lower = {h.lower(): i for i, h in enumerate(header)}
    wanted: list[tuple[int, str]] = []
    for key, value in match.items():
        if key.lower() not in lower:
            raise InvalidInput(
                say(
                    f"No column {key!r}. Columns: {', '.join(header)}.",
                    f"Aucune colonne {key!r}. Colonnes : {', '.join(header)}.",
                )
            )
        wanted.append((lower[key.lower()], value.strip().lower()))
    rows: list[dict[str, str | None]] = []
    for record in reader:
        if len(record) != len(header):
            continue
        if all(record[i].strip().lower() == v for i, v in wanted):
            rows.append({h: (c.strip() or None) for h, c in zip(header, record, strict=True)})
            if len(rows) >= limit:
                break
    return header, rows
