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
from maplestats_mcp.shared.arg_checks import format_choices
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.i18n import pick
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


def _parse_listing(html: str, dataset_type: str | None, lang: str = "en") -> list[DatasetSummary]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#Master_ContentPlaceHolder1_DataSets")
    if container is None:
        raise_localized(
            UpstreamError,
            "nl-opendata listing page did not contain its dataset container.",
            "la page de liste de nl-opendata ne contient pas son bloc de jeux de données.",
            lang,
        )

    cards: list[DatasetSummary] = []
    for card in container.find_all("div", class_="row-fluid well", recursive=False):
        parsed = _listing_card(card, dataset_type)
        if parsed is not None:
            cards.append(parsed)
    return cards


def _parse_tag_list(html: str, lang: str = "en") -> list[TagSummary]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#tagcontainer")
    if container is None:
        raise_localized(
            UpstreamError,
            "nl-opendata Explore page did not contain its tag container.",
            "la page Explore de nl-opendata ne contient pas son bloc de mots-clés.",
            lang,
        )

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


def _parse_detail(html: str, dataset_id: str, lang: str = "en") -> DatasetDetail:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#Master_ContentPlaceHolder1_DataSets")
    if container is None:
        # The live detail page omits the listing page's Master_ContentPlaceHolder1_DataSets
        # wrapper and places the metadata in the first .row-fluid > .well instead.
        container = soup.select_one("div.row-fluid > div.well")
    if container is None or not _clean_text(container.find("h2")):
        raise_localized(
            NotFound,
            f"nl-opendata dataset {dataset_id!r} was not found.",
            f"le jeu de données nl-opendata {dataset_id!r} est introuvable.",
            lang,
        )
    title = _clean_text(container.find("h2"))

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
            coverage=pick(
                lang,
                "",
                "Titres, métadonnées et noms de fichiers tels que publiés par le portail, en "
                "anglais seulement.",
            )
            or None,
            lang=lang,
        ),
    )


def _listing_params(
    dataset_type: str, sort: str, tag_id: str | None = None, lang: str = "en"
) -> dict[str, str]:
    if tag_id is not None:
        return {"page-id": "datasets-tag", "id": tag_id}
    if dataset_type not in {"tabular", "spatial"}:
        raise_localized(
            InvalidInput,
            f"unsupported listing type: {dataset_type!r}",
            f"type de liste non pris en charge : {dataset_type!r}",
            lang,
        )
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
    raise_localized(
        InvalidInput,
        "sort must be one of: name, released_desc, released_asc.",
        "sort doit valoir name, released_desc ou released_asc.",
        lang,
    )


def _request_url(params: dict[str, str]) -> str:
    return f"{constants.BASE_URL}?{urlencode(params)}"


def _raise_http_error(exc: httpx.HTTPStatusError, context: str, lang: str = "en") -> NoReturn:
    status = exc.response.status_code
    detail = exc.response.text.strip().replace("\n", " ")[:200]
    if status == 404:
        raise_localized(
            NotFound,
            f"{context}: no matching page was found.",
            f"{context} : aucune page correspondante.",
            lang,
        )
    if 400 <= status < 500:
        raise_localized(
            InvalidInput,
            f"{context}: the portal rejected the request ({detail}).",
            f"{context} : le portail a refusé la requête ({detail}).",
            lang,
        )
    raise_localized(
        UpstreamError,
        f"{context} returned HTTP {status}: {detail}",
        f"{context} a répondu par une erreur HTTP {status} : {detail}",
        lang,
    )


