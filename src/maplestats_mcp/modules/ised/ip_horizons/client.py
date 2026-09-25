"""Client for CIPO's IP Horizons researcher datasets.

IP Horizons publishes Canada's full patent, industrial design and
trademark registers as quarterly bulk ZIP files, listed as resources of
three open.canada.ca CKAN packages (see constants.PACKAGE_IDS). Checked
live 2026-09-25:

1. Resource names and formats in CKAN are unreliable (a resource named
   "..._txt_format_..." links to a CSV ZIP; ZIPs are labelled CSV), so
   the table, number range and release date are read from the download
   URL itself, e.g. .../Patent_CSV_2024_10_11/PT_main_1_to_2000000_2024-10-11.zip.
2. Each package keeps older releases next to the newest, so a table can
   appear in two or three release folders.
3. The data dictionaries are ZIPs holding one XLSX workbook, one sheet
   per table, whose header row starts "Variable Name" (patents) or
   "Attribute Name" (industrial designs). Their spellings do not always
   match the CSV headers (e.g. "Filling Date" vs "Filing Date").
4. opic-cipo.ca sends only its leaf certificate, not the RapidSSL TLS
   RSA CA G1 intermediate (checked with openssl s_client). Browsers and
   Windows curl fetch the missing intermediate themselves; Python does
   not, so every request failed with CERTIFICATE_VERIFY_FAILED. The
   public intermediate is bundled next to this file and trusted on top
   of certifi's roots, for this host only. It expires 2027-11-02.
5. The data files are large (the patent main table is two ~77 MB ZIPs of
   ~315 MB pipe-delimited UTF-8 each), so this client lists and
   describes them rather than downloading them.
"""

from __future__ import annotations

import io
import re
import ssl
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import certifi
import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from maplestats_mcp.modules.ised.ip_horizons import constants
from maplestats_mcp.modules.ised.ip_horizons.schemas import (
    DictionaryField,
    IpHorizonsCatalogue,
    IpHorizonsDictionary,
    IpHorizonsFile,
    IpType,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get, is_retryable, new_client
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

_FOLDER = re.compile(r"/[A-Za-z]+_CSV_(\d{4})_(\d{2})_(\d{2})/")
_FILE = re.compile(
    r"/(?:PT|ID|TM)_(?P<table>[^/]+?)(?P<txt>_txt_format)?"
    r"(?:_(?P<lo>\d+)_to_(?P<hi>\d+))?(?:_(?P<day>\d{4}-\d{2}-\d{2}))?\.zip$",
    re.IGNORECASE,
)
_HEADER_CELLS = ("variable name", "attribute name")

_TLS = ssl.create_default_context(cafile=certifi.where())
_TLS.load_verify_locations(Path(__file__).with_name("rapidssl_tls_rsa_ca_g1.pem"))
_CIPO_CLIENT = new_client(timeout=60.0, verify=_TLS)


@retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def _get_cipo_file(url: str) -> bytes:
    response = await _CIPO_CLIENT.get(url)
    response.raise_for_status()
    return response.content


def parse_file_url(ip_type: IpType, url: str, name: str) -> IpHorizonsFile | None:
    """One catalogue entry from a download URL, or None for non-data links."""
    match = _FILE.search(url)
    if match is None or "IP_Horizon_Resources" in url:
        return None
    folder = _FOLDER.search(url)
    release: date | None = None
    if folder:
        release = date(int(folder[1]), int(folder[2]), int(folder[3]))
    elif match["day"]:
        release = date.fromisoformat(match["day"])
    return IpHorizonsFile(
        ip_type=ip_type,
        table=match["table"].lower(),
        text_format=match["txt"] is not None,
        number_from=int(match["lo"]) if match["lo"] else None,
        number_to=int(match["hi"]) if match["hi"] else None,
        release_date=release,
        name=name,
        url=url,
    )


def _latest_only(files: list[IpHorizonsFile]) -> list[IpHorizonsFile]:
    # Keep each table's newest release folder whole, so a table split by
    # number range keeps all its parts and an older unsplit copy drops out.
    newest: dict[tuple[str, str, bool], date] = {}
    for item in files:
        key = (item.ip_type, item.table, item.text_format)
        if item.release_date and item.release_date > newest.get(key, date.min):
            newest[key] = item.release_date
    return [
        item
        for item in files
        if item.release_date == newest.get((item.ip_type, item.table, item.text_format))
    ]


async def _package(ip_type: IpType) -> tuple[dict[str, Any], bool]:
    package_id = constants.PACKAGE_IDS[ip_type]

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(constants.CKAN_BASE_URL, params={"id": package_id})
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"ised_ip_horizons: open.canada.ca package {package_id} returned "
                f"HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "ised_ip_horizons: open.canada.ca did not respond in time. Try again shortly."
            ) from exc

    payload, was_cached = await cached_fetch(
        f"ised-ip-horizons:package:{package_id}", constants.CATALOGUE_TTL_SECONDS, fetch
    )
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise UpstreamError(f"ised_ip_horizons: package {package_id} had no 'result'.")
    return result, was_cached


