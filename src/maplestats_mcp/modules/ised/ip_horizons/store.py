"""Local Parquet copies of IP Horizons patent tables, fetched on first use.

A lookup or search downloads only the tables and number ranges it needs,
extracts the CSV from its ZIP, converts it to Parquet with DuckDB, and
deletes the ZIP and CSV. Checked live 2026-09-25 on the 2024-10-11
patent release: every file is pipe-delimited UTF-8 with no quoting and
the literal string NULL for missing values, and DuckDB's strict parser
read exactly one row per line (1,190,073 main rows; 9,070,237 party
rows). Converting the main file took 2 s and shrank 315 MB of CSV to
65 MB of Parquet.

Headers are bilingual ("Patent Number - Numéro du brevet"); columns are
renamed to the English half in snake_case. Values are trimmed because
some dates carry a leading space (" 1995-03-14").

A download that outlives the tool timeout keeps running (asyncio.shield),
so a retry finds it finished, as in statcan/pumf/tabulate.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import zipfile
from pathlib import Path

from maplestats_mcp import config
from maplestats_mcp.modules.ised.ip_horizons.schemas import IpHorizonsFile
from maplestats_mcp.shared.errors import NotFound, UpstreamUnavailable

_downloads: dict[str, asyncio.Task[Path]] = {}
_DOWNLOAD_ATTEMPTS = 3
_RETRY_WAIT_SECONDS = 5.0


def column_name(header: str) -> str:
    english = header.split(" - ")[0]
    return re.sub(r"[^a-z0-9]+", "_", english.strip().lower()).strip("_")


def _enforce_cache_cap(root: Path, keep: Path) -> None:
    files = sorted((p for p in root.rglob("*.parquet")), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    for path in files:
        if total <= config.get_ip_horizons_cache_max_bytes():
            break
        if path != keep:
            total -= path.stat().st_size
            path.unlink(missing_ok=True)


def convert_csv(csv_path: Path, target: Path) -> None:
    """Write a pipe-delimited IP Horizons CSV as Parquet with clean column names."""
    # Imported on first use: duckdb takes ~0.5 s to import and only these tools use it.
    import duckdb

    source = str(csv_path).replace("'", "''")
    reader = (
        f"read_csv('{source}', delim='|', header=true, all_varchar=true, "
        "quote='', escape='', nullstr='NULL')"
    )
    with duckdb.connect() as connection:
        headers = [
            row[0] for row in connection.execute(f"DESCRIBE SELECT * FROM {reader}").fetchall()
        ]
        columns = []
        for header in headers:
            name = column_name(header)
            quoted = '"' + header.replace('"', '""') + '"'
            if name == "patent_number":
                columns.append(f"TRY_CAST(trim({quoted}) AS BIGINT) AS patent_number")
            else:
                columns.append(f"NULLIF(trim({quoted}), '') AS {name}")
        part = target.with_suffix(".parquet.part")
        sink = str(part).replace("'", "''")
        connection.execute(
            f"COPY (SELECT {', '.join(columns)} FROM {reader}) "
            f"TO '{sink}' (FORMAT parquet, COMPRESSION zstd)"
        )
    part.replace(target)


async def _fetch_zip(file: IpHorizonsFile, zip_path: Path) -> None:
    # Imported here to avoid a cycle: client imports this module.
    from maplestats_mcp.modules.ised.ip_horizons.client import cipo_client

    async with cipo_client().stream("GET", file.url) as response:
        response.raise_for_status()
        # Dead links answer 404 with an HTML page (caught by the caller);
        # refuse an HTML body with any other status rather than unzip it.
        if "html" in response.headers.get("content-type", ""):
            raise NotFound(f"ised_ip_horizons: {file.url} is no longer published.")
        with zip_path.open("wb") as handle:
            async for chunk in response.aiter_bytes(1 << 20):
                handle.write(chunk)


async def _download(file: IpHorizonsFile, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    zip_path = target.with_suffix(".zip.part")
    for attempt in range(1, _DOWNLOAD_ATTEMPTS + 1):
        try:
            await _fetch_zip(file, zip_path)
            break
        except NotFound:
            zip_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            zip_path.unlink(missing_ok=True)
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 404:
                raise NotFound(f"ised_ip_horizons: {file.url} is no longer published.") from exc
            if attempt == _DOWNLOAD_ATTEMPTS:
                raise UpstreamUnavailable(
                    f"ised_ip_horizons: download of {file.url} failed: {exc!r}"
                ) from exc
            await asyncio.sleep(_RETRY_WAIT_SECONDS * attempt)

    def extract_and_convert() -> None:
        csv_path = target.with_suffix(".csv.part")
        try:
            with zipfile.ZipFile(zip_path) as archive:
                member = next(n for n in archive.namelist() if n.lower().endswith(".csv"))
                with archive.open(member) as source, csv_path.open("wb") as sink:
                    shutil.copyfileobj(source, sink, 1 << 20)
            convert_csv(csv_path, target)
        finally:
            csv_path.unlink(missing_ok=True)
            zip_path.unlink(missing_ok=True)
        _enforce_cache_cap(config.get_ip_horizons_cache_dir(), target)

    await asyncio.to_thread(extract_and_convert)
    return target


async def local_table(file: IpHorizonsFile) -> Path:
    """The Parquet copy of one IP Horizons file, downloading it if needed."""
    # The URL carries the release date, so a new quarterly release is a new key.
    key = hashlib.sha1(file.url.encode()).hexdigest()[:16]
    target = config.get_ip_horizons_cache_dir() / f"{file.table}_{key}.parquet"
    if target.exists():
        target.touch()
        return target
    task = _downloads.get(key)
    if task is None or task.done():
        task = asyncio.create_task(_download(file, target))
        _downloads[key] = task
    return await asyncio.shield(task)
