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
   ~315 MB pipe-delimited UTF-8 each). Listing and dictionaries never
   download them; get_patent and search_patents fetch only the tables
   and number ranges they need, once, into store.py's Parquet cache.
6. Every trademark file link in the catalogue, and a few old patent
   text chunks, answer 404 with CIPO's HTML page (checked 2026-09-25).
"""

from __future__ import annotations

import asyncio
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

from maplestats_mcp.modules.ised.ip_horizons import constants, store
from maplestats_mcp.modules.ised.ip_horizons.schemas import (
    DictionaryField,
    IpHorizonsCatalogue,
    IpHorizonsDictionary,
    IpHorizonsFile,
    IpType,
    PatentClassification,
    PatentParty,
    PatentRecord,
    PatentSearchResult,
    PatentSummary,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
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
# HTTP/1.1: over HTTP/2 a 160 MB patent download broke off mid-stream
# (httpx.ReadError, 2026-09-25) where curl's HTTP/1.1 finished it.
_CIPO_CLIENT = new_client(timeout=60.0, http2=False, verify=_TLS)


def cipo_client() -> httpx.AsyncClient:
    """The client that trusts opic-cipo.ca's missing intermediate (see item 4)."""
    return _CIPO_CLIENT


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


_PARTY_TYPES = {
    "owner": "Owner",
    "inventor": "Inventor",
    "applicant": "Applicant",
    "agent": "Agent",
}
_IPC = re.compile(r"^([A-H])(\d{2})([A-Z])(?:\s*(\d{1,4})(?:/(\d{1,6}))?)?$")
_MAX_LIMIT = 100


async def _patent_files(table: str) -> list[IpHorizonsFile]:
    catalogue = await list_files("patent", table=table)
    files = [f for f in catalogue.files if not f.text_format]
    # The IPC release lists one unsplit ZIP (twice) next to its two split
    # parts holding the same rows; prefer the parts.
    if any(f.number_from for f in files):
        files = [f for f in files if f.number_from]
    return list({f.url: f for f in files}.values())


def _covering(files: list[IpHorizonsFile], number: int) -> IpHorizonsFile | None:
    for item in files:
        if item.number_from is None or item.number_from <= number <= (item.number_to or 0):
            return item
    return None


# Old records use -1 and -2 for unknown or not-applicable codes and
# dates, and "Unknown" for provinces (checked 2026-09-25: patent 1000000
# has filing date "-1"); return those as null.
_UNKNOWN = frozenset({"-1", "-2", "Unknown"})
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _clean(value: Any) -> Any:
    return None if value in _UNKNOWN else value


def _date(value: Any) -> str | None:
    return value if isinstance(value, str) and _ISO_DATE.match(value) else None


def _summary(row: dict[str, Any]) -> PatentSummary:
    row = {key: _clean(value) for key, value in row.items()}
    return PatentSummary(
        patent_number=row["patent_number"],
        title_en=row.get("application_patent_title_english"),
        title_fr=row.get("application_patent_title_french"),
        filing_date=_date(row.get("filing_date")),
        grant_date=_date(row.get("grant_date")),
        status_code=row.get("application_status_code"),
        application_type=row.get("application_type_code"),
        document_kind=row.get("document_kind_type"),
        filing_country=row.get("filing_country_code"),
        filing_language=row.get("language_of_filing_code"),
        pct_application_number=row.get("pct_application_number"),
        pct_publication_number=row.get("pct_publication_number"),
        parent_application_number=row.get("parent_application_number"),
    )


def ipc_symbol(row: dict[str, Any]) -> str:
    head = "".join(
        row.get(k) or "" for k in ("ipc_section_code", "ipc_class_code", "ipc_subclass_code")
    )
    group = (row.get("ipc_main_group_code") or "").lstrip("0") or "0"
    # IPC notation keeps the subgroup's leading zero ("H03K 19/01"); the
    # files store it that way (checked 2026-09-25: "00", "01", "0525").
    subgroup = row.get("ipc_subgroup_code") or "00"
    return f"{head} {group}/{subgroup}"


