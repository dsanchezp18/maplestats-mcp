"""Client for Canada Energy Regulator open data.

Discovery reuses the federal CKAN client (the CER's own catalogue is
open.canada.ca's `cer-rec` organization); rows come straight from the
CER's CSV files, restricted to CER hosts. See constants.py for the
encoding and error-page quirks confirmed live.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any
from urllib.parse import urlparse

import httpx

from maple_data_mcp.modules.cer import constants
from maple_data_mcp.modules.cer.schemas import CerDataset, CerDatasetList, CerFile, CerRows
from maple_data_mcp.modules.ckan import client as ckan
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import get_raw
from maple_data_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


async def list_datasets(query: str = "", *, limit: int = 10, lang: str = "en") -> CerDatasetList:
    """CER datasets with CSV files, each file in the requested language."""
    if limit < 1 or limit > 25:
        raise InvalidInput(f"limit must be between 1 and 25, got {limit}.")
    found = await ckan.search_datasets(
        "federal",
        query,
        fq=f"organization:{constants.CATALOGUE_ORG} AND res_format:CSV",
        rows=limit,
        lang=lang,
    )
    datasets: list[CerDataset] = []
    for package in found.packages:
        detail = await ckan.get_dataset("federal", package.id, lang)
        files = [
            CerFile(name=r.name, url=r.url or "", language=r.language[0] if r.language else None)
            for r in detail.resources
            if (r.format or "").upper() == "CSV"
            and r.url
            and (not r.language or lang in r.language)
        ]
        if files:
            datasets.append(CerDataset(id=detail.id, title=detail.title, files=files))
    return CerDatasetList(
        datasets=datasets,
        total_count=found.total_count,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=found.provenance.url,
            cached=found.provenance.cached,
            schema_name="cer.CerDatasetList",
            coverage=f"{len(datasets)} of {found.total_count} CER datasets with CSV files",
        ),
    )


def _decode(body: bytes) -> str:
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return body.decode("cp1252")


async def _download(url: str) -> list[dict[str, str]]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in constants.ALLOWED_HOSTS:
        raise InvalidInput("url must be an https CER file URL from cer_list_datasets.")
    if not parsed.path.lower().endswith(".csv"):
        raise InvalidInput("url must point to a .csv file.")

    async def fetch() -> list[dict[str, str]]:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=120.0)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise NotFound(f"cer: no file at {url}.") from exc
            raise UpstreamError(f"cer: {url} returned HTTP {exc.response.status_code}.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"cer: {url} did not respond in time.") from exc
        if len(response.content) > constants.MAX_FILE_BYTES:
            raise UpstreamError(f"cer: {url} is larger than this tool reads.")
        text = _decode(response.content)
        if text.lstrip().lower().startswith(("<!doctype", "<html")):
            raise NotFound(f"cer: {url} returned a web page, not a CSV file.")
        # Some headers carry trailing spaces ("Période "); strip them.
        return [
            {(k or "").strip(): (v or "") for k, v in row.items()}
            for row in csv.DictReader(io.StringIO(text))
        ]

    rows, _ = await cached_fetch(f"cer:file:{url}", constants.CACHE_TTL_FILE_SECONDS, fetch)
    return rows


def _row_date(value: str) -> date | None:
    value = value.strip()
    try:
        if len(value) == 4 and value.isdigit():
            return date(int(value), 1, 1)
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_bound(value: str | None, name: str) -> date | None:
    if not value:
        return None
    parsed = _row_date(value)
    if parsed is None:
        raise InvalidInput(f"{name} must be YYYY or YYYY-MM-DD, got {value!r}.")
    return parsed


async def query_file(
    url: str,
    filters: dict[str, str] | None = None,
    *,
    columns: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = constants.ROWS_DEFAULT,
) -> CerRows:
    """Filter a CER CSV by exact (case-insensitive) column values and dates.

    Returns the most recent `limit` matching rows when the file has a
    date or year column, otherwise the first `limit`.
    """
    if limit < 1 or limit > constants.ROWS_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.ROWS_MAX}, got {limit}.")
    start_date = _parse_bound(start, "start")
    end_date = _parse_bound(end, "end")
    rows = await _download(url)
    header = list(rows[0].keys()) if rows else []
    by_lower = {c.lower(): c for c in header}

    def column(name: str) -> str:
        match = by_lower.get(name.strip().lower())
        if match is None:
            raise InvalidInput(f"Unknown column {name!r}; columns are {header}.")
        return match

    wanted = {column(k): v.strip().lower() for k, v in (filters or {}).items()}
    selected = [column(c) for c in columns] if columns else header
    date_column = next(
        (by_lower[c.lower()] for c in constants.DATE_COLUMNS if c.lower() in by_lower), None
    )

    def keep(row: dict[str, Any]) -> bool:
        if any((row.get(c) or "").strip().lower() != v for c, v in wanted.items()):
            return False
        if date_column and (start_date or end_date):
            when = _row_date(row.get(date_column) or "")
            if when is None:
                return False
            if start_date and when < start_date:
                return False
            if end_date and when > end_date:
                return False
        return True

    matching = [r for r in rows if keep(r)]
    if date_column:
        matching.sort(key=lambda r: _row_date(r.get(date_column) or "") or date.min)
        kept = matching[-limit:]
    else:
        kept = matching[:limit]
    return CerRows(
        url=url,
        columns=selected,
        rows=[{c: r.get(c) or "" for c in selected} for r in kept],
        total_rows=len(rows),
        matching_rows=len(matching),
        returned_count=len(kept),
        date_column=date_column,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=False,
            schema_name="cer.CerRows",
            coverage=f"{len(kept)} of {len(matching)} matching rows",
        ),
    )
