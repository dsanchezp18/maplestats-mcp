"""Read the inside of a Delta File without downloading it, and list the archive.

Confirmed live 2026-10-02 against www150.statcan.gc.ca/n1/delta/:

- Each zip has exactly three deflated members, in this order: `codeSet.xml`
  (about 528 KB inflated, the code descriptions), `YYYYMMDD.xml` (the
  metadata of every cube released that day; 240 KB to 6 MB) and
  `YYYYMMDD.csv` (the data; sorted ascending by productId, one contiguous
  block per table). Sizes run from 91 KB to 3.87 GB (20261001, whose CSV
  inflates to 29 GB, so the zip is ZIP64).
- The server answers `Accept-Ranges: bytes` and 206, with `ETag` and
  `Last-Modified` (about 8:30 ET), so the central directory and a member
  are read by range requests.
- The published `/delta/` URL answers 301 to `/n1/delta/`; this module goes
  straight to the `/n1/` URL.
- A date with no file answers 404, for a weekend, a holiday (20260930 has
  none) and a date past the roughly 47 business days that are kept.
- Rows are never deleted; a correction arrives in the next day's file.
  The CSV's values are raw: the scalar factor is not applied.
"""

from __future__ import annotations

import asyncio
import html
import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as date_cls
from email.utils import parsedate_to_datetime
from xml.etree.ElementTree import Element

import httpx
from defusedxml import ElementTree
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from maplestats_mcp.modules.statcan.delta import constants
from maplestats_mcp.modules.statcan.delta.archive_schemas import (
    DeltaCorrection,
    DeltaDimension,
    DeltaFileEntry,
    DeltaFileList,
    DeltaLegend,
    DeltaMember,
    DeltaRow,
    DeltaTable,
    DeltaTableData,
    DeltaTableList,
)
from maplestats_mcp.shared import remote_zip
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw, is_retryable, new_client
from maplestats_mcp.shared.rate_limiter import get_limiter
from maplestats_mcp.shared.remote_zip import ZipMember
from maplestats_mcp.shared.zip_stream import MemberStream, ScanLimitExceeded

ARCHIVE_URL = "https://www150.statcan.gc.ca/n1/delta/{date}.zip"
PAGE_URL = "https://www.statcan.gc.ca/en/developers/df"
SCHEMA_URL = "https://www.statcan.gc.ca/en/developers-developpeurs/df-fd/cubemetadata.zip"
# Retention is about 47 business days (the page listed 47 files on
# 2026-10-02, 20260728 to 20261002), not the "5 releases" of the user guide.
RETENTION_BUSINESS_DAYS = 47
CACHE_TTL_SECONDS = 600
SCAN_CHUNK_BYTES = 8 * 1024 * 1024
# Measured 2026-10-02 from a home connection: about 2.5 MB/s from this
# host, so 200 MB took 80 to 100 s, close to the server's 120 s tool
# timeout. 100 MB (about 750 MB inflated on the 3.87 GB day) or 75 s,
# whichever comes first; past that a table is better fetched from WDS.
SCAN_MAX_COMPRESSED_BYTES = 100 * 1024 * 1024
SCAN_MAX_SECONDS = 75.0
SCAN_MAX_INFLATED_BYTES = 4 * 1024 * 1024 * 1024
MAX_XML_BYTES = 80 * 1024 * 1024
MAX_ROWS_CAP = 10_000
MAX_VECTOR_FILTER = 1_000

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_client = new_client(timeout=20.0, follow_redirects=True)
_BOM = chr(0xFEFF)
_TAG = re.compile(r"<[^>]+>")
_PAGE_FILE = re.compile(r"/delta/(\d{8})\.zip")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class Archive:
    date: str
    url: str
    size: int
    last_modified: str | None
    etag: str | None
    codeset: ZipMember
    metadata: ZipMember
    data: ZipMember


def _parse_date(date: str) -> tuple[date_cls, str]:
    try:
        parsed = date_cls.fromisoformat(date)
    except ValueError as exc:
        raise InvalidInput(f"Expected a YYYY-MM-DD date, got {date!r}.") from exc
    return parsed, ARCHIVE_URL.format(date=parsed.strftime("%Y%m%d"))


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
    reraise=True,
)
async def _head_once(url: str) -> httpx.Response:
    await _LIMITER.acquire()
    response = await _client.head(url)
    if response.status_code != 404:
        response.raise_for_status()
    return response


