"""Client for GC InfoBase open datasets.

Files are listed from the federal CKAN package and addressed by
resource id, so a caller never supplies a download URL. Rows come from
the CSV through shared/csv_files.py.
"""

from __future__ import annotations

import re

from maplestats_mcp.modules.ckan import client as ckan
from maplestats_mcp.modules.ckan.schemas import ResourceInfo
from maplestats_mcp.modules.gc_infobase import constants
from maplestats_mcp.modules.gc_infobase.schemas import InfoBaseFile, InfoBaseFileList, InfoBaseRows
from maplestats_mcp.shared import csv_files
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_YEAR = re.compile(r"(\d{4})")


async def _csv_resources(lang: str) -> tuple[list[ResourceInfo], str, bool]:
    package = await ckan.get_dataset("federal", constants.PACKAGE_ID, lang)
    resources = [r for r in package.resources if (r.format or "").upper() == "CSV" and r.url]
    # The CKAN provenance names the bare package_show action; the package
    # id makes the link reproduce this listing.
    url = package.provenance.url
    if "?" not in url:
        url = f"{url}?id={constants.PACKAGE_ID}"
    return resources, url, package.provenance.cached


# Columns whose numbers are identifiers or codes, not quantities: org_id,
# Org_ID, OID, MID, program_id, vote_type_id, vote_number, dept_code
# (names seen across the 35 English files, 2026-10-03). They stay text.
_ID_COLUMN = re.compile(r"(?:^|_)(?:[a-z]{0,2}id|code|number|num)$", re.IGNORECASE)
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")


def _numeric_columns(rows: list[dict[str, str]], names: list[str]) -> set[str]:
    numeric = set()
    for name in names:
        if _ID_COLUMN.search(name):
            continue
        values = [v for r in rows if (v := (r.get(name) or "").strip())]
        if values and all(_NUMBER.match(v) for v in values):
            numeric.add(name)
    return numeric


def _number(value: str) -> int | float | None:
    text = value.strip()
    if not text:
        return None
    return float(text) if "." in text else int(text)


def _file(resource: ResourceInfo) -> InfoBaseFile:
    return InfoBaseFile(
        resource_id=resource.id,
        name=resource.name,
        description=resource.description,
        languages=resource.language,
        url=resource.url or "",
    )


async def list_files(query: str | None = None, lang: str = "en") -> InfoBaseFileList:
    resources, url, cached = await _csv_resources(lang)
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
            cached=cached,
            schema_name="gc_infobase.InfoBaseFileList",
            lang=lang,
        ),
    )


async def _own_language_name(resource: ResourceInfo, lang: str) -> tuple[str, str | None]:
    """The file's name in its own language, and a note when `lang` differs.

    CKAN translates a resource's name whatever the file's language: live
    2026-10-03, tp_pt_en.csv asked for with lang="fr" came back named
    "Comptes publics du Canada – Paiements de transfert" over English rows
    and columns. The name is taken in the file's language instead, and the
    note points to the file in the asked language when there is one.
    """
    if not resource.language or lang in resource.language:
        return resource.name, None
    own = resource.language[0]
    own_resources, _, _ = await _csv_resources(own)
    name = next((r.name for r in own_resources if r.id == resource.id), resource.name)
    asked, _, _ = await _csv_resources(lang)
    stem = (resource.url or "").rsplit("/", 1)[-1]
    twin_stem = re.sub(rf"_{own}\.csv$", f"_{lang}.csv", stem)
    twin = next(
        (
            r
            for r in asked
            if twin_stem != stem and (r.url or "").endswith(f"/{twin_stem}") and lang in r.language
        ),
        None,
    )
    note = f"This file is in {own.upper()} only; lang={lang!r} does not translate its rows."
    if twin is not None:
        note += f" The {lang.upper()} file is resource_id {twin.id!r} ({twin.name})."
    return name, note


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

    resources, _, _ = await _csv_resources(lang)
    resource = next((r for r in resources if r.id == resource_id.strip()), None)
    if resource is None:
        raise NotFound(f"No GC InfoBase file {resource_id!r}. Use gc_infobase_list_files.")
    name, language_note = await _own_language_name(resource, lang)
    url = resource.url or ""
    csv_files.check_url(url, constants.ALLOWED_HOSTS, "gc_infobase")
    rows, cached = await csv_files.fetch_rows(
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
    # Judged over the whole file so a column's type does not depend on
    # which rows matched (live: "expenditures" came back as "390060074.49").
    numeric = _numeric_columns(rows, selected)
    typed_rows = [
        {c: _number(v) if c in numeric else v for c, v in row.items()} for row in selected_rows
    ]
    return InfoBaseRows(
        resource_id=resource.id,
        name=name,
        columns=selected,
        numeric_columns=[c for c in selected if c in numeric],
        rows=typed_rows,
        total_rows=len(rows),
        matching_rows=len(matching),
        returned_count=len(kept),
        fiscal_year_column=year_column,
        organization_column=org_column,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="gc_infobase.InfoBaseRows",
            coverage=f"{len(kept)} of {len(matching)} matching rows",
            freshness="files refreshed with each Estimates and Public Accounts release",
            limits=language_note,
            lang=lang,
        ),
    )
