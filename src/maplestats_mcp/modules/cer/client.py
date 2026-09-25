"""Client for Canada Energy Regulator open data.

Discovery reuses the federal CKAN client (the CER's own catalogue is
open.canada.ca's `cer-rec` organization); rows come straight from the
CER's CSV files, restricted to CER hosts. See constants.py for the
encoding and error-page quirks confirmed live.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from maplestats_mcp.modules.cer import constants
from maplestats_mcp.modules.cer.schemas import CerDataset, CerDatasetList, CerFile, CerRows
from maplestats_mcp.modules.ckan import client as ckan
from maplestats_mcp.shared import csv_files
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.rate_limiter import get_limiter

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


async def _download(url: str) -> tuple[list[dict[str, str]], bool]:
    csv_files.check_url(url, constants.ALLOWED_HOSTS, "cer")
    return await csv_files.fetch_rows(
        url, limiter=_LIMITER, ttl=constants.CACHE_TTL_FILE_SECONDS, context="cer"
    )


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
    rows, cached = await _download(url)
    columns_lookup = csv_files.Columns(rows)
    filtered = csv_files.exact_filter(rows, columns_lookup, filters)
    date_column = columns_lookup.first_of(constants.DATE_COLUMNS)

    def keep(row: dict[str, Any]) -> bool:
        if date_column and (start_date or end_date):
            when = _row_date(row.get(date_column) or "")
            if when is None:
                return False
            if start_date and when < start_date:
                return False
            if end_date and when > end_date:
                return False
        return True

    matching = [r for r in filtered if keep(r)]
    if date_column:
        matching.sort(key=lambda r: _row_date(r.get(date_column) or "") or date.min)
        kept = matching[-limit:]
    else:
        kept = matching[:limit]
    selected, selected_rows = csv_files.select(kept, columns_lookup, columns)
    return CerRows(
        url=url,
        columns=selected,
        rows=selected_rows,
        total_rows=len(rows),
        matching_rows=len(matching),
        returned_count=len(kept),
        date_column=date_column,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="cer.CerRows",
            coverage=f"{len(kept)} of {len(matching)} matching rows",
        ),
    )