async def _head(url: str) -> httpx.Response:
    try:
        return await _head_once(url)
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(f"{url} returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"{url} could not be reached.") from exc


def _as_of(last_modified: str | None) -> datetime | None:
    if not last_modified:
        return None
    try:
        return parsedate_to_datetime(last_modified).astimezone(UTC)
    except (TypeError, ValueError):
        return None


async def _open_archive(date: str) -> Archive:
    parsed, url = _parse_date(date)

    async def fetch() -> Archive:
        return await _fetch_archive(parsed, url)

    archive, _ = await cached_fetch(f"delta:archive:{parsed.isoformat()}", CACHE_TTL_SECONDS, fetch)
    return archive


async def _fetch_archive(parsed: date_cls, url: str) -> Archive:
    """The archive's three members, from a HEAD and a central-directory range read."""
    head = await _head(url)
    if head.status_code == 404:
        raise NotFound(await _missing_message(parsed))
    members, total = await remote_zip.list_members(url)
    stamp = parsed.strftime("%Y%m%d")
    by_name = {m.name: m for m in members}
    try:
        return Archive(
            date=parsed.isoformat(),
            url=url,
            size=total,
            last_modified=head.headers.get("last-modified"),
            etag=head.headers.get("etag"),
            codeset=by_name["codeSet.xml"],
            metadata=by_name[f"{stamp}.xml"],
            data=by_name[f"{stamp}.csv"],
        )
    except KeyError as exc:
        names = ", ".join(by_name) or "none"
        raise UpstreamError(
            f"{url} does not hold the expected codeSet.xml, {stamp}.xml and {stamp}.csv "
            f"(members: {names})."
        ) from exc


async def _missing_message(parsed: date_cls) -> str:
    """Why a date has no file: weekend, holiday, past retention or not yet published."""
    status = await _date_status(parsed, None)
    return (
        f"No Delta File exists for {parsed.isoformat()}: {status}. "
        "Use statcan_delta_list_files for the dates that are available."
    )


async def _page_dates() -> list[str]:
    try:
        response = await get_raw(PAGE_URL)
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(f"{PAGE_URL} returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"{PAGE_URL} could not be reached.") from exc
    dates = sorted(set(_PAGE_FILE.findall(response.text)))
    if not dates:
        raise UpstreamError(f"{PAGE_URL} lists no Delta File links; the page may have changed.")
    return dates


async def _date_status(parsed: date_cls, listed: list[str] | None) -> str:
    stamps = listed if listed is not None else await _page_dates()
    stamp = parsed.strftime("%Y%m%d")
    if stamp in stamps:
        return "available"
    oldest, newest = stamps[0], stamps[-1]
    if stamp < oldest:
        return (
            f"past retention (the oldest file kept is {_iso(oldest)}; about "
            f"{RETENTION_BUSINESS_DAYS} business days are available)"
        )
    if stamp > newest:
        return f"not yet published (the newest file is {_iso(newest)}; released about 8:30 ET)"
    kind = "a weekend" if parsed.weekday() >= 5 else "a holiday or a day without a release"
    return f"no release that day ({kind})"


def _iso(stamp: str) -> str:
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"


def _text(element: Element, tag: str) -> str | None:
    value = element.findtext(tag)
    return value.strip() if value and value.strip() else None


def _int(element: Element, tag: str) -> int | None:
    value = _text(element, tag)
    return int(value) if value and value.lstrip("-").isdigit() else None


def _strip_html(value: str | None) -> str | None:
    if not value:
        return None
    return html.unescape(_TAG.sub(" ", value)).strip() or None


def _cube(element: Element, *, lang: str, detail: bool) -> DeltaTable:
    """One cube; `detail` adds dimension members and correction notes."""
    dimensions: list[DeltaDimension] = []
    for dimension in element.iterfind("dimensions/dimension"):
        members = list(dimension.iterfind("members/member"))
        dimensions.append(
            DeltaDimension(
                position_id=_int(dimension, "dimensionPositionId") or 0,
                name_en=_text(dimension, "dimensionNameEn"),
                name_fr=_text(dimension, "dimensionNameFr"),
                member_count=len(members),
                members=[
                    DeltaMember(
                        member_id=_int(member, "memberId") or 0,
                        name_en=_text(member, "memberNameEn"),
                        name_fr=_text(member, "memberNameFr"),
                        terminated=(_int(member, "terminated") == 1)
                        if _int(member, "terminated") is not None
                        else None,
                    )
                    for member in members
                ]
                if detail
                else None,
            )
        )
    corrections = list(element.iterfind("corrections/correction"))
    suffix = "Fr" if lang == "fr" else "En"
    return DeltaTable(
        product_id=_int(element, "productId") or 0,
        cansim_id=_text(element, "cansimId"),
        title_en=_text(element, "cubeTitleEn"),
        title_fr=_text(element, "cubeTitleFr"),
        frequency_code=_int(element, "frequencyCode"),
        frequency=_text(element, f"frequency{suffix}"),
        release_time=_text(element, "releaseTime"),
        series_count=_int(element, "nbSeriesCube"),
        datapoint_count=_int(element, "nbDatapointsCube"),
        start_date=_text(element, "cubeStartDate"),
        end_date=_text(element, "cubeEndDate"),
        archive_status_code=_int(element, "archiveStatusCode"),
        archive_status=_text(element, f"archiveStatus{suffix}"),
        correction_count=len(corrections),
        corrections=[
            DeltaCorrection(
                correction_id=_int(correction, "correctionId"),
                date=_text(correction, "correctionDate"),
                note=_strip_html(_text(correction, f"correctionNote{suffix}")),
            )
            for correction in corrections
        ]
        if detail
        else None,
        dimensions=dimensions,
    )


async def _read_cubes(
    archive: Archive, *, lang: str, detail_for: int | None = None
) -> tuple[list[DeltaTable], bool]:
    """Every cube in the release's metadata XML (one range read of the member).

    Members and correction notes are built only for `detail_for`, since the
    big days hold thousands of members. Cached per file version (ETag).
    """

    async def fetch() -> list[DeltaTable]:
        raw = await remote_zip.read_member(archive.url, archive.metadata, max_bytes=MAX_XML_BYTES)
        cubes: list[DeltaTable] = []
        try:
            for _, element in ElementTree.iterparse(io.BytesIO(raw), events=("end",)):
                if element.tag == "cube":
                    wanted = detail_for is not None and _int(element, "productId") == detail_for
                    cubes.append(_cube(element, lang=lang, detail=wanted))
                    element.clear()
        except ElementTree.ParseError as exc:
            raise UpstreamError(f"{archive.metadata.name} is not valid XML: {exc}.") from exc
        return cubes

    key = f"delta:cubes:{archive.date}:{archive.etag}:{lang}:{detail_for}"
    cubes, cached = await cached_fetch(key, CACHE_TTL_SECONDS, fetch)
    return cubes, cached


async def list_tables(
    date: str,
    *,
    product_id: int | None = None,
    query: str | None = None,
    detail: bool = False,
    max_tables: int = 200,
    lang: str = "en",
) -> DeltaTableList:
    if max_tables < 1:
        raise InvalidInput("max_tables must be at least 1.")
    if detail and product_id is None:
        raise InvalidInput("detail=True needs a product_id (members and corrections are long).")
    archive = await _open_archive(date)
    cubes, cached = await _read_cubes(archive, lang=lang, detail_for=product_id if detail else None)
    chosen = cubes
    if product_id is not None:
        chosen = [c for c in cubes if c.product_id == product_id]
        if not chosen:
            raise NotFound(
                f"Table {product_id} was not released in the Delta File of {archive.date}; "
                "call statcan_delta_list_tables without product_id for the tables that were."
            )
    if query:
        needle = query.casefold()
        chosen = [
            c for c in chosen if needle in f"{c.title_en or ''} {c.title_fr or ''}".casefold()
        ]
    shown = chosen[:max_tables]
    notes = [
        (
            "A table appears when its data or metadata changed that day; no rows are ever deleted, "
            "and a correction arrives in the next day's file."
        ),
        (
            "Files are published on business days about 8:30 ET. Read one table's rows with "
            "statcan_delta_read_table."
        ),
    ]
    return DeltaTableList(
        date=archive.date,
        zip_url=archive.url,
        zip_size_bytes=archive.size,
        last_modified=archive.last_modified,
        etag=archive.etag,
        table_count=len(cubes),
        returned=len(shown),
        truncated=len(chosen) > len(shown),
        tables=shown,
        notes=notes,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=archive.url,
            cached=cached,
            schema_name="statcan_delta.DeltaTableList",
            as_of=_as_of(archive.last_modified),
            freshness="One file per business day, about 8:30 ET; about 47 business days kept.",
            coverage=f"{len(cubes)} tables released on {archive.date}.",
            limits=f"Read by range requests from the {archive.size:,}-byte zip; "
            "only the metadata member was fetched.",
        ),
    )


def _parse_codeset(raw: bytes) -> dict[str, dict[int, tuple[str, str]]]:
    """Code -> (English, French) description for each code family used in the CSV."""
    root = ElementTree.fromstring(raw)
    families = {
        "symbols": ("symbol", "symbolCode", "symbolDescEn", "symbolDescFr"),
        "statuses": ("status", "statusCode", "statusDescEn", "statusDescFr"),
        "security_levels": (
            "securityLevel",
            "securityLevelCode",
            "securityLevelDescEn",
            "securityLevelDescFr",
        ),
        "scalar_factors": (
            "scalar",
            "scalarFactorCode",
            "scalarFactorDescEn",
            "scalarFactorDescFr",
        ),
        "frequencies": ("frequency", "frequencyCode", "frequencyDescEn", "frequencyDescFr"),
    }
    parsed: dict[str, dict[int, tuple[str, str]]] = {}
    for family, (item, code_tag, en_tag, fr_tag) in families.items():
        codes: dict[int, tuple[str, str]] = {}
        for element in root.iter(item):
            code = _int(element, code_tag)
            if code is not None:
                codes[code] = (_text(element, en_tag) or "", _text(element, fr_tag) or "")
        parsed[family] = codes
    return parsed


async def _codeset(archive: Archive) -> dict[str, dict[int, tuple[str, str]]]:
    async def fetch() -> dict[str, dict[int, tuple[str, str]]]:
        raw = await remote_zip.read_member(archive.url, archive.codeset)
        try:
            return _parse_codeset(raw)
        except ElementTree.ParseError as exc:
            raise UpstreamError(f"{archive.codeset.name} is not valid XML: {exc}.") from exc

    codes, _ = await cached_fetch(f"delta:codeset:{archive.date}:{archive.etag}", 3600, fetch)
    return codes


def _legend(
    codes: dict[str, dict[int, tuple[str, str]]], rows: list[DeltaRow], lang: str
) -> DeltaLegend:
    pick = 1 if lang == "fr" else 0
    used = {
        "symbols": {row.symbol_code for row in rows},
        "statuses": {row.status_code for row in rows},
        "security_levels": {row.security_level_code for row in rows},
        "scalar_factors": {row.scalar_factor_code for row in rows},
        "frequencies": {row.frequency_code for row in rows},
    }
    return DeltaLegend(
        **{
            family: {
                code: codes[family][code][pick] or codes[family][code][0]
                for code in sorted(used[family])
                if code in codes[family]
            }
            for family in used
        }
    )


def _row(fields: list[bytes], index: dict[str, int]) -> DeltaRow:
    def text(name: str) -> str:
        return fields[index[name]].decode("ascii", "replace")

    raw_value = text("value").strip()
    return DeltaRow(
        vector_id=int(text("vectorId")),
        coordinate=text("coordinate"),
        ref_period=text("refPer"),
        ref_period_end=text("refPer2") or None,
        value=float(raw_value) if raw_value else None,
        symbol_code=int(text("symbolCode")),
        status_code=int(text("statusCode")),
        security_level_code=int(text("securityLevelCode")),
        scalar_factor_code=int(text("scalarFactorCode")),
        decimals=int(text("decimals")),
        frequency_code=int(text("frequencyCode")),
        release_time=text("releaseTime"),
    )


_EXPECTED_COLUMNS = (
    "productId",
    "coordinate",
    "vectorId",
    "refPer",
    "refPer2",
    "symbolCode",
    "statusCode",
    "securityLevelCode",
    "value",
    "releaseTime",
    "scalarFactorCode",
    "decimals",
    "frequencyCode",
)


def _leading_id(line: bytes) -> int:
    head = line.split(b",", 1)[0]
    if not head.isdigit():
        raise UpstreamError(f"A Delta CSV line does not start with a productId: {line[:60]!r}.")
    return int(head)


async def read_table(
    date: str,
    product_id: int,
    *,
    vector_ids: list[int] | None = None,
    max_rows: int = 1000,
    lang: str = "en",
) -> DeltaTableData:
    if not 1 <= max_rows <= MAX_ROWS_CAP:
        raise InvalidInput(f"max_rows must be between 1 and {MAX_ROWS_CAP:,}.")
    if vector_ids is not None and len(vector_ids) > MAX_VECTOR_FILTER:
        raise InvalidInput(f"vector_ids takes at most {MAX_VECTOR_FILTER:,} ids.")
    wanted = set(vector_ids) if vector_ids else None
    archive = await _open_archive(date)

    # The metadata XML says whether the table was released at all, which
    # saves scanning a CSV (up to gigabytes) for a table that is not in it.
    cubes, _ = await _read_cubes(archive, lang=lang)
    cube = next((c for c in cubes if c.product_id == product_id), None)
    if cube is None:
        raise NotFound(
            f"Table {product_id} was not released in the Delta File of {archive.date} "
            f"({len(cubes)} tables were); call statcan_delta_list_tables for that list, or "
            "wds_get_full_table_download for the table's current data."
        )
    codes = await _codeset(archive)

    stream = MemberStream(
        archive.url,
        archive.data,
        chunk_bytes=SCAN_CHUNK_BYTES,
        max_scan_bytes=SCAN_MAX_COMPRESSED_BYTES,
        max_inflated_bytes=SCAN_MAX_INFLATED_BYTES,
        max_seconds=SCAN_MAX_SECONDS,
        before_fetch=_LIMITER.acquire,
    )
    rows: list[DeltaRow] = []
    index: dict[str, int] | None = None
    truncated = False
    done = False
    batches = stream.batches()
    try:
        async for batch in batches:
            if index is None:
                header = batch.pop(0).decode("ascii", "replace").lstrip(_BOM).split(",")
                index = {name: position for position, name in enumerate(header)}
                missing = [name for name in _EXPECTED_COLUMNS if name not in index]
                if missing:
                    raise UpstreamError(
                        f"{archive.data.name} lacks the columns {', '.join(missing)}; "
                        "the Delta CSV layout may have changed."
                    )
                if not batch:
                    continue
            # Sorted ascending by productId in contiguous blocks (confirmed
            # on 20260929 and 20261002), so a whole batch is skipped from its
            # first and last line and only the batches that touch the
            # block are read line by line.
            first, last = _leading_id(batch[0]), _leading_id(batch[-1])
            if first > last:
                raise UpstreamError(f"{archive.data.name} is not sorted by productId.")
            if last < product_id:
                continue
            if first > product_id:
                break
            for line in batch:
                current = _leading_id(line)
                if current < product_id:
                    continue
                if current > product_id:
                    done = True
                    break
                row = _row(line.split(b","), index)
                if wanted is not None and row.vector_id not in wanted:
                    continue
                if len(rows) >= max_rows:
                    truncated = True
                    done = True
                    break
                rows.append(row)
            if done:
                break
    except ScanLimitExceeded as exc:
        raise UpstreamError(
            f"Table {product_id} is too far into the Delta File of {archive.date} "
            f"({archive.data.compressed_size:,} bytes compressed): {exc.scanned:,} bytes were "
            f"scanned (limits {SCAN_MAX_COMPRESSED_BYTES:,} bytes and {SCAN_MAX_SECONDS:.0f} s) without finishing its rows. "
            "Use wds_get_changed_series_data (the series that changed) or "
            "wds_get_full_table_download (the whole table as CSV), or download "
            f"{archive.url} yourself."
        ) from exc
    finally:
        await batches.aclose()

    notes = [
        "Values are raw: the scalar factor is not applied (see legend.scalar_factors).",
        (
            "Deltas carry changed data points only, with no deletions; a correction arrives in the "
            "next business day's file."
        ),
    ]
    if not rows and not truncated:
        notes.append(
            "No CSV rows for this table"
            + (" matched vector_ids." if wanted else " (a metadata-only change).")
        )
    if truncated:
        notes.append(f"Stopped at max_rows={max_rows:,}; filter with vector_ids or raise max_rows.")
    return DeltaTableData(
        date=archive.date,
        product_id=product_id,
        cansim_id=cube.cansim_id,
        title_en=cube.title_en,
        title_fr=cube.title_fr,
        release_time=cube.release_time,
        series_count=cube.series_count,
        zip_url=archive.url,
        vector_filter=sorted(wanted) if wanted else None,
        row_count=len(rows),
        truncated=truncated,
        csv_rows_found=bool(rows),
        compressed_bytes_scanned=stream.scanned,
        rows=rows,
        legend=_legend(codes, rows, lang),
        notes=notes,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=archive.url,
            cached=False,
            schema_name="statcan_delta.DeltaTableData",
            as_of=_as_of(archive.last_modified),
            freshness="One file per business day, about 8:30 ET.",
            coverage=f"Table {product_id} in the release of {archive.date}.",
            limits=f"{stream.scanned:,} of {archive.data.compressed_size:,} compressed CSV bytes "
            f"read; rows capped at {max_rows:,}.",
        ),
    )