async def _get_html(params: dict[str, str], lang: str = "en") -> str:
    url = constants.BASE_URL
    await _LIMITER.acquire()
    try:
        # The portal's legacy PHP front end occasionally closes a reused
        # keep-alive connection between listing and detail requests. Closing
        # each response is cheap for this small catalogue and avoids turning
        # that server-side behavior into a false upstream outage.
        response = await get_raw(url, params=params, headers={"Connection": "close"})
    except httpx.HTTPStatusError as exc:
        _raise_http_error(
            exc, f"{constants.RATE_LIMIT_SOURCE}:{params.get('page-id', 'page')}", lang
        )
    except httpx.HTTPError:
        raise_localized(
            UpstreamUnavailable,
            "Open Data Newfoundland and Labrador did not respond in time "
            "after the shared HTTP retries. Try again shortly.",
            "le portail de données ouvertes de Terre-Neuve-et-Labrador n'a pas répondu à "
            "temps malgré les nouvelles tentatives. Réessayez sous peu.",
            lang,
        )
    html = response.text
    if not html.strip():
        raise_localized(
            UpstreamError,
            f"{_request_url(params)} returned an empty response.",
            f"{_request_url(params)} a renvoyé une réponse vide.",
            lang,
        )
    return html


async def _fetch_listing(
    dataset_type: str,
    *,
    sort: str,
    tag_id: str | None = None,
    lang: str = "en",
) -> tuple[list[DatasetSummary], bool]:
    params = _listing_params(dataset_type, sort, tag_id, lang)
    cache_key = f"nl-opendata:listing:{urlencode(params)}"

    async def fetch() -> list[DatasetSummary]:
        html = await _get_html(params, lang)
        return _parse_listing(html, None if tag_id is not None else dataset_type, lang)

    return await cached_fetch(cache_key, constants.CACHE_TTL_LISTING_SECONDS, fetch)


def _sort_results(datasets: list[DatasetSummary], sort: str) -> None:
    if sort == "name":
        datasets.sort(key=lambda item: item.title.casefold())
        return
    datasets.sort(
        key=lambda item: (item.released_date or date.min, item.title.casefold()),
        reverse=sort == "released_desc",
    )


