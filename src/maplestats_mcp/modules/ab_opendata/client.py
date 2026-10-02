"""Open Alberta files: dataset discovery through CKAN and file reading.

Discovery calls the portal's CKAN Action API (`package_search`,
`package_show`) through the shared CKAN helper; a file is read only when
its dataset lists it, so the tool never fetches arbitrary URLs. API calls
and downloads share one bucket of one request per 10 seconds (the portal's
robots.txt crawl delay). Sheet and CSV parsing lives in tables.py.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Literal
from urllib.parse import unquote, urlparse

import httpx

from maplestats_mcp.modules.ab_opendata import constants, tables
from maplestats_mcp.modules.ab_opendata.schemas import (
    DatasetDetail,
    DatasetEntry,
    DatasetList,
    OrganizationCount,
    OrganizationList,
    ResourceEntry,
    ResourceRows,
    ResourceStructure,
    SheetInfo,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.ckan import CkanConfig, action, excerpt
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]
FormatName = Literal["xlsx", "xls", "csv"]
SortName = Literal["relevance", "modified", "title"]

_CONFIG = CkanConfig(
    source=constants.RATE_LIMIT_SOURCE,
    base_url=constants.API_BASE,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
    timeout=60.0,
)
_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_DOWNLOAD = re.compile(constants.DOWNLOAD_PATH_PATTERN)
_SLUG = re.compile(r"^[a-z0-9_-]+$")

LICENCE_NOTE = {
    "en": "Almost every Open Alberta dataset is under the Open Government Licence - Alberta: "
    "a worldwide, royalty-free, perpetual, non-exclusive licence to use the information, "
    "including for commercial purposes, with the attribution 'Contains information "
    "licensed under the Open Government Licence – Alberta.' A dataset whose ogl_alberta "
    "is false is under other terms: its own licence, or by default the alberta.ca terms "
    "of use (non-commercial); check licence_note before reusing it.",
    "fr": "Presque tous les jeux de données d'Open Alberta relèvent de la Licence du "
    "gouvernement ouvert - Alberta : licence mondiale, libre de redevances, perpétuelle et "
    "non exclusive d'utilisation de l'information, y compris à des fins commerciales, avec "
    "la mention « Contains information licensed under the Open Government Licence – "
    "Alberta. » Un jeu dont ogl_alberta est faux relève d'autres conditions : sa propre "
    "licence ou, par défaut, les conditions d'utilisation d'alberta.ca (usage non "
    "commercial); lire licence_note avant toute réutilisation.",
}
OTHER_LICENCE_NOTE = {
    "en": "NOT under the Open Government Licence - Alberta (licence: {licence}). Other terms "
    "apply: the dataset's own licence or, by default, the alberta.ca terms of use, which "
    "are non-commercial. Do not assume commercial reuse is allowed; check {url}.",
    "fr": "N'est PAS sous la Licence du gouvernement ouvert - Alberta (licence : {licence}). "
    "D'autres conditions s'appliquent : la licence propre au jeu ou, par défaut, les "
    "conditions d'utilisation d'alberta.ca, qui sont non commerciales. Ne pas supposer que "
    "la réutilisation commerciale est permise; vérifier {url}.",
}
NO_LICENCE = {"en": "none stated", "fr": "aucune indiquée"}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    # Titles carry U+FFFD where an en dash was lost upstream; notes carry literal &nbsp;.
    text = str(value).replace("�", "").replace("&nbsp;", " ").replace("\xa0", " ")
    text = " ".join(text.split())
    return None if text in ("", "null") else text


def _first(value: Any) -> str | None:
    if isinstance(value, list):
        return _clean(value[0]) if value else None
    return _clean(value)


def parse_download_url(url: str) -> tuple[str, str]:
    """(dataset id, resource id) of an open.alberta.ca download link, or InvalidInput."""
    parsed = urlparse(url)
    match = _DOWNLOAD.match(parsed.path)
    if parsed.scheme != "https" or parsed.hostname != constants.DOMAIN or match is None:
        raise InvalidInput(
            f"ab_opendata: url must be an https download link on {constants.DOMAIN} "
            "(/dataset/<id>/resource/<id>/download/<file>); see ab_opendata_search_datasets."
        )
    return match["dataset"], match["resource"]


def _readable(url: str, fmt: str | None) -> bool:
    parsed = urlparse(url)
    return (
        (fmt or "").lower() in constants.FORMATS
        and parsed.scheme == "https"
        and parsed.hostname == constants.DOMAIN
        and _DOWNLOAD.match(parsed.path) is not None
    )


def _resource(raw: dict[str, Any]) -> ResourceEntry:
    url = str(raw.get("url") or "")
    size = raw.get("size")
    fmt = _clean(raw.get("format"))
    return ResourceEntry(
        id=str(raw.get("id") or ""),
        name=_clean(raw.get("name")) or unquote(url.rsplit("/", 1)[-1]),
        format=fmt,
        size_bytes=int(size) if isinstance(size, int | float) and size else None,
        modified=_clean(raw.get("last_modified") or raw.get("metadata_modified")),
        url=url,
        readable=_readable(url, fmt),
        description=excerpt(_clean(raw.get("description")) or "", 200) or None,
    )


def parse_dataset(package: dict[str, Any], lang: Lang = "en") -> DatasetEntry:
    name = str(package.get("name") or package.get("id") or "")
    organization = package.get("organization") or {}
    licence_id = _clean(package.get("license_id"))
    ogl = licence_id == constants.OGL_LICENCE_ID
    licence = _clean(package.get("license_title"))
    url = constants.DATASET_URL.format(name=name)
    resources = [_resource(r) for r in list_or_empty(package, "resources")]
    resources.sort(key=lambda r: not r.readable)
    other = sorted({(r.format or "unknown").lower() for r in resources if not r.readable})
    return DatasetEntry(
        name=name,
        title=_clean(package.get("title")) or name,
        dataset_url=url,
        organization=_clean(organization.get("name")),
        organization_title=_clean(organization.get("title")),
        licence_id=licence_id,
        licence=licence,
        licence_url=_clean(package.get("license_url")),
        ogl_alberta=ogl,
        licence_note=None
        if ogl
        else OTHER_LICENCE_NOTE[lang].format(
            licence=licence or licence_id or NO_LICENCE[lang], url=url
        ),
        date_modified=_clean(package.get("date_modified"))
        or (_clean(package.get("metadata_modified")) or "")[:10]
        or None,
        update_frequency=_clean(package.get("updatefrequency")),
        time_coverage_from=_clean(package.get("time_coverage_from")),
        time_coverage_to=_clean(package.get("time_coverage_to")),
        topics=[t for t in (_clean(x) for x in list_or_empty(package, "topic")) if t],
        summary=excerpt(_clean(package.get("notes")) or "", constants.NOTES_EXCERPT_CHARS) or None,
        resources=resources,
        other_formats=other,
    )


async def _api(method: str, params: dict[str, Any]) -> tuple[Any, bool]:
    key = f"ab_opendata:{method}:{json.dumps(params, sort_keys=True)}"

    async def fetch() -> Any:
        return await action(_CONFIG, method, params=params)

    return await cached_fetch(key, constants.CACHE_TTL_API_SECONDS, fetch)


def _format_filter(fmt: str | None) -> str:
    if fmt is None:
        return "(res_format:XLSX OR res_format:XLS OR res_format:CSV)"
    if fmt not in constants.FORMATS:
        raise InvalidInput(f"ab_opendata: format must be one of {list(constants.FORMATS)}.")
    return f"res_format:{fmt.upper()}"


def _facet_organizations(result: Any) -> list[OrganizationCount]:
    facets = (result.get("search_facets") or {}).get("organization") or {}
    return [
        OrganizationCount(
            name=str(i.get("name")),
            title=_clean(i.get("display_name")) or str(i.get("name")),
            datasets=int(i.get("count") or 0),
        )
        for i in list_or_empty(facets, "items")
    ]


async def _search(
    query: str | None,
    organization: str | None,
    fmt: str | None,
    ogl_only: bool,
    sort: str,
    rows: int,
    start: int,
) -> tuple[Any, bool]:
    filters = ["type:opendata", _format_filter(fmt)]
    if organization:
        slug = organization.strip().lower()
        if not _SLUG.match(slug):
            raise InvalidInput(
                "ab_opendata: organization is a slug such as 'health' or "
                "'treasuryboardandfinance' (see ab_opendata_list_organizations)."
            )
        filters.append(f"organization:{slug}")
    if ogl_only:
        filters.append(f"license_id:{constants.OGL_LICENCE_ID}")
    order = {
        "relevance": "score desc, metadata_modified desc" if query else "metadata_modified desc",
        "modified": "metadata_modified desc",
        "title": "title_string asc",
    }
    if sort not in order:
        raise InvalidInput(f"ab_opendata: sort must be one of {list(order)}.")
    return await _api(
        "package_search",
        {
            "q": (query or "").strip(),
            "fq": " AND ".join(filters),
            "rows": rows,
            "start": start,
            "sort": order[sort],
            "facet.field": json.dumps(["organization"]),
            "facet.limit": constants.ORGANIZATIONS_FACET_LIMIT,
        },
    )


async def search_datasets(
    query: str | None = None,
    organization: str | None = None,
    format: str | None = None,
    ogl_alberta_only: bool = False,
    sort: SortName = "relevance",
    limit: int = constants.DATASETS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> DatasetList:
    if not 1 <= limit <= constants.DATASETS_LIMIT_MAX:
        raise InvalidInput(f"ab_opendata: limit must be 1 to {constants.DATASETS_LIMIT_MAX}.")
    if offset < 0:
        raise InvalidInput("ab_opendata: offset must be 0 or more.")
    result, cached = await _search(
        query, organization, format, ogl_alberta_only, sort, limit, offset
    )
    datasets = [parse_dataset(p, lang) for p in list_or_empty(result, "results")]
    total = int(result.get("count") or 0)
    return DatasetList(
        datasets=datasets,
        total_datasets=total,
        offset=offset,
        truncated=offset + len(datasets) < total,
        organizations=_facet_organizations(result),
        licence_note=LICENCE_NOTE[lang],
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=f"{constants.SITE}/dataset",
            cached=cached,
            schema_name="ab_opendata.DatasetList",
            freshness="Catalogue metadata, cached for six hours.",
            coverage="Open datasets (type opendata) with at least one Excel or CSV resource; "
            "publications, maps and datasets with only PDFs or links are not listed here "
            "(use ckan_ with portal=ab).",
            limits=(
                f"Showing datasets {offset + 1} to {offset + len(datasets)} of {total}."
                if offset + len(datasets) < total or offset
                else None
            ),
        ),
    )


async def list_organizations(format: str | None = None, lang: Lang = "en") -> OrganizationList:
    result, cached = await _search(None, None, format, False, "title", 1, 0)
    organizations = _facet_organizations(result)
    return OrganizationList(
        organizations=organizations,
        total_datasets=int(result.get("count") or 0),
        licence_note=LICENCE_NOTE[lang],
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=f"{constants.SITE}/organization",
            cached=cached,
            schema_name="ab_opendata.OrganizationList",
            freshness="Catalogue metadata, cached for six hours.",
            coverage="Counts datasets with an Excel or CSV resource only.",
        ),
    )


def _dataset_id(dataset: str) -> str:
    text = dataset.strip()
    if not text:
        raise InvalidInput("ab_opendata: dataset must not be empty.")
    parsed = urlparse(text)
    if parsed.hostname == constants.DOMAIN:
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "dataset":
            return parts[1]
        raise InvalidInput(f"ab_opendata: {text!r} is not a dataset page on {constants.DOMAIN}.")
    return text


async def _package(dataset_id: str) -> tuple[dict[str, Any], bool]:
    try:
        package, cached = await _api("package_show", {"id": dataset_id})
    except NotFound as exc:
        raise NotFound(f"ab_opendata: no dataset {dataset_id!r} on {constants.DOMAIN}.") from exc
    if not isinstance(package, dict):
        raise UpstreamError(f"ab_opendata: package_show for {dataset_id!r} returned no object.")
    return package, cached


async def get_dataset(dataset: str, lang: Lang = "en") -> DatasetDetail:
    package, cached = await _package(_dataset_id(dataset))
    entry = parse_dataset(package, lang)
    return DatasetDetail(
        dataset=entry,
        licence_note=LICENCE_NOTE[lang],
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=entry.dataset_url,
            cached=cached,
            schema_name="ab_opendata.DatasetDetail",
            freshness=f"Update frequency: {entry.update_frequency or 'not stated'}; "
            f"modified {entry.date_modified or 'date not stated'}.",
            coverage="Every resource of the dataset; only .xlsx, .xls and .csv files hosted "
            "on open.alberta.ca are readable with ab_opendata_read_resource.",
        ),
    )


async def _context(url: str, lang: Lang) -> tuple[DatasetEntry, ResourceEntry]:
    dataset_id, resource_id = parse_download_url(url)
    package, _ = await _package(dataset_id)
    entry = parse_dataset(package, lang)
    resource = next((r for r in entry.resources if r.id == resource_id), None)
    if resource is None:
        raise NotFound(
            f"ab_opendata: resource {resource_id} is not listed in dataset {entry.name!r}."
        )
    if not resource.readable:
        raise InvalidInput(
            f"ab_opendata: resource {resource.name!r} (format {resource.format}) is not an "
            "Excel or CSV file this module reads."
        )
    return entry, resource


async def _body(url: str, size_hint: int | None) -> tuple[bytes, bool]:
    if size_hint and size_hint > constants.MAX_FILE_BYTES:
        raise UpstreamError(f"ab_opendata: {url} is larger than this tool reads.")

    async def fetch() -> bytes:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=180.0)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise NotFound(f"ab_opendata: no file at {url}.") from exc
            raise UpstreamError(
                f"ab_opendata: {url} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"ab_opendata: {url} did not respond in time.") from exc
        if len(response.content) > constants.MAX_FILE_BYTES:
            raise UpstreamError(f"ab_opendata: {url} is larger than this tool reads.")
        return response.content

    return await cached_fetch(f"ab_opendata:file:{url}", constants.CACHE_TTL_FILE_SECONDS, fetch)


def _choose_sheet(sizes: list[tuple[str, int, int]], sheet: str | None) -> str:
    names = [n for n, _, _ in sizes]
    if sheet is None:
        return tables.largest_sheet(sizes)
    wanted = sheet.strip().casefold()
    for name in names:
        if name.casefold() == wanted:
            return name
    raise InvalidInput(f"ab_opendata: no sheet {sheet!r}; sheets are {names}.")


def _attribution(entry: DatasetEntry) -> str | None:
    return constants.OGL_ATTRIBUTION if entry.ogl_alberta else None


def _freshness(entry: DatasetEntry, resource: ResourceEntry) -> str:
    return (
        f"As published by the data owner; dataset update frequency: "
        f"{entry.update_frequency or 'not stated'}; file modified "
        f"{(resource.modified or 'date not stated')[:10]}."
    )


async def describe_resource(
    url: str, sheet: str | None = None, lang: Lang = "en"
) -> ResourceStructure:
    entry, resource = await _context(url, lang)
    body, cached = await _body(url, resource.size_bytes)
    fmt = tables.detect_format(body, resource.format)
    sizes = await asyncio.to_thread(tables.sheet_sizes, body, fmt)
    only = _choose_sheet(sizes, sheet) if sheet is not None else None
    total, summaries = await asyncio.to_thread(tables.describe, body, fmt, only)
    attribution = _attribution(entry)
    return ResourceStructure(
        url=url,
        format=fmt,
        resource_name=resource.name,
        dataset=entry.name,
        dataset_title=entry.title,
        sheets=[
            SheetInfo(
                name=s.name,
                rows=s.rows,
                columns=s.columns,
                header_row=s.header_row,
                column_names=s.column_names,
                preview=s.preview,
            )
            for s in summaries
        ],
        total_sheets=total,
        truncated=len(summaries) < (1 if only else total),
        licence=entry.licence,
        ogl_alberta=entry.ogl_alberta,
        attribution=attribution,
        licence_note=entry.licence_note,
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="ab_opendata.ResourceStructure",
            freshness=_freshness(entry, resource),
            coverage=attribution or entry.licence_note,
            limits=(
                f"Described the first {constants.MAX_DESCRIBED_SHEETS} of {total} sheets."
                if total > constants.MAX_DESCRIBED_SHEETS and not only
                else None
            ),
        ),
    )


async def read_resource(
    url: str,
    sheet: str | None = None,
    columns: list[str] | None = None,
    filters: dict[str, str] | None = None,
    contains: str | None = None,
    header_row: int | None = None,
    header_rows: int = 1,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> ResourceRows:
    parse_download_url(url)
    if not 1 <= limit <= constants.ROWS_LIMIT_MAX:
        raise InvalidInput(f"ab_opendata: limit must be 1 to {constants.ROWS_LIMIT_MAX}.")
    if offset < 0:
        raise InvalidInput("ab_opendata: offset must be 0 or more.")
    if header_row is not None and header_row < 1:
        raise InvalidInput("ab_opendata: header_row is 1-based (1 or more).")
    if not 1 <= header_rows <= 5:
        raise InvalidInput("ab_opendata: header_rows must be 1 to 5.")

    entry, resource = await _context(url, lang)
    body, cached = await _body(url, resource.size_bytes)
    fmt = tables.detect_format(body, resource.format)
    sizes = await asyncio.to_thread(tables.sheet_sizes, body, fmt)
    names = [n for n, _, _ in sizes]
    if not names:
        raise UpstreamError(f"ab_opendata: {url} has no sheets.")
    chosen = tables.CSV_SHEET if fmt == "csv" else _choose_sheet(sizes, sheet)
    result = await asyncio.to_thread(
        tables.scan,
        body,
        fmt,
        chosen,
        header_row=header_row,
        header_rows=header_rows,
        columns=columns,
        filters=filters,
        contains=contains,
        offset=offset,
        limit=limit,
    )
    more = offset + limit < result.total_rows
    notes = []
    if result.capped:
        notes.append(f"the file was scanned only up to {constants.MAX_SCAN_ROWS} rows")
    if more:
        notes.append(
            f"showing rows {offset + 1} to {offset + len(result.rows)} of {result.total_rows}"
        )
    attribution = _attribution(entry)
    return ResourceRows(
        url=url,
        format=fmt,
        resource_name=resource.name,
        dataset=entry.name,
        dataset_title=entry.title,
        sheets=names,
        sheet=chosen,
        header_row=result.header_row,
        all_columns=result.all_columns,
        columns=result.columns,
        rows=result.rows,
        total_rows=result.total_rows,
        offset=offset,
        truncated=more or result.capped,
        licence=entry.licence,
        ogl_alberta=entry.ogl_alberta,
        attribution=attribution,
        licence_note=entry.licence_note,
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="ab_opendata.ResourceRows",
            freshness=_freshness(entry, resource),
            coverage=(
                f"{entry.title}: {resource.name}, sheet {chosen!r} of {len(names)}. "
                + (attribution or entry.licence_note or "")
            ).strip(),
            limits="; ".join(notes) or None,
        ),
    )