async def _file_headers(stamp: str) -> DeltaFileEntry:
    url = ARCHIVE_URL.format(date=stamp)
    parsed = date_cls(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))
    entry = DeltaFileEntry(date=parsed.isoformat(), weekday=_WEEKDAYS[parsed.weekday()], url=url)
    try:
        head = await _head(url)
    except (UpstreamError, UpstreamUnavailable):
        return entry
    if head.status_code != 200:
        return entry
    length = head.headers.get("content-length")
    entry.size_bytes = int(length) if length and length.isdigit() else None
    entry.last_modified = head.headers.get("last-modified")
    entry.etag = head.headers.get("etag")
    return entry


async def list_files(
    *, date: str | None = None, include_sizes: bool = False, lang: str = "en"
) -> DeltaFileList:
    del lang
    requested = _parse_date(date)[0] if date else None
    stamps = await _page_dates()
    if include_sizes:
        files = list(await asyncio.gather(*(_file_headers(s) for s in stamps)))
    else:
        files = []
        for stamp in stamps:
            parsed = date_cls(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))
            files.append(
                DeltaFileEntry(
                    date=parsed.isoformat(),
                    weekday=_WEEKDAYS[parsed.weekday()],
                    url=ARCHIVE_URL.format(date=stamp),
                )
            )
    files.sort(key=lambda f: f.date, reverse=True)
    notes = [
        (
            f"The page lists {len(stamps)} files, about {RETENTION_BUSINESS_DAYS} business days; "
            "older files are removed (the user guide's '5 releases' is out of date)."
        ),
        (
            "A file appears on business days about 8:30 ET. Holidays (for example 2026-09-30) have "
            "none. Corrections arrive in the next day's file; nothing is deleted."
        ),
        (
            "Each zip holds codeSet.xml, YYYYMMDD.xml (cube metadata) and YYYYMMDD.csv (data); the "
            f"metadata schema is at {SCHEMA_URL}."
        ),
    ]
    return DeltaFileList(
        files=files,
        count=len(files),
        oldest=files[-1].date if files else None,
        newest=files[0].date if files else None,
        requested_date=requested.isoformat() if requested else None,
        requested_status=await _date_status(requested, stamps) if requested else None,
        notes=notes,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=PAGE_URL,
            cached=False,
            schema_name="statcan_delta.DeltaFileList",
            freshness="Updated each business day about 8:30 ET.",
            coverage=f"{len(files)} files, {files[-1].date} to {files[0].date}." if files else None,
            limits="Sizes, ETags and Last-Modified come from HEAD requests, only with "
            "include_sizes=True.",
        ),
    )
