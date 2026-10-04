"""Yukon Bureau of Statistics: table listing (one CKAN call) and CSV reading.

Discovery is one `package_search` for the Bureau's organization: its
results already carry every resource (URL, format, size), so no per-dataset
`package_show` is needed. Only CSV files the catalogue lists are read, and a
file whose declared size is over the cap is refused before it is downloaded;
others are streamed under the cap.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from maplestats_mcp.modules.yukon_stats import constants
from maplestats_mcp.modules.yukon_stats.schemas import TableEntry, TableList, TableRows
from maplestats_mcp.shared import file_download
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.ckan import CkanConfig, action
from maplestats_mcp.shared.csv_files import Columns, decode, exact_filter
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.licences import OGL_YUKON
from maplestats_mcp.shared.limits import fit_to_budget, join_limits
from maplestats_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

# Discovery shares the download bucket: the host is paced at one request per
# 10 seconds whatever is asked of it.
_CONFIG = CkanConfig(
    source=constants.RATE_LIMIT_SOURCE,
    base_url=constants.API_URL,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
    timeout=constants.CATALOGUE_TIMEOUT_SECONDS,
)


def _when(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def parse_packages(packages: list[dict[str, Any]]) -> list[TableEntry]:
    """Every CSV resource hosted on open.yukon.ca among the given datasets."""
    tables: list[TableEntry] = []
    for package in packages:
        name = str(package.get("name") or package.get("id") or "")
        for resource in list_or_empty(package, "resources"):
            url = str(resource.get("url") or "")
            parsed = urlparse(url)
            if not (
                str(resource.get("format") or "").upper() == "CSV"
                and parsed.hostname == constants.DOMAIN
                and parsed.path.lower().endswith(".csv")
            ):
                continue
            size = resource.get("size")
            tables.append(
                TableEntry(
                    dataset=name,
                    dataset_title=str(package.get("title") or name),
                    title=str(resource.get("name") or url.rsplit("/", 1)[-1]),
                    url=url,
                    modified=_when(resource.get("last_modified"))
                    or _when(resource.get("metadata_modified")),
                    size_bytes=int(size) if isinstance(size, int | float) else None,
                )
            )
    return tables


async def _catalogue() -> tuple[list[TableEntry], bool]:
    async def fetch() -> list[TableEntry]:
        result = await action(
            _CONFIG,
            "package_search",
            params={"fq": f"organization:{constants.ORGANIZATION}", "rows": 100},
        )
        return parse_packages(list_or_empty(result, "results"))

    return await cached_fetch("yukon_stats:catalogue", constants.CACHE_TTL_LIST_SECONDS, fetch)


async def list_tables(
    query: str | None = None,
    dataset: str | None = None,
    limit: int = constants.TABLES_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> TableList:
    if not 1 <= limit <= constants.TABLES_LIMIT_MAX:
        raise InvalidInput(f"yukon_stats: limit must be 1 to {constants.TABLES_LIMIT_MAX}.")
    tables, cached = await _catalogue()
    if dataset:
        wanted = dataset.casefold()
        tables = [
            t
            for t in tables
            if wanted in t.dataset.casefold() or wanted in t.dataset_title.casefold()
        ]
    if query:
        words = query.casefold().split()
        tables = [
            t
            for t in tables
            if all(w in f"{t.title} {t.dataset_title} {t.dataset}".casefold() for w in words)
        ]
    total = len(tables)
    return TableList(
        tables=tables[:limit],
        total_tables=total,
        truncated=total > limit,
        licence=constants.LICENCE[lang],
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=f"{constants.API_URL}package_search?fq=organization:{constants.ORGANIZATION}"
            "&rows=100",
            cached=cached,
            schema_name="yukon_stats.TableList",
            coverage="CSV tables of the Yukon Bureau of Statistics organization only.",
            limits=(
                f"Showing {limit} of {total} tables; narrow with query or dataset, or raise "
                f"limit (max {constants.TABLES_LIMIT_MAX})."
                if total > limit
                else None
            ),
            licence=OGL_YUKON,
        ),
    )


def check_table_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != constants.DOMAIN
        or not parsed.path.startswith(constants.DOWNLOAD_PATH_PREFIX)
        or not parsed.path.lower().endswith(".csv")
    ):
        raise InvalidInput(
            f"yukon_stats: url must be an https .csv link on {constants.DOMAIN} under "
            f"{constants.DOWNLOAD_PATH_PREFIX} (see yukon_stats_list_tables)."
        )


def _parse(body: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = decode(body)
    if text.lstrip().lower().startswith(("<!doctype", "<html")):
        raise NotFound("yukon_stats: the link returned a web page, not a CSV file.")
    reader = csv.DictReader(io.StringIO(text))
    names = [(n or "").strip() for n in (reader.fieldnames or [])]
    keep = [n for n in names if n.lower() not in constants.DROPPED_COLUMNS]
    limit = constants.CELL_MAX_CHARS
    rows = [
        {(k or "").strip(): (v or "")[:limit] for k, v in row.items() if (k or "").strip() in keep}
        for row in reader
    ]
    return keep, rows


def _too_large(url: str, size: int) -> UpstreamError:
    return UpstreamError(
        f"yukon_stats: {url} is {size:,} bytes, larger than the {constants.MAX_FILE_BYTES:,} "
        "this tool reads. Download it from the portal instead."
    )


async def _table(
    url: str, declared_size: int | None
) -> tuple[tuple[list[str], list[dict[str, str]]], bool]:
    # The catalogue states each file's size; refuse an oversized file before
    # spending a paced request and the download on it.
    if declared_size and declared_size > constants.MAX_FILE_BYTES:
        raise _too_large(url, declared_size)

    async def fetch() -> tuple[list[str], list[dict[str, str]]]:
        # Streamed under the cap: a declared Content-Length above it is refused
        # before the body is read, and an undeclared one stops at the cap. The
        # parsed rows are cached below, so the bytes are not kept a second time.
        downloaded = await file_download.download(
            url,
            allow_host=lambda host: host == constants.DOMAIN,
            limiter_for=lambda _host: _LIMITER,
            max_bytes=constants.MAX_FILE_BYTES,
            context="yukon_stats",
            timeout=180.0,
        )
        return await run_parse(_parse, downloaded.body)

    return await cached_fetch(f"yukon_stats:file:{url}", constants.CACHE_TTL_FILE_SECONDS, fetch)


async def _listed(url: str) -> TableEntry:
    """The catalogue entry for exactly this URL.

    open.yukon.ca serves a download by its resource id and ignores the file
    name: on 2026-10-03 ".../resource/9d6ceba0-.../download/zz-vacancy-rates.csv"
    returned the rent table, so an unchecked URL can label one table with
    another's name. Only URLs the catalogue lists are read, so the tool also
    never fetches an arbitrary path under /data/.
    """
    tables, _ = await _catalogue()
    entry = next((t for t in tables if t.url == url), None)
    if entry is not None:
        return entry
    resource_id = _resource_id(url)
    same = next((t for t in tables if resource_id and _resource_id(t.url) == resource_id), None)
    if same is not None:
        raise InvalidInput(
            f"yukon_stats: the catalogue lists this resource as {same.url} ({same.title!r}); "
            "pass that exact URL."
        )
    raise NotFound(
        f"yukon_stats: {url} is not a CSV table of the Yukon Bureau of Statistics "
        "(see yukon_stats_list_tables)."
    )


def _resource_id(url: str) -> str | None:
    parts = urlparse(url).path.split("/")
    if "resource" in parts:
        index = parts.index("resource") + 1
        return parts[index] if index < len(parts) else None
    return None


async def query_table(
    url: str,
    filters: dict[str, str] | None = None,
    columns: list[str] | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> TableRows:
    check_table_url(url)
    if not 1 <= limit <= constants.ROWS_LIMIT_MAX:
        raise InvalidInput(f"yukon_stats: limit must be 1 to {constants.ROWS_LIMIT_MAX}.")
    if offset < 0:
        raise InvalidInput("yukon_stats: offset must be 0 or more.")

    entry = await _listed(url)
    (names, rows), cached = await _table(url, entry.size_bytes)
    lookup = Columns([dict.fromkeys(names, "")])
    rows = exact_filter(rows, lookup, filters)
    chosen = [lookup.require(c) for c in columns] if columns else names
    total = len(rows)
    page = fit_to_budget([{c: r.get(c, "") for c in chosen} for r in rows[offset : offset + limit]])
    more = offset + len(page) < total
    return TableRows(
        url=url,
        columns=chosen,
        all_columns=names,
        rows=page,
        total_rows=total,
        offset=offset,
        truncated=more,
        licence=constants.LICENCE[lang],
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="yukon_stats.TableRows",
            freshness="As published by the Yukon Bureau of Statistics.",
            coverage="The 'footnotes' column is dropped and other cells are cut at "
            f"{constants.CELL_MAX_CHARS} characters.",
            limits=join_limits(
                f"Showing rows {offset + 1} to {offset + len(page)} of {total}; page with "
                "offset, filter, or select fewer columns"
                if more
                else None,
                "The page was cut to about 200 KB"
                if len(page) < min(limit, total - offset)
                else None,
            ),
            licence=OGL_YUKON,
        ),
    )
