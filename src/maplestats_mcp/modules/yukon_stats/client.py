"""Yukon Bureau of Statistics: table listing (via the CKAN client) and CSV reading."""

from __future__ import annotations

import csv
import io
from typing import Literal
from urllib.parse import urlparse

import httpx

from maplestats_mcp.modules.ckan import client as ckan
from maplestats_mcp.modules.yukon_stats import constants
from maplestats_mcp.modules.yukon_stats.schemas import TableEntry, TableList, TableRows
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.csv_files import Columns, decode, exact_filter
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


async def _catalogue() -> tuple[list[TableEntry], bool]:
    async def fetch() -> list[TableEntry]:
        found = await ckan.search_datasets(
            constants.PORTAL,
            "",
            fq=f"organization:{constants.ORGANIZATION}",
            rows=100,
        )
        tables: list[TableEntry] = []
        for summary in found.packages:
            detail = await ckan.get_dataset(constants.PORTAL, summary.id)
            for resource in detail.resources:
                url = resource.url or ""
                parsed = urlparse(url)
                if (
                    (resource.format or "").upper() == "CSV"
                    and parsed.hostname == constants.DOMAIN
                    and parsed.path.lower().endswith(".csv")
                ):
                    tables.append(
                        TableEntry(
                            dataset=detail.name or detail.id,
                            dataset_title=detail.title,
                            title=resource.name,
                            url=url,
                            modified=resource.last_modified or resource.metadata_modified,
                        )
                    )
        return tables

    return await cached_fetch("yukon_stats:catalogue", constants.CACHE_TTL_LIST_SECONDS, fetch)


async def list_tables(
    query: str | None = None,
    dataset: str | None = None,
    limit: int = constants.TABLES_LIMIT_MAX,
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
            url=f"https://{constants.DOMAIN}/en/organization/{constants.ORGANIZATION}",
            cached=cached,
            schema_name="yukon_stats.TableList",
            coverage="CSV tables of the Yukon Bureau of Statistics organization only.",
            limits=f"Showing {limit} of {total} tables." if total > limit else None,
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


async def _table(url: str) -> tuple[tuple[list[str], list[dict[str, str]]], bool]:
    async def fetch() -> tuple[list[str], list[dict[str, str]]]:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=180.0)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise NotFound(f"yukon_stats: no file at {url}.") from exc
            raise UpstreamError(
                f"yukon_stats: {url} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"yukon_stats: {url} did not respond in time.") from exc
        if len(response.content) > constants.MAX_FILE_BYTES:
            raise UpstreamError(f"yukon_stats: {url} is larger than this tool reads.")
        return _parse(response.content)

    return await cached_fetch(f"yukon_stats:file:{url}", constants.CACHE_TTL_FILE_SECONDS, fetch)


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

    (names, rows), cached = await _table(url)
    lookup = Columns([dict.fromkeys(names, "")])
    rows = exact_filter(rows, lookup, filters)
    chosen = [lookup.require(c) for c in columns] if columns else names
    total = len(rows)
    page = [{c: r.get(c, "") for c in chosen} for r in rows[offset : offset + limit]]
    return TableRows(
        url=url,
        columns=chosen,
        all_columns=names,
        rows=page,
        total_rows=total,
        offset=offset,
        truncated=offset + limit < total,
        licence=constants.LICENCE[lang],
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="yukon_stats.TableRows",
            freshness="As published by the Yukon Bureau of Statistics.",
            coverage="The 'footnotes' column is dropped and other cells are cut at "
            f"{constants.CELL_MAX_CHARS} characters.",
            limits=(
                f"Showing rows {offset + 1} to {offset + len(page)} of {total}."
                if offset + limit < total
                else None
            ),
        ),
    )