async def list_files(
    ip_type: IpType, *, table: str | None = None, latest_only: bool = True
) -> IpHorizonsCatalogue:
    """The bulk data files of one IP Horizons dataset."""
    if ip_type not in constants.PACKAGE_IDS:
        raise InvalidInput(
            f"ised_ip_horizons:list_files: ip_type must be one of "
            f"{sorted(constants.PACKAGE_IDS)}, got {ip_type!r}."
        )
    package, was_cached = await _package(ip_type)
    parsed = [
        parse_file_url(ip_type, str(res.get("url") or ""), str(res.get("name") or ""))
        for res in list_or_empty(package, "resources")
    ]
    files = [item for item in parsed if item is not None]
    all_tables = sorted({item.table for item in files})
    if latest_only:
        files = _latest_only(files)
    if table:
        wanted = table.strip().lower()
        if wanted not in all_tables:
            raise InvalidInput(
                f"ised_ip_horizons:list_files: no {ip_type} table {table!r}; "
                f"tables are {all_tables}."
            )
        files = [item for item in files if item.table == wanted]
    files.sort(
        key=lambda f: (f.table, f.text_format, f.number_from or 0, f.release_date or date.min)
    )
    release_dates = [f.release_date for f in files if f.release_date]
    return IpHorizonsCatalogue(
        files=files,
        returned_count=len(files),
        tables=all_tables,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.DATASET_PAGE_URL.format(id=constants.PACKAGE_IDS[ip_type]),
            cached=was_cached,
            schema_name="ised_ip_horizons.IpHorizonsCatalogue",
            freshness="quarterly bulk releases",
            coverage=(
                f"newest release folder per table (latest {max(release_dates)})"
                if latest_only and release_dates
                else "every release folder the package lists"
            ),
            limits="Lists download links only; files are ZIPs of pipe-delimited UTF-8 CSV.",
        ),
    )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def parse_dictionary(workbook_bytes: bytes) -> tuple[list[DictionaryField], list[str]]:
    """Fields from every table sheet, plus the overview sheet's notes."""
    # Imported on first use, like duckdb in statcan/pumf: only this tool needs it.
    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(workbook_bytes), read_only=True, data_only=True)
    fields: list[DictionaryField] = []
    notes: list[str] = []
    for index, sheet in enumerate(workbook.worksheets):
        rows = [row for row in sheet.iter_rows(values_only=True) if any(c is not None for c in row)]
        header_at = next(
            (i for i, row in enumerate(rows) if (_text(row[0]) or "").lower() in _HEADER_CELLS),
            None,
        )
        if header_at is None:
            # The first sheet is prose: coverage period, delimiter, encoding.
            if index == 0:
                notes = [text for row in rows if (text := _text(row[0])) and len(text) > 40]
            continue
        table = re.sub(r"^(pt|id)_", "", "_".join(sheet.title.strip().lower().split()))
        for row in rows[header_at + 1 :]:
            cells = [*row, *([None] * 7)]
            name_en = _text(cells[0])
            if not name_en:
                continue
            fields.append(
                DictionaryField(
                    table=table,
                    name_en=name_en,
                    name_fr=_text(cells[1]),
                    type_en=_text(cells[3]),
                    type_fr=_text(cells[4]),
                    description_en=_text(cells[5]),
                    description_fr=_text(cells[6]),
                )
            )
    return fields, notes


async def get_dictionary(ip_type: IpType, *, table: str | None = None) -> IpHorizonsDictionary:
    """The data dictionary of one IP Horizons dataset."""
    url = constants.DICTIONARY_URLS.get(ip_type)
    if url is None:
        raise InvalidInput(
            f"ised_ip_horizons:get_dictionary: CIPO publishes dictionaries only for "
            f"{sorted(constants.DICTIONARY_URLS)}, got {ip_type!r}."
        )

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            body = await _get_cipo_file(url)
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"ised_ip_horizons: {url} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"ised_ip_horizons: {url} did not respond in time.") from exc
        if len(body) > constants.MAX_DICTIONARY_BYTES:
            raise UpstreamError(f"ised_ip_horizons: {url} is larger than expected.")
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                member = next(n for n in archive.namelist() if n.lower().endswith(".xlsx"))
                return parse_dictionary(archive.read(member))
        except (zipfile.BadZipFile, StopIteration) as exc:
            # opic-cipo.ca serves its HTML 404 page for a missing file.
            raise UpstreamError(f"ised_ip_horizons: {url} is not a dictionary ZIP.") from exc

    (fields, notes), was_cached = await cached_fetch(
        f"ised-ip-horizons:dictionary:{ip_type}", constants.DICTIONARY_TTL_SECONDS, fetch
    )
    tables = sorted({f.table for f in fields})
    if table:
        wanted = table.strip().lower()
        if wanted not in tables:
            raise InvalidInput(
                f"ised_ip_horizons:get_dictionary: no {ip_type} table {table!r}; "
                f"tables are {tables}."
            )
        fields = [f for f in fields if f.table == wanted]
    return IpHorizonsDictionary(
        ip_type=ip_type,
        fields=fields,
        tables=tables,
        notes=notes,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="ised_ip_horizons.IpHorizonsDictionary",
        ),
    )