def _classification(row: dict[str, Any]) -> PatentClassification:
    sequence = row.get("ipc_classification_sequence_number") or ""
    return PatentClassification(
        sequence=int(sequence) if sequence.isdigit() else None,
        symbol=ipc_symbol(row),
        section=row.get("ipc_section"),
        class_title=row.get("ipc_class"),
        subclass_title=row.get("ipc_subclass"),
        group_title=row.get("ipc_group"),
        subgroup_title=row.get("ipc_subgroup"),
        version_date=row.get("ipc_version_date"),
    )


def _party(row: dict[str, Any]) -> PatentParty:
    row = {key: _clean(value) for key, value in row.items()}
    return PatentParty(
        party_type=row.get("interested_party_type"),
        name=row.get("party_name"),
        city=row.get("party_city"),
        province=row.get("party_province"),
        country=row.get("party_country"),
        owner_from=_date(row.get("owner_enable_date")),
        owner_to=_date(row.get("ownership_end_date")),
    )


def _query(sql: str, params: list[Any]) -> list[dict[str, Any]]:
    # Imported on first use: duckdb takes ~0.5 s to import.
    import duckdb

    with duckdb.connect() as connection:
        cursor = connection.execute(sql, params)
        names = [d[0] for d in cursor.description or []]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _parquet(paths: list[Path]) -> str:
    quoted = ", ".join("'" + str(p).replace("'", "''") + "'" for p in paths)
    return f"read_parquet([{quoted}])"


def _release(files: list[IpHorizonsFile]) -> date | None:
    dates = [f.release_date for f in files if f.release_date]
    return max(dates) if dates else None


async def get_patent(number: int, *, include_classifications: bool = False) -> PatentRecord:
    """One Canadian patent with its parties, and optionally its IPC classes."""
    context = "ised_ip_horizons:get_patent"
    if number < 1:
        raise InvalidInput(f"{context}: patent_number must be positive, got {number}.")
    main_file = _covering(await _patent_files("main"), number)
    party_file = _covering(await _patent_files("interested_party"), number)
    if main_file is None or party_file is None:
        raise NotFound(f"{context}: no IP Horizons file covers patent {number}.")
    used = [main_file, party_file]
    if include_classifications:
        ipc_file = _covering(await _patent_files("ipc_classification"), number)
        if ipc_file is not None:
            used.append(ipc_file)
    # Downloads start together; see search_patents.
    local = await asyncio.gather(*(store.local_table(f) for f in used))
    main_path, party_path = local[0], local[1]
    ipc_path: Path | None = local[2] if len(local) > 2 else None

    def run() -> tuple[list[dict[str, Any]], ...]:
        where = "WHERE patent_number = ?"
        main = _query(f"SELECT * FROM {_parquet([main_path])} {where}", [number])
        parties = _query(f"SELECT * FROM {_parquet([party_path])} {where}", [number])
        classes: list[dict[str, Any]] = []
        if ipc_path is not None:
            classes = _query(
                f"SELECT * FROM {_parquet([ipc_path])} {where} "
                "ORDER BY TRY_CAST(ipc_classification_sequence_number AS INTEGER)",
                [number],
            )
        return main, parties, classes

    main, parties, classes = await asyncio.to_thread(run)
    if not main:
        raise NotFound(f"{context}: patent {number} is not in the IP Horizons data.")
    return PatentRecord(
        patent=_summary(main[0]),
        parties=[_party(row) for row in parties],
        classifications=[_classification(row) for row in classes],
        classifications_included=ipc_path is not None,
        release_date=_release(used),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=main_file.url,
            cached=False,
            schema_name="ised_ip_horizons.PatentRecord",
            freshness="quarterly bulk releases",
            limits="Owners, status and classes are as of the release date, not today.",
        ),
    )


