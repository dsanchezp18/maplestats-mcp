"""HTTP client and HTML parsers for Open Data Newfoundland and Labrador.

Live verification on 2026-09-18 found three stable public surfaces:

* ``datasets-tabular`` returns 71 dataset cards and ``datasets-spatial``
  returns 12; neither listing has server-side pagination.
* ``datasets-tabular-date``/``datasets-spatial-date`` accept
  ``sortby=datareleased`` and ``order=ascending|descending``.
* ``datasetdetails&id=<id>`` contains a ``dl`` of metadata and a download
  table whose links use ``filedownload/?file-id=<id>``.

The client therefore fetches the small listing pages, filters and paginates
locally, and returns the official file URLs without downloading potentially
large binary files into an MCP response.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal, NoReturn
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from maplestats_mcp.modules.nl_opendata import constants
from maplestats_mcp.modules.nl_opendata.schemas import (
    DatasetDetail,
    DatasetFile,
    DatasetSearchResult,
    DatasetSummary,
    TagList,
    TagSummary,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

DatasetType = Literal["all", "tabular", "spatial"]
SortOrder = Literal["name", "released_desc", "released_asc"]

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


def _has_detail_href(href: str | None) -> bool:
    return bool(href and "page-id=datasetdetails" in href)


def _has_tag_href(href: str | None) -> bool:
    return bool(href and "page-id=datasets-tag" in href)


def _has_file_href(href: str | None) -> bool:
    return bool(href and "filedownload" in href)


def _clean_text(node: Any) -> str:
    if node is None:
        return ""
    return " ".join(str(part).strip() for part in node.stripped_strings).strip()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def _parse_id_from_href(href: str | None, *, parameter: str = "id") -> str | None:
    if not href:
        return None
    query = parse_qs(urlparse(urljoin(constants.BASE_URL, href)).query)
    value = query.get(parameter, [None])[0]
    return value.strip() if value else None


def _field_values(container: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    for strong in container.find_all("strong"):
        label = _clean_text(strong).rstrip(":").casefold()
        sibling = strong.find_next_sibling()
        values[label] = _clean_text(sibling)
    return values


def _listing_card(card: Any, dataset_type: str | None) -> DatasetSummary | None:
    title_node = card.find("h2")
    detail_link = card.find("a", href=_has_detail_href)
    dataset_id = _parse_id_from_href(detail_link.get("href") if detail_link else None)
    title = _clean_text(title_node)
    if not dataset_id or not title:
        return None

    fields = _field_values(card)
    return DatasetSummary(
        id=dataset_id,
        title=title,
        dataset_type=dataset_type,
        released_date=_parse_date(fields.get("date released")),
        modified_date=_parse_date(fields.get("date modified")),
        publisher=fields.get("publisher") or None,
        creator=fields.get("creator") or None,
        landing_page_url=f"{constants.BASE_URL}?page-id=datasetdetails&id={dataset_id}",
    )


def _parse_listing(html: str, dataset_type: str | None) -> list[DatasetSummary]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#Master_ContentPlaceHolder1_DataSets")
    if container is None:
        raise UpstreamError("nl-opendata listing page did not contain its dataset container.")

    cards: list[DatasetSummary] = []
    for card in container.find_all("div", class_="row-fluid well", recursive=False):
        parsed = _listing_card(card, dataset_type)
        if parsed is not None:
            cards.append(parsed)
    return cards


def _parse_tag_list(html: str) -> list[TagSummary]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#tagcontainer")
    if container is None:
        raise UpstreamError("nl-opendata Explore page did not contain its tag container.")

    tags: dict[str, TagSummary] = {}
    for anchor in container.find_all("a", href=_has_tag_href):
        href = anchor.get("href")
        tag_id = _parse_id_from_href(href if isinstance(href, str) else None)
        name = _clean_text(anchor)
        if tag_id and name:
            tags[tag_id] = TagSummary(
                id=tag_id,
                name=name,
                landing_page_url=(f"{constants.BASE_URL}?page-id=datasets-tag&id={tag_id}"),
            )
    return list(tags.values())


def _parse_file(row: Any) -> DatasetFile | None:
    cells = row.find_all("td", recursive=False)
    link = row.find("a", href=_has_file_href)
    file_id = _parse_id_from_href(link.get("href") if link else None, parameter="file-id")
    if len(cells) < 5 or link is None or file_id is None:
        return None

    size_display = _clean_text(cells[4]) or None
    byte_match = re.search(r"\(([\d,]+)\s+bytes\)", size_display or "")
    size_bytes = int(byte_match.group(1).replace(",", "")) if byte_match else None
    return DatasetFile(
        id=file_id,
        title=_clean_text(cells[0]),
        revision=_parse_int(_clean_text(cells[1])),
        format=_clean_text(cells[2]) or None,
        revision_date=_parse_date(_clean_text(cells[3])),
        size_display=size_display,
        size_bytes=size_bytes,
        download_url=urljoin(constants.BASE_URL, link.get("href")),
    )


def _parse_detail(html: str, dataset_id: str) -> DatasetDetail:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#Master_ContentPlaceHolder1_DataSets")
    if container is None:
        # The live detail page omits the listing page's Master_ContentPlaceHolder1_DataSets
        # wrapper and places the metadata in the first .row-fluid > .well instead.
        container = soup.select_one("div.row-fluid > div.well")
    if container is None:
        raise NotFound(f"nl-opendata dataset {dataset_id!r} was not found.")
    title_node = container.find("h2")
    title = _clean_text(title_node)
    if not title:
        raise NotFound(f"nl-opendata dataset {dataset_id!r} was not found.")

    metadata = container.find("dl")
    metadata_values: dict[str, str] = {}
    if metadata is not None:
        for dt in metadata.find_all("dt", recursive=False):
            dd = dt.find_next_sibling("dd")
            metadata_values[_clean_text(dt).rstrip(":").casefold()] = _clean_text(dd)

    tags_container = container.find(id="Master_ContentPlaceHolder1_tags")
    topics = (
        [_clean_text(anchor) for anchor in tags_container.find_all("a")] if tags_container else []
    )
    downloads = container.find(id="Master_ContentPlaceHolder1_downloads")
    files = []
    if downloads is not None:
        table = downloads.find("table")
        if table is not None:
            files = [parsed for row in table.find_all("tr") if (parsed := _parse_file(row))]

    dataset_type = metadata_values.get("type") or None
    return DatasetDetail(
        id=dataset_id,
        title=title,
        dataset_type=dataset_type,
        creator=metadata_values.get("creator") or None,
        contact_email=metadata_values.get("contact email") or None,
        geographic_coverage=metadata_values.get("geographical coverage") or None,
        contributor=metadata_values.get("contributor") or None,
        publisher=metadata_values.get("publisher") or None,
        temporal_coverage=metadata_values.get("temporal coverage") or None,
        released_date=_parse_date(metadata_values.get("released date")),
        modified_date=_parse_date(metadata_values.get("modified date")),
        rights=metadata_values.get("rights") or None,
        topics=topics,
        files=files,
        landing_page_url=f"{constants.BASE_URL}?page-id=datasetdetails&id={dataset_id}",
        licence_url=constants.LICENCE_URL,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}?page-id=datasetdetails&id={dataset_id}",
            cached=False,
            schema_name="nl_opendata.DatasetDetail",
        ),
    )


def _listing_params(dataset_type: str, sort: str, tag_id: str | None = None) -> dict[str, str]:
    if tag_id is not None:
        return {"page-id": "datasets-tag", "id": tag_id}
    if dataset_type not in {"tabular", "spatial"}:
        raise InvalidInput(f"unsupported listing type: {dataset_type!r}")
    if sort == "name":
        return {"page-id": f"datasets-{dataset_type}"}
    if sort == "released_desc":
        return {
            "page-id": f"datasets-{dataset_type}-date",
            "sortby": "datareleased",
            "order": "descending",
        }
    if sort == "released_asc":
        return {
            "page-id": f"datasets-{dataset_type}-date",
            "sortby": "datareleased",
            "order": "ascending",
        }
    raise InvalidInput("sort must be one of: name, released_desc, released_asc.")


def _request_url(params: dict[str, str]) -> str:
    return f"{constants.BASE_URL}?{urlencode(params)}"


def _raise_http_error(exc: httpx.HTTPStatusError, context: str) -> NoReturn:
    status = exc.response.status_code
    detail = exc.response.text.strip().replace("\n", " ")[:200]
    if status == 404:
        raise NotFound(f"{context}: no matching page was found.") from exc
    if 400 <= status < 500:
        raise InvalidInput(f"{context}: the portal rejected the request ({detail}).") from exc
    raise UpstreamError(f"{context} returned HTTP {status}: {detail}") from exc


async def _get_html(params: dict[str, str]) -> str:
    url = constants.BASE_URL
    await _LIMITER.acquire()
    try:
        # The portal's legacy PHP front end occasionally closes a reused
        # keep-alive connection between listing and detail requests. Closing
        # each response is cheap for this small catalogue and avoids turning
        # that server-side behavior into a false upstream outage.
        response = await get_raw(url, params=params, headers={"Connection": "close"})
    except httpx.HTTPStatusError as exc:
        _raise_http_error(exc, f"{constants.RATE_LIMIT_SOURCE}:{params.get('page-id', 'page')}")
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            "Open Data Newfoundland and Labrador did not respond in time "
            "after the shared HTTP retries. Try again shortly."
        ) from exc
    html = response.text
    if not html.strip():
        raise UpstreamError(f"{_request_url(params)} returned an empty response.")
    return html


async def _fetch_listing(
    dataset_type: str,
    *,
    sort: str,
    tag_id: str | None = None,
) -> tuple[list[DatasetSummary], bool]:
    params = _listing_params(dataset_type, sort, tag_id)
    cache_key = f"nl-opendata:listing:{urlencode(params)}"

    async def fetch() -> list[DatasetSummary]:
        html = await _get_html(params)
        return _parse_listing(html, None if tag_id is not None else dataset_type)

    return await cached_fetch(cache_key, constants.CACHE_TTL_LISTING_SECONDS, fetch)


def _sort_results(datasets: list[DatasetSummary], sort: str) -> None:
    if sort == "name":
        datasets.sort(key=lambda item: item.title.casefold())
        return
    datasets.sort(
        key=lambda item: (item.released_date or date.min, item.title.casefold()),
        reverse=sort == "released_desc",
    )


async def search_datasets(
    query: str = "",
    *,
    dataset_type: DatasetType = "all",
    tag_id: str | None = None,
    sort: SortOrder = "name",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> DatasetSearchResult:
    """Search the portal's HTML listing pages, with local pagination."""
    del lang
    if limit < 1 or limit > constants.SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}."
        )
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")
    if dataset_type not in {"all", "tabular", "spatial"}:
        raise InvalidInput("dataset_type must be one of: all, tabular, spatial.")
    if sort not in {"name", "released_desc", "released_asc"}:
        raise InvalidInput("sort must be one of: name, released_desc, released_asc.")
    if tag_id is not None and dataset_type != "all":
        raise InvalidInput("tag_id can only be used with dataset_type='all'.")
    if tag_id is not None and not tag_id.strip():
        raise InvalidInput("tag_id must not be empty.")

    if tag_id is not None:
        pages = [await _fetch_listing("all", sort=sort, tag_id=tag_id)]
    else:
        requested_types = ["tabular", "spatial"] if dataset_type == "all" else [dataset_type]
        pages = [await _fetch_listing(kind, sort=sort) for kind in requested_types]

    datasets_by_id: dict[str, DatasetSummary] = {}
    for page, _was_cached in pages:
        for dataset in page:
            datasets_by_id.setdefault(dataset.id, dataset)
    datasets = list(datasets_by_id.values())

    needle = query.strip().casefold()
    if needle:
        datasets = [
            dataset
            for dataset in datasets
            if needle
            in " ".join(
                part for part in (dataset.title, dataset.publisher or "", dataset.creator or "")
            ).casefold()
        ]
    _sort_results(datasets, sort)

    total_count = len(datasets)
    page = datasets[offset : offset + limit]
    if tag_id is not None:
        provenance_url = _request_url(_listing_params("all", sort, tag_id))
    elif dataset_type == "all":
        provenance_url = constants.BASE_URL
    else:
        provenance_url = _request_url(_listing_params(dataset_type, sort))
    return DatasetSearchResult(
        datasets=page,
        total_count=total_count,
        returned_count=len(page),
        limit=limit,
        offset=offset,
        query=query,
        dataset_type=dataset_type,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=provenance_url,
            cached=all(was_cached for _page, was_cached in pages),
            schema_name="nl_opendata.DatasetSearchResult",
            coverage=f"{len(page)} of {total_count} matching records returned",
            limits=(
                f"local page size capped at {constants.SEARCH_LIMIT_MAX}; "
                "the upstream catalogue has no server-side pagination"
            ),
        ),
    )


async def get_dataset(dataset_id: str, lang: str = "en") -> DatasetDetail:
    del lang
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")
    params = {"page-id": "datasetdetails", "id": dataset_id.strip()}
    cache_key = f"nl-opendata:detail:{dataset_id.strip()}"

    async def fetch() -> str:
        return await _get_html(params)

    html, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_DETAIL_SECONDS, fetch)
    result = _parse_detail(html, dataset_id.strip())
    result.provenance.cached = was_cached
    return result


async def list_tags(lang: str = "en") -> TagList:
    del lang
    params = {"page-id": "explore"}

    async def fetch() -> list[TagSummary]:
        html = await _get_html(params)
        return _parse_tag_list(html)

    tags, was_cached = await cached_fetch(
        "nl-opendata:tags", constants.CACHE_TTL_TAGS_SECONDS, fetch
    )
    return TagList(
        tags=tags,
        total_count=len(tags),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=_request_url(params),
            cached=was_cached,
            schema_name="nl_opendata.TagList",
            freshness="tag vocabulary cached for 24 hours",
        ),
    )
