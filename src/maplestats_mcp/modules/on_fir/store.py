"""Local Parquet copies of the FIR's yearly CSV files, fetched on first use.

Each year is one ZIP (`fir_data_<year>.zip`) holding one CSV of every
data point every municipality reported, one row per schedule, line and
column. Read from fir_data_2023.zip (posted 2025-04) and the 2005 and 2025
files: 18 columns, the same header from 2000 to 2025, UTF-8, LF line ends,
quoted strings, AMOUNT right-padded with spaces to 80 characters
("      3110984"), MUNID with a leading space below 10000 (" 6005"). The
2023 file is 9.3 MB zipped, 166 MB of CSV (571,761 rows) and 3.3 MB as
Parquet; DuckDB read and converted it in about 1.5 s.

One 2023 note (Thunder Bay, schedule 83) holds a bare double quote inside
a quoted field, so DuckDB's strict parser refuses the file; the reader
sets the dialect explicitly with `strict_mode=false`, which reads that row
whole (Python's csv module splits it into 20 fields).

The file name carries the year's "last updated" date from the index page,
so a re-posted year is a new file and the old one is removed. A download
that outlives the tool timeout keeps running (asyncio.shield), so a retry
finds it finished, as in ised/ip_horizons/store.py.
"""

from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

from maplestats_mcp import config
from maplestats_mcp.modules.on_fir import constants
from maplestats_mcp.shared import duck
from maplestats_mcp.shared.breaker import CircuitOpen
from maplestats_mcp.shared.capped_io import FileTooLarge, check_size, copy_capped
from maplestats_mcp.shared.errors import NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import run_in_pool
from maplestats_mcp.shared.fr_typography import call_error
from maplestats_mcp.shared.http import counted_once, new_client
from maplestats_mcp.shared.rate_limiter import get_limiter

# The largest year so far is 11.4 MB zipped and about 170 MB of CSV.
MAX_ZIP_BYTES = 80 * 1024 * 1024
MAX_CSV_BYTES = 1024 * 1024 * 1024
_DOWNLOAD_ATTEMPTS = 3
_RETRY_WAIT_SECONDS = 5.0

_client = new_client(timeout=120.0, follow_redirects=False)
_downloads: dict[str, asyncio.Task[Path]] = {}

_READER = (
    "read_csv('{path}', header=true, all_varchar=true, delim=',', quote='\"', "
    "escape='\"', strict_mode=false)"
)

# SLC is "slc.<schedule>.L<line>.C<section>.<column>"; the column part can be
# alphanumeric ("slc.53X.L1070.C01.0A", 7,229 rows in 2023).
_CONVERT = """
COPY (
    SELECT
        TRY_CAST(MARSYEAR AS INTEGER) AS year,
        trim(MUNID) AS munid,
        trim(MUNICIPALITY_DESC) AS municipality,
        NULLIF(trim(ASSESSMENT_CODE), '') AS assessment_code,
        NULLIF(trim(MSO_NUMBER), '') AS mso,
        NULLIF(trim(SGC_CODE), '') AS sgc_code,
        NULLIF(trim(UT_NUMBER), '') AS ut_number,
        NULLIF(trim(MTYPE_CODE), '') AS mtype,
        trim(TIER_CODE) AS tier,
        NULLIF(trim(LAST_UPDATE_DATE), '') AS last_update,
        split_part(SLC, '.', 2) AS schedule,
        trim(SCHEDULE_DESC) AS schedule_desc,
        NULLIF(trim(SUB_SCHEDULE_DESC), '') AS sub_schedule,
        substr(split_part(SLC, '.', 3), 2) AS line,
        NULLIF(trim(SCHEDULE_LINE_DESC), '') AS line_desc,
        substr(SLC, length(SLC) - 4) AS col,
        NULLIF(trim(SCHEDULE_COLUMN_DESC), '') AS column_desc,
        trim(SLC) AS slc,
        NULLIF(trim(DATATYPE_DESC), '') AS datatype,
        TRY_CAST(NULLIF(trim(AMOUNT), '') AS DOUBLE) AS amount,
        NULLIF(VALUE_TEXT, '') AS value_text
    FROM {reader}
    WHERE SLC IS NOT NULL
) TO '{sink}' (FORMAT parquet, COMPRESSION zstd)
"""