async def search_patents(
    *,
    party_name: str | None = None,
    party_type: str | None = None,
    ipc: str | None = None,
    title: str | None = None,
    filed_from: date | None = None,
    filed_to: date | None = None,
    limit: int = 25,
) -> PatentSearchResult:
    """Canadian patents matching party, IPC class, title and filing-date filters."""
    context = "ised_ip_horizons:search_patents"
    party_name = (party_name or "").strip() or None
    title = (title or "").strip() or None
    ipc_text = " ".join((ipc or "").upper().split()) or None
    if not any([party_name, ipc_text, title, filed_from, filed_to]):
        raise InvalidInput(f"{context}: give at least one of party_name, ipc, title or a date.")
    if limit < 1 or limit > _MAX_LIMIT:
        raise InvalidInput(f"{context}: limit must be between 1 and {_MAX_LIMIT}, got {limit}.")
    party_key = party_type.lower() if party_type else None
    if party_key and party_key not in _PARTY_TYPES:
        raise InvalidInput(f"{context}: party_type must be one of {sorted(_PARTY_TYPES)}.")
    if party_key and not party_name:
        raise InvalidInput(f"{context}: party_type needs a party_name.")
    ipc_match = _IPC.match(ipc_text) if ipc_text else None
    if ipc_text and ipc_match is None:
        raise InvalidInput(f"{context}: ipc must look like 'H01M', 'H01M 10' or 'H01M 10/0525'.")

    main_files = await _patent_files("main")
    party_files = await _patent_files("interested_party") if party_name else []
    ipc_files = await _patent_files("ipc_classification") if ipc_match else []
    used = [*main_files, *party_files, *ipc_files]
    # Start every needed download together, so a first call that times out
    # leaves all of them running rather than only the first.
    paths = dict(
        zip(
            [f.url for f in used],
            await asyncio.gather(*(store.local_table(f) for f in used)),
            strict=True,
        )
    )
    main_paths = [paths[f.url] for f in main_files]

    filters: dict[str, str] = {}
    where: list[str] = []
    params: list[Any] = []
    if title:
        filters["title"] = title
        where.append(
            "(application_patent_title_english ILIKE ? OR application_patent_title_french ILIKE ?)"
        )
        params += [f"%{title}%", f"%{title}%"]
    # Dates are ISO text in the files, so string comparison orders them;
    # the LIKE keeps "-1" (unknown) out of a filed_to range.
    if filed_from or filed_to:
        where.append("filing_date LIKE '____-__-__'")
    if filed_from:
        filters["filed_from"] = filed_from.isoformat()
        where.append("filing_date >= ?")
        params.append(filed_from.isoformat())
    if filed_to:
        filters["filed_to"] = filed_to.isoformat()
        where.append("filing_date <= ?")
        params.append(filed_to.isoformat())
    if party_name:
        party_paths = [paths[f.url] for f in party_files]
        filters["party_name"] = party_name
        clause = "party_name ILIKE ?"
        params.append(f"%{party_name}%")
        if party_key:
            filters["party_type"] = party_key
            clause += " AND interested_party_type = ?"
            params.append(_PARTY_TYPES[party_key])
        where.append(
            f"patent_number IN (SELECT patent_number FROM {_parquet(party_paths)} WHERE {clause})"
        )
    if ipc_match and ipc_text:
        ipc_paths = [paths[f.url] for f in ipc_files]
        filters["ipc"] = ipc_text
        section, klass, subclass, group, subgroup = ipc_match.groups()
        clause = "ipc_section_code = ? AND ipc_class_code = ? AND ipc_subclass_code = ?"
        params += [section, klass, subclass]
        if group:
            clause += " AND TRY_CAST(ipc_main_group_code AS INTEGER) = ?"
            params.append(int(group))
        if subgroup:
            clause += " AND ltrim(ipc_subgroup_code, '0') = ?"
            params.append(subgroup.lstrip("0"))
        where.append(
            f"patent_number IN (SELECT patent_number FROM {_parquet(ipc_paths)} WHERE {clause})"
        )

    base = f"FROM {_parquet(main_paths)} WHERE {' AND '.join(where)}"

    def run() -> tuple[int, list[dict[str, Any]]]:
        total = _query(f"SELECT count(*) AS n {base}", params)[0]["n"]
        rows = _query(
            f"SELECT * {base} ORDER BY filing_date DESC NULLS LAST, patent_number DESC "
            f"LIMIT {limit}",
            params,
        )
        return total, rows

    total, rows = await asyncio.to_thread(run)
    return PatentSearchResult(
        patents=[_summary(row) for row in rows],
        returned_count=len(rows),
        total_matched=total,
        filters=filters,
        release_date=_release(used),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.DATASET_PAGE_URL.format(id=constants.PACKAGE_IDS["patent"]),
            cached=False,
            schema_name="ised_ip_horizons.PatentSearchResult",
            freshness="quarterly bulk releases",
            coverage=f"newest {len(rows)} by filing date of {total} matches",
            limits="Name and title filters are case-insensitive substring matches.",
        ),
    )