async def _with_types(
    datasets: list[DatasetSummary], lang: str = "en"
) -> tuple[list[DatasetSummary], int]:
    """Fill dataset_type from the tabular and spatial listings (the tag page has none).

    Returns the datasets and how many stayed untyped.
    """
    kinds: dict[str, str] = {}
    for kind in ("tabular", "spatial"):
        page, _ = await _fetch_listing(kind, sort="name", lang=lang)
        for dataset in page:
            kinds.setdefault(dataset.id, kind)
    typed = [d.model_copy(update={"dataset_type": kinds.get(d.id)}) for d in datasets]
    return typed, sum(1 for d in typed if d.dataset_type is None)


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
    checks = [
        (
            limit < 1 or limit > constants.SEARCH_LIMIT_MAX,
            f"limit must be between 1 and {constants.SEARCH_LIMIT_MAX}, got {limit}.",
            f"limit doit être compris entre 1 et {constants.SEARCH_LIMIT_MAX} (reçu {limit}).",
        ),
        (
            offset < 0,
            f"offset must be >= 0, got {offset}.",
            f"offset doit être égal ou supérieur à 0 (reçu {offset}).",
        ),
        (
            dataset_type not in {"all", "tabular", "spatial"},
            "dataset_type must be one of: all, tabular, spatial.",
            "dataset_type doit valoir all, tabular ou spatial.",
        ),
        (
            sort not in {"name", "released_desc", "released_asc"},
            "sort must be one of: name, released_desc, released_asc.",
            "sort doit valoir name, released_desc ou released_asc.",
        ),
        (
            tag_id is not None and dataset_type != "all",
            "tag_id can only be used with dataset_type='all'.",
            "tag_id ne s'emploie qu'avec dataset_type='all'.",
        ),
        (
            tag_id is not None and not tag_id.strip(),
            "tag_id must not be empty.",
            "tag_id ne doit pas être vide.",
        ),
    ]
    for failed, en, fr in checks:
        if failed:
            raise_localized(InvalidInput, en, fr, lang)

    if tag_id is not None:
        tag_id = tag_id.strip()
        pages = [await _fetch_listing("all", sort=sort, tag_id=tag_id, lang=lang)]
        if not pages[0][0]:
            # An unknown tag id answers an empty listing, not an error.
            known = {tag.id: tag.name for tag in (await list_tags(lang)).tags}
            if tag_id.strip() not in known:
                choices = format_choices(f"{i}: {n}" for i, n in sorted(known.items()))
                raise_localized(
                    InvalidInput,
                    f"tag_id {tag_id!r} is not a tag on the portal. Tags (id: name): "
                    + choices
                    + ". See nl_opendata_list_tags.",
                    f"tag_id {tag_id!r} n'est pas un mot-clé du portail. Mots-clés (id : nom) : "
                    + choices
                    + ". Voir nl_opendata_list_tags.",
                    lang,
                )
    else:
        requested_types = ["tabular", "spatial"] if dataset_type == "all" else [dataset_type]
        pages = [await _fetch_listing(kind, sort=sort, lang=lang) for kind in requested_types]

    datasets_by_id: dict[str, DatasetSummary] = {}
    for page, _was_cached in pages:
        for dataset in page:
            datasets_by_id.setdefault(dataset.id, dataset)
    datasets = list(datasets_by_id.values())

    untyped = 0
    if tag_id is not None and datasets:
        datasets, untyped = await _with_types(datasets, lang)

    words = query.casefold().split()
    if words:
        datasets = [
            dataset
            for dataset in datasets
            if all(
                word
                in " ".join(
                    part for part in (dataset.title, dataset.publisher or "", dataset.creator or "")
                ).casefold()
                for word in words
            )
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
            coverage=pick(
                lang,
                f"{len(page)} of {total_count} matching records returned"
                + (
                    f"; {untyped} tagged dataset(s) are in neither the tabular nor the spatial "
                    "listing, so their dataset_type is null"
                    if untyped
                    else ""
                ),
                f"{len(page)} jeux de données renvoyés sur {total_count} correspondants"
                + (
                    f" ; {untyped} jeu(x) de données associé(s) au mot-clé ne figure(nt) ni dans "
                    "la liste tabulaire ni dans la liste spatiale : leur dataset_type est nul"
                    if untyped
                    else ""
                )
                + ". Titres et métadonnées en anglais seulement, comme sur le portail.",
            ),
            limits=pick(
                lang,
                f"local page size capped at {constants.SEARCH_LIMIT_MAX}; "
                "the upstream catalogue has no server-side pagination",
                f"taille de page locale limitée à {constants.SEARCH_LIMIT_MAX} ; le catalogue "
                "source n'a pas de pagination côté serveur",
            ),
            lang=lang,
        ),
    )


async def get_dataset(dataset_id: str, lang: str = "en") -> DatasetDetail:
    if not dataset_id.strip():
        raise_localized(
            InvalidInput,
            "dataset_id must not be empty.",
            "dataset_id ne doit pas être vide.",
            lang,
        )
    params = {"page-id": "datasetdetails", "id": dataset_id.strip()}
    cache_key = f"nl-opendata:detail:{dataset_id.strip()}"

    async def fetch() -> str:
        return await _get_html(params, lang)

    html, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_DETAIL_SECONDS, fetch)
    result = _parse_detail(html, dataset_id.strip(), lang)
    result.provenance.cached = was_cached
    return result


_TAGS_PARAMS = {"page-id": "explore"}


async def _tags(lang: str = "en") -> tuple[list[TagSummary], bool]:
    async def fetch() -> list[TagSummary]:
        html = await _get_html(_TAGS_PARAMS, lang)
        return _parse_tag_list(html, lang)

    return await cached_fetch("nl-opendata:tags", constants.CACHE_TTL_TAGS_SECONDS, fetch)


async def list_tags(lang: str = "en") -> TagList:
    params = _TAGS_PARAMS
    tags, was_cached = await _tags(lang)
    return TagList(
        tags=tags,
        total_count=len(tags),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=_request_url(params),
            cached=was_cached,
            schema_name="nl_opendata.TagList",
            freshness=pick(
                lang,
                "tag vocabulary cached for 24 hours",
                "vocabulaire des mots-clés conservé en cache 24 heures ; mots-clés en anglais, "
                "comme sur le portail",
            ),
            lang=lang,
        ),
    )