def _sql_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def convert_csv(csv_path: Path, target: Path) -> None:
    """Write one year's FIR CSV as Parquet with clean, typed columns."""
    part = target.with_suffix(".parquet.part")
    reader = _READER.format(path=_sql_path(csv_path))
    with duck.connect() as connection:
        # Measured on the 166 MB 2023 CSV (2026-10-26): DuckDB's default threads
        # peaked at +554 MB of process memory, two threads at +301 MB for 0.6 s
        # more. MAPLE_DUCKDB_MEMORY_LIMIT=256MB brings it to about +220 MB.
        connection.execute("SET threads=2")
        connection.execute(_CONVERT.format(reader=reader, sink=_sql_path(part)))
    part.replace(target)


def _enforce_cache_cap(root: Path, keep: Path) -> None:
    files = sorted(root.glob("*.parquet"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    for path in files:
        if total <= config.get_on_fir_cache_max_bytes():
            break
        if path != keep:
            total -= path.stat().st_size
            path.unlink(missing_ok=True)


async def _fetch_zip(url: str, zip_path: Path) -> None:
    await get_limiter(
        constants.RATE_LIMIT_SOURCE, constants.RATE_LIMIT_PER_SECOND, constants.RATE_LIMIT_CAPACITY
    ).acquire()
    async with _client.stream("GET", url) as response:
        response.raise_for_status()
        # A missing year answers with the site's HTML page, not a ZIP.
        if "html" in response.headers.get("content-type", ""):
            raise call_error(
                NotFound,
                f"on_fir: {url} is not published.",
                f"on_fir : {url} n'est pas publié.",
            )
        check_size(int(response.headers.get("content-length") or 0), MAX_ZIP_BYTES, url)
        written = 0
        with zip_path.open("wb") as handle:
            async for chunk in response.aiter_bytes(1 << 20):
                written += len(chunk)
                check_size(written, MAX_ZIP_BYTES, url)
                handle.write(chunk)


@counted_once
async def _download(url: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    zip_path = target.with_suffix(".zip.part")
    for attempt in range(1, _DOWNLOAD_ATTEMPTS + 1):
        try:
            await _fetch_zip(url, zip_path)
            break
        except (NotFound, FileTooLarge, CircuitOpen):
            zip_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            zip_path.unlink(missing_ok=True)
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 404:
                raise call_error(
                    NotFound,
                    f"on_fir: {url} is not published.",
                    f"on_fir : {url} n'est pas publié.",
                ) from exc
            if attempt == _DOWNLOAD_ATTEMPTS:
                raise call_error(
                    UpstreamUnavailable,
                    f"on_fir: download of {url} failed: {exc!r}",
                    f"on_fir : le téléchargement de {url} a échoué : {exc!r}",
                ) from exc
            await asyncio.sleep(_RETRY_WAIT_SECONDS * attempt)

    def extract_and_convert() -> None:
        csv_path = target.with_suffix(".csv.part")
        try:
            with zipfile.ZipFile(zip_path) as archive:
                member = next((n for n in archive.namelist() if n.lower().endswith(".csv")), None)
                if member is None:
                    raise call_error(
                        UpstreamError,
                        f"on_fir: {url} has no CSV file inside.",
                        f"on_fir : {url} ne contient aucun fichier CSV.",
                    )
                with archive.open(member) as source, csv_path.open("wb") as sink:
                    copy_capped(source, sink, MAX_CSV_BYTES, member)
            convert_csv(csv_path, target)
        except (zipfile.BadZipFile, OSError) as exc:
            raise call_error(
                UpstreamError,
                f"on_fir: {url} could not be unpacked: {exc}",
                f"on_fir : {url} n'a pas pu être décompressé : {exc}",
            ) from exc
        finally:
            csv_path.unlink(missing_ok=True)
            zip_path.unlink(missing_ok=True)
        # The same year under an earlier "last updated" date is superseded.
        for older in target.parent.glob(f"fir_{target.stem.split('_')[1]}_*.parquet"):
            if older != target:
                older.unlink(missing_ok=True)
        _enforce_cache_cap(target.parent, target)

    await run_in_pool(extract_and_convert)
    return target


async def local_year(year: int, url: str, last_updated: str | None) -> Path:
    """The Parquet copy of one FIR year, downloading it if needed."""
    stamp = (last_updated or "undated").replace("-", "")
    target = config.get_on_fir_cache_dir() / f"fir_{year}_{stamp}.parquet"
    if target.exists():
        target.touch()
        return target
    key = target.name
    task = _downloads.get(key)
    if task is None or task.done():
        task = asyncio.create_task(_download(url, target))
        _downloads[key] = task
    return await asyncio.shield(task)
