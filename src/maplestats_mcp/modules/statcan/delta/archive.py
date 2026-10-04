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

Reading deep into the CSV (confirmed live 2026-10-03 on 20261001): the
deflate stream must be inflated from its start once, at about 5 MB/s, so a
table near the end of the 3.87 GB day takes several calls. Each scan saves
verified resume points (`scan_index.py`, `shared/zip_stream.py`), so the
next call continues where the last stopped and any later read of the same
file version starts next to its table.
"""

from __future__ import annotations

import asyncio
import html
import io
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as date_cls
from email.utils import parsedate_to_datetime
from xml.etree.ElementTree import Element

import httpx
from defusedxml import ElementTree
from tenacity import retry, retry_if_exception, stop_after_attempt

from maplestats_mcp import config
from maplestats_mcp.modules.statcan.delta import constants, scan_index
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
from maplestats_mcp.modules.statcan.lang import say, use_lang
from maplestats_mcp.shared import remote_zip
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import (
    get_raw,
    is_retryable,
    new_client,
    request_headers,
    wait_honouring_retry_after,
)
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
SCAN_CHUNK_BYTES = 16 * 1024 * 1024
# Measured 2026-10-03 against 20261001.zip from a home connection: one
# range request runs at about 2.5 MB/s (8 MB in 3.1 s, 32 MB in 9.6 to 15 s)
# whatever its size, two in flight reach 5 MB/s and four 7 MB/s. www150
# asks automated clients for 2 s between requests, so requests *start* at
# least 2 s apart and at most two overlap: with 16 MB ranges that is about
# one request every 3 s, for roughly twice the single-stream rate.
SCAN_PREFETCH = 2
SCAN_REQUEST_INTERVAL_SECONDS = 2.0
# One verified resume point per range (each 16 MB range is due one); 240
# points of 32 KiB windows for the 3.87 GB day, about 2 MB saved.
SCAN_POINT_SPACING = 8 * 1024 * 1024
# The compressed and time ceilings come from config (MAPLE_DELTA_MAX_SCAN_MB,
# default 400; MAPLE_DELTA_MAX_SCAN_SECONDS, default 75, under the 120 s
# tool timeout). The inflated ceiling only stops a deflate bomb: the real
# CSV inflates about 7.5 times (3.87 GB to 29 GB on 20261001).
SCAN_MAX_INFLATE_RATIO = 16
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
_WEEKDAYS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def _weekday(day: date_cls) -> str:
    return say(_WEEKDAYS[day.weekday()], _WEEKDAYS_FR[day.weekday()])


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
        raise InvalidInput(
            say(
                f"Expected a YYYY-MM-DD date, got {date!r}.",
                f"Date attendue au format AAAA-MM-JJ, reçu {date!r}.",
            )
        ) from exc
    return parsed, ARCHIVE_URL.format(date=parsed.strftime("%Y%m%d"))


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(4),
    wait=wait_honouring_retry_after,
    reraise=True,
)
async def _head_once(url: str) -> httpx.Response:
    await _LIMITER.acquire()
    response = await _client.head(url, headers=request_headers(url, None))
    if response.status_code != 404:
        response.raise_for_status()
    return response


async def _head(url: str) -> httpx.Response:
    try:
        return await _head_once(url)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise UpstreamError(
            say(f"{url} returned HTTP {status}.", f"{url} a renvoyé HTTP {status}.")
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            say(f"{url} could not be reached.", f"{url} est injoignable.")
        ) from exc


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
            say(
                f"{url} does not hold the expected codeSet.xml, {stamp}.xml and {stamp}.csv "
                f"(members: {names}).",
                f"{url} ne contient pas les fichiers attendus codeSet.xml, {stamp}.xml et "
                f"{stamp}.csv (membres : {names}).",
            )
        ) from exc


async def _missing_message(parsed: date_cls) -> str:
    """Why a date has no file: weekend, holiday, past retention or not yet published."""
    status = await _date_status(parsed, None)
    return say(
        f"No Delta File exists for {parsed.isoformat()}: {status}. "
        "Use statcan_delta_list_files for the dates that are available.",
        f"Aucun fichier delta n'existe pour le {parsed.isoformat()} : {status}. "
        "Utilisez statcan_delta_list_files pour les dates disponibles.",
    )


async def _page_dates() -> list[str]:
    try:
        response = await get_raw(PAGE_URL)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise UpstreamError(
            say(f"{PAGE_URL} returned HTTP {status}.", f"{PAGE_URL} a renvoyé HTTP {status}.")
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            say(f"{PAGE_URL} could not be reached.", f"{PAGE_URL} est injoignable.")
        ) from exc
    dates = sorted(set(_PAGE_FILE.findall(response.text)))
    if not dates:
        raise UpstreamError(
            say(
                f"{PAGE_URL} lists no Delta File links; the page may have changed.",
                f"{PAGE_URL} ne liste aucun lien de fichier delta ; la page a peut-être changé.",
            )
        )
    return dates


async def _date_status(parsed: date_cls, listed: list[str] | None) -> str:
    stamps = listed if listed is not None else await _page_dates()
    stamp = parsed.strftime("%Y%m%d")
    if stamp in stamps:
        return say("available", "disponible")
    oldest, newest = stamps[0], stamps[-1]
    if stamp < oldest:
        return say(
            f"past retention (the oldest file kept is {_iso(oldest)}; about "
            f"{RETENTION_BUSINESS_DAYS} business days are available)",
            f"hors de la période de conservation (le plus ancien fichier gardé est du {_iso(oldest)} ; "
            f"environ {RETENTION_BUSINESS_DAYS} jours ouvrables sont disponibles)",
        )
    if stamp > newest:
        return say(
            f"not yet published (the newest file is {_iso(newest)}; released about 8:30 ET)",
            f"pas encore publié (le fichier le plus récent est du {_iso(newest)} ; diffusion vers "
            "8 h 30, HE)",
        )
    if parsed.weekday() >= 5:
        return say(
            "no release that day (a weekend)", "aucune diffusion ce jour-là (fin de semaine)"
        )
    return say(
        "no release that day (a holiday or a day without a release)",
        "aucune diffusion ce jour-là (jour férié ou jour sans diffusion)",
    )


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
            raise UpstreamError(
                say(
                    f"{archive.metadata.name} is not valid XML: {exc}.",
                    f"{archive.metadata.name} n'est pas du XML valide : {exc}.",
                )
            ) from exc
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
    use_lang(lang)
    if max_tables < 1:
        raise InvalidInput(
            say("max_tables must be at least 1.", "max_tables doit être d'au moins 1.")
        )
    if detail and product_id is None:
        raise InvalidInput(
            say(
                "detail=True needs a product_id (members and corrections are long).",
                "detail=True exige un product_id (les membres et les corrections sont longs).",
            )
        )
    archive = await _open_archive(date)
    cubes, cached = await _read_cubes(archive, lang=lang, detail_for=product_id if detail else None)
    chosen = cubes
    if product_id is not None:
        chosen = [c for c in cubes if c.product_id == product_id]
        if not chosen:
            raise NotFound(
                say(
                    f"Table {product_id} was not released in the Delta File of {archive.date}; "
                    "call statcan_delta_list_tables without product_id for the tables that were.",
                    f"Le tableau {product_id} ne figure pas dans le fichier delta du {archive.date} ; "
                    "appelez statcan_delta_list_tables sans product_id pour la liste des tableaux "
                    "diffusés.",
                )
            )
    if query:
        needle = query.casefold()
        chosen = [
            c for c in chosen if needle in f"{c.title_en or ''} {c.title_fr or ''}".casefold()
        ]
    shown = chosen[:max_tables]
    notes = [
        say(
            "A table appears when its data or metadata changed that day; no rows are ever deleted, "
            "and a correction arrives in the next day's file.",
            "Un tableau figure dans le fichier quand ses données ou ses métadonnées ont changé ce "
            "jour-là ; aucune ligne n'est jamais supprimée et une correction arrive dans le "
            "fichier du lendemain.",
        ),
        say(
            "Files are published on business days about 8:30 ET. Read one table's rows with "
            "statcan_delta_read_table.",
            "Les fichiers sont publiés les jours ouvrables vers 8 h 30, HE. Lisez les lignes "
            "d'un tableau avec statcan_delta_read_table.",
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
            freshness=say(
                "One file per business day, about 8:30 ET; about 47 business days kept.",
                "Un fichier par jour ouvrable, vers 8 h 30, HE ; environ 47 jours ouvrables "
                "conservés.",
            ),
            coverage=say(
                f"{len(cubes)} tables released on {archive.date}.",
                f"{len(cubes)} tableaux diffusés le {archive.date}.",
            ),
            limits=say(
                f"Read by range requests from the {archive.size:,}-byte zip; "
                "only the metadata member was fetched.",
                f"Lu par requêtes de plage dans le ZIP de {archive.size:,} octets ; seul le "
                "fichier de métadonnées a été récupéré.",
            ),
            lang=lang,
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
            raise UpstreamError(
                say(
                    f"{archive.codeset.name} is not valid XML: {exc}.",
                    f"{archive.codeset.name} n'est pas du XML valide : {exc}.",
                )
            ) from exc

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


def _size(count: int) -> str:
    return f"{count / 1024**2:,.0f} MB" if count >= 10 * 1024**2 else f"{count:,} bytes"


def _column_index(header: str, member: str) -> dict[str, int]:
    names = header.split(",")
    index = {name: position for position, name in enumerate(names)}
    missing = [name for name in _EXPECTED_COLUMNS if name not in index]
    if missing:
        raise UpstreamError(
            say(
                f"{member} lacks the columns {', '.join(missing)}; "
                "the Delta CSV layout may have changed.",
                f"Il manque à {member} les colonnes {', '.join(missing)} ; la structure du CSV "
                "delta a peut-être changé.",
            )
        )
    return index


def _ceiling_message(
    archive: Archive,
    product_id: int,
    stream: MemberStream,
    exc: ScanLimitExceeded,
    started_at: int,
    reached: int,
    max_scan_bytes: int,
    max_seconds: float,
) -> str:
    """How far a stopped scan got, and that calling again continues from there."""
    total = archive.data.compressed_size
    share = stream.offset / total if total else 0.0
    saved = (
        say(
            "Progress is saved: calling statcan_delta_read_table again with the same arguments "
            "continues from there, about as far again per call",
            "La progression est enregistrée : rappeler statcan_delta_read_table avec les mêmes "
            "arguments reprend à cet endroit, à peu près aussi loin à chaque appel",
        )
        if stream.points
        else say(
            "No resume point was saved (the scan was too short), so calling again repeats it",
            "Aucun point de reprise n'a été enregistré (lecture trop courte) ; un nouvel appel "
            "la recommence",
        )
    )
    origin = (
        say(
            f" from byte {started_at:,} (a saved resume point)",
            f" à partir de l'octet {started_at:,} (un point de reprise enregistré)",
        )
        if started_at
        else ""
    )
    return say(
        f"Table {product_id} was not reached in the Delta File of {archive.date} within one "
        f"call's ceiling ({_size(max_scan_bytes)} or {max_seconds:.0f} s): "
        f"{_size(exc.scanned)} of the {_size(total)} compressed CSV were "
        f"read{origin}, up to productId {reached} ({share:.0%} of the file). {saved}. Faster routes: wds_get_changed_series_data "
        "(the series that changed) or wds_get_full_table_download (the whole table as CSV), or "
        f"download {archive.url} yourself.",
        f"Le tableau {product_id} n'a pas été atteint dans le fichier delta du {archive.date} "
        f"dans la limite d'un appel ({_size(max_scan_bytes)} ou {max_seconds:.0f} s) : "
        f"{_size(exc.scanned)} des {_size(total)} du CSV compressé ont été lus{origin}, "
        f"jusqu'au productId {reached} ({share:.0%} du fichier). {saved}. Solutions plus "
        "rapides : wds_get_changed_series_data (les séries modifiées) ou "
        "wds_get_full_table_download (tout le tableau en CSV), ou téléchargez vous-même "
        f"{archive.url}.",
    )


def _leading_id(line: bytes) -> int:
    head = line.split(b",", 1)[0]
    if not head.isdigit():
        raise UpstreamError(
            say(
                f"A Delta CSV line does not start with a productId: {line[:60]!r}.",
                f"Une ligne du CSV delta ne commence pas par un productId : {line[:60]!r}.",
            )
        )
    return int(head)


async def read_table(
    date: str,
    product_id: int,
    *,
    vector_ids: list[int] | None = None,
    max_rows: int = 1000,
    lang: str = "en",
) -> DeltaTableData:
    use_lang(lang)
    if not 1 <= max_rows <= MAX_ROWS_CAP:
        raise InvalidInput(
            say(
                f"max_rows must be between 1 and {MAX_ROWS_CAP:,}.",
                f"max_rows doit être entre 1 et {MAX_ROWS_CAP:,}.",
            )
        )
    if vector_ids is not None and len(vector_ids) > MAX_VECTOR_FILTER:
        raise InvalidInput(
            say(
                f"vector_ids takes at most {MAX_VECTOR_FILTER:,} ids.",
                f"vector_ids accepte au plus {MAX_VECTOR_FILTER:,} identifiants.",
            )
        )
    called = time.monotonic()
    wanted = set(vector_ids) if vector_ids else None
    archive = await _open_archive(date)

    # The metadata XML says whether the table was released at all, which
    # saves scanning a CSV (up to gigabytes) for a table that is not in it.
    cubes, _ = await _read_cubes(archive, lang=lang)
    cube = next((c for c in cubes if c.product_id == product_id), None)
    if cube is None:
        raise NotFound(
            say(
                f"Table {product_id} was not released in the Delta File of {archive.date} "
                f"({len(cubes)} tables were); call statcan_delta_list_tables for that list, or "
                "wds_get_full_table_download for the table's current data.",
                f"Le tableau {product_id} ne figure pas dans le fichier delta du {archive.date} "
                f"({len(cubes)} tableaux y figurent) ; appelez statcan_delta_list_tables pour "
                "cette liste, ou wds_get_full_table_download pour les données actuelles du "
                "tableau.",
            )
        )
    codes = await _codeset(archive)

    saved = scan_index.load(archive.date, archive.etag)
    resume = scan_index.best_start(saved, product_id)
    max_scan_bytes = config.get_delta_max_scan_bytes()
    max_seconds = config.get_delta_max_scan_seconds()
    stream = MemberStream(
        archive.url,
        archive.data,
        chunk_bytes=SCAN_CHUNK_BYTES,
        max_scan_bytes=max_scan_bytes,
        max_inflated_bytes=SCAN_MAX_INFLATE_RATIO * max_scan_bytes,
        # The ceiling counts from the call's start: opening a big archive
        # (HEAD, directory, metadata XML) took up to 23 s on 2026-10-03.
        max_seconds=max(1.0, max_seconds - (time.monotonic() - called)),
        before_fetch=_LIMITER.acquire,
        start=resume.point if resume else None,
        point_spacing=SCAN_POINT_SPACING,
        prefetch=SCAN_PREFETCH,
        min_request_interval=SCAN_REQUEST_INTERVAL_SECONDS,
    )
    started_at = stream.offset
    rows: list[DeltaRow] = []
    index: dict[str, int] | None = None
    header_line: str | None = None
    if resume is not None and saved.header:
        index = _column_index(saved.header, archive.data.name)
    truncated = False
    done = False
    in_block = False
    block_complete = True
    reached = resume.product_id if resume else 0
    blocks = stream.blocks()
    try:
        async for block in blocks:
            if index is None:
                head, _, block = block.partition(b"\n")
                header_line = head.rstrip(b"\r").decode("ascii", "replace").lstrip(_BOM)
                index = _column_index(header_line, archive.data.name)
                if not block:
                    continue
            # Sorted ascending by productId in contiguous blocks (confirmed
            # on 20260929, 20261001 and 20261002), so a run of lines is
            # skipped from its first and last line and only the runs that
            # touch the table are split into lines.
            first = _leading_id(block[: block.find(b"\n")] if b"\n" in block else block)
            last = _leading_id(block[block.rfind(b"\n") + 1 :])
            if first > last:
                raise UpstreamError(
                    say(
                        f"{archive.data.name} is not sorted by productId.",
                        f"{archive.data.name} n'est pas trié par productId.",
                    )
                )
            reached = last
            if last < product_id:
                continue
            if first > product_id:
                break
            for raw_line in block.split(b"\n"):
                line = raw_line.rstrip(b"\r")
                current = _leading_id(line)
                if current < product_id:
                    continue
                if current > product_id:
                    done = True
                    break
                in_block = True
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
        if not in_block:
            raise UpstreamError(
                _ceiling_message(
                    archive,
                    product_id,
                    stream,
                    exc,
                    started_at,
                    reached,
                    max_scan_bytes,
                    max_seconds,
                )
            ) from exc
        block_complete = False
    finally:
        await blocks.aclose()
        # Points are kept even when the ceiling stopped the scan: that is
        # what lets the next call continue from here.
        scan_index.record(saved, header_line, stream.points)

    notes = [
        say(
            "Values are raw: the scalar factor is not applied (see legend.scalar_factors).",
            "Les valeurs sont brutes : le facteur d'échelle n'est pas appliqué (voir "
            "legend.scalar_factors).",
        ),
        say(
            "Deltas carry changed data points only, with no deletions; a correction arrives in the "
            "next business day's file.",
            "Les fichiers delta ne contiennent que les points de données modifiés, sans "
            "suppression ; une correction arrive dans le fichier du jour ouvrable suivant.",
        ),
    ]
    if not rows and not truncated:
        notes.append(
            say(
                "No CSV rows for this table"
                + (" matched vector_ids." if wanted else " (a metadata-only change)."),
                "Aucune ligne du CSV pour ce tableau"
                + (
                    " ne correspond à vector_ids."
                    if wanted
                    else " (changement des métadonnées seulement)."
                ),
            )
        )
    if truncated:
        notes.append(
            say(
                f"Stopped at max_rows={max_rows:,}; filter with vector_ids or raise max_rows.",
                f"Arrêt à max_rows={max_rows:,} ; filtrez avec vector_ids ou augmentez max_rows.",
            )
        )
    if not block_complete:
        notes.append(
            say(
                f"Incomplete: the scan ceiling ({_size(max_scan_bytes)} or "
                f"{max_seconds:.0f} s) stopped inside this table's rows, so only its first rows were "
                "read and matching rows further on are missing. For the whole table use "
                "wds_get_full_table_download; for a few series, wds_get_changed_series_data.",
                f"Incomplet : la limite de lecture ({_size(max_scan_bytes)} ou "
                f"{max_seconds:.0f} s) a été atteinte dans les lignes de ce tableau ; seules ses "
                "premières lignes ont été lues et les lignes suivantes manquent. Pour tout le "
                "tableau, utilisez wds_get_full_table_download ; pour quelques séries, "
                "wds_get_changed_series_data.",
            )
        )
    if resume is not None:
        notes.append(
            say(
                f"Started at compressed byte {started_at:,} (productId {resume.product_id}), a resume "
                "point saved by an earlier scan of this file, instead of at byte 0.",
                f"Lecture commencée à l'octet compressé {started_at:,} (productId "
                f"{resume.product_id}), un point de reprise enregistré par une lecture précédente "
                "de ce fichier, plutôt qu'à l'octet 0.",
            )
        )
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
        scan_started_at_byte=started_at,
        block_complete=block_complete,
        rows=rows,
        legend=_legend(codes, rows, lang),
        notes=notes,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=archive.url,
            cached=False,
            schema_name="statcan_delta.DeltaTableData",
            as_of=_as_of(archive.last_modified),
            freshness=say(
                "One file per business day, about 8:30 ET.",
                "Un fichier par jour ouvrable, vers 8 h 30, HE.",
            ),
            coverage=say(
                f"Table {product_id} in the release of {archive.date}.",
                f"Tableau {product_id} dans la diffusion du {archive.date}.",
            ),
            limits=say(
                f"{stream.scanned:,} of {archive.data.compressed_size:,} compressed CSV bytes "
                f"read from byte {started_at:,}; rows capped at {max_rows:,}.",
                f"{stream.scanned:,} des {archive.data.compressed_size:,} octets compressés du "
                f"CSV lus à partir de l'octet {started_at:,} ; lignes limitées à {max_rows:,}.",
            ),
            lang=lang,
        ),
    )


async def _file_headers(stamp: str) -> DeltaFileEntry:
    url = ARCHIVE_URL.format(date=stamp)
    parsed = date_cls(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))
    entry = DeltaFileEntry(date=parsed.isoformat(), weekday=_weekday(parsed), url=url)
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
    use_lang(lang)
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
                    weekday=_weekday(parsed),
                    url=ARCHIVE_URL.format(date=stamp),
                )
            )
    files.sort(key=lambda f: f.date, reverse=True)
    notes = [
        say(
            f"The page lists {len(stamps)} files, about {RETENTION_BUSINESS_DAYS} business days; "
            "older files are removed (the user guide's '5 releases' is out of date).",
            f"La page liste {len(stamps)} fichiers, soit environ {RETENTION_BUSINESS_DAYS} jours "
            "ouvrables ; les fichiers plus anciens sont retirés (les « 5 diffusions » du guide de "
            "l'utilisateur ne sont plus à jour).",
        ),
        say(
            "A file appears on business days about 8:30 ET. Holidays (for example 2026-09-30) have "
            "none. Corrections arrive in the next day's file; nothing is deleted.",
            "Un fichier paraît les jours ouvrables vers 8 h 30, HE. Les jours fériés (par exemple "
            "le 2026-09-30) n'en ont pas. Les corrections arrivent dans le fichier du lendemain ; "
            "rien n'est supprimé.",
        ),
        say(
            "Each zip holds codeSet.xml, YYYYMMDD.xml (cube metadata) and YYYYMMDD.csv (data); the "
            f"metadata schema is at {SCHEMA_URL}.",
            "Chaque ZIP contient codeSet.xml, AAAAMMJJ.xml (métadonnées des tableaux) et "
            f"AAAAMMJJ.csv (données) ; le schéma des métadonnées est à {SCHEMA_URL}.",
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
            freshness=say(
                "Updated each business day about 8:30 ET.",
                "Mis à jour chaque jour ouvrable vers 8 h 30, HE.",
            ),
            coverage=say(
                f"{len(files)} files, {files[-1].date} to {files[0].date}.",
                f"{len(files)} fichiers, du {files[-1].date} au {files[0].date}.",
            )
            if files
            else None,
            limits=say(
                "Sizes, ETags and Last-Modified come from HEAD requests, only with "
                "include_sizes=True.",
                "Les tailles, ETag et Last-Modified viennent de requêtes HEAD, seulement avec "
                "include_sizes=True.",
            ),
            lang=lang,
        ),
    )
