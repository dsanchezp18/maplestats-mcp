"""Client for GC InfoBase open datasets.

Files are listed from the federal CKAN package and addressed by
resource id, so a caller never supplies a download URL. Rows come from
the CSV through shared/csv_files.py.
"""

from __future__ import annotations

import re

from maple_data_mcp.modules.ckan import client as ckan
from maple_data_mcp.modules.ckan.schemas import ResourceInfo
from maple_data_mcp.modules.gc_infobase import constants
from maple_data_mcp.modules.gc_infobase.schemas import InfoBaseFile, InfoBaseFileList, InfoBaseRows
from maple_data_mcp.shared import csv_files
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound
from maple_data_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_YEAR = re.compile(r"(\d{4})")


async def _csv_resources(lang: str) -> tuple[list[ResourceInfo], str]:
    package = await ckan.get_dataset("federal", constants.PACKAGE_ID, lang)
    resources = [r for r in package.resources if (r.format or "").upper() == "CSV" and r.url]
    return resources, package.provenance.url


def _file(resource: ResourceInfo) -> InfoBaseFile:
    return InfoBaseFile(
        resource_id=resource.id,
        name=resource.name,
        description=resource.description,
        languages=resource.language,
        url=resource.url or "",
    )


async def list_files(query: str | None = None, lang: str = "en") -> InfoBaseFileList:
    resources, url = await _csv_resources(lang)
    needle = (query or "").strip().lower()
    files = [
        _file(r)
        for r in resources
        if (not r.language or lang in r.language)
        and (not needle or needle in f"{r.name} {r.description or ''}".lower())
    ]
    return InfoBaseFileList(
        files=files,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=False,
            schema_name="gc_infobase.InfoBaseFileList",
        ),
    )


def _start_year(value: str) -> str | None:
    found = _YEAR.search(value or "")
    return found.group(1) if found else None


async def query(
    resource_id: str,
    *,
    organization: str | None = None,
    fiscal_year: str | None = None,
    filters: dict[str, str] | None = None,
    columns: list[str] | None = None,
    limit: int = constants.ROWS_DEFAULT,
    lang: str = "en",
) -> InfoBaseRows:
    """Rows of one file. `organization` is a case-insensitive substring;
    `fiscal_year` matches on the start year ("2023", "2023-24")."""
    if limit < 1 or limit > constants.ROWS_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.ROWS_MAX}, got {limit}.")
    year = _start_year(fiscal_year) if fiscal_year else None
    if fiscal_year and year is None:
        raise InvalidInput(f"fiscal_year must contain a year such as 2023, got {fiscal_year!r}.")

    resources, _ = await _csv_resources(lang)
    resource = next((r for r in resources if r.id == resource_id.strip()), None)
    if resource is None:
        raise NotFound(f"No GC InfoBase file {resource_id!r}. Use gc_infobase_list_files.")
    url = resource.url or ""
    csv_files.check_url(url, constants.ALLOWED_HOSTS, "gc_infobase")
    rows = await csv_files.fetch_rows(
        url, limiter=_LIMITER, ttl=constants.CACHE_TTL_FILE_SECONDS, context="gc_infobase"
    )
    lookup = csv_files.Columns(rows)
    matching = csv_files.exact_filter(rows, lookup, filters)
    year_column = lookup.first_of(constants.FISCAL_YEAR_COLUMNS)
    org_column = lookup.first_of(constants.ORGANIZATION_COLUMNS)
    if organization:
        if org_column is None:
            raise InvalidInput(f"This file has no organization column; columns are {lookup.names}.")
        needle = organization.strip().lower()
        matching = [r for r in matching if needle in (r.get(org_column) or "").lower()]
    if year:
        if year_column is None:
            raise InvalidInput(f"This file has no fiscal-year column; columns are {lookup.names}.")
        matching = [r for r in matching if _start_year(r.get(year_column) or "") == year]
    kept = matching[:limit]
    selected, selected_rows = csv_files.select(kept, lookup, columns)
    return InfoBaseRows(
        resource_id=resource.id,
        name=resource.name,
        columns=selected,
        rows=selected_rows,
        total_rows=len(rows),
        matching_rows=len(matching),
        returned_count=len(kept),
        fiscal_year_column=year_column,
        organization_column=org_column,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=False,
            schema_name="gc_infobase.InfoBaseRows",
            coverage=f"{len(kept)} of {len(matching)} matching rows",
            freshness="files refreshed with each Estimates and Public Accounts release",
        ),
    )
