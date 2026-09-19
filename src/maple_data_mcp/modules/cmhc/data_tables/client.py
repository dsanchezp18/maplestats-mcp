"""HTTP client for CMHC's "Data Tables" document catalogue (www.cmhc-schl.gc.ca).

Every function wraps `shared.http.get_raw`/`api_get` through the
cmhc-dt rate limiter and either returns a typed model or raises a
`shared/errors.py` exception. The following was confirmed live this
session against https://www.cmhc-schl.gc.ca (a Sitecore Experience
Platform site, unrelated to the rest of modules/cmhc/'s HMIP legacy
ASP.NET app):

- `GET {DATA_TABLES_PATH}` -> 301-redirects to a category-overview page
  whose links confirm exactly the three categories in
  constants.KNOWN_CATEGORIES. `canadian-housing-survey-data-tables`
  only cross-links the other two categories on its own page (confirmed
  live) rather than hosting leaf tables under its own path -
  `list_tables` returns an empty list for it rather than guessing at an
  unconfirmed URL structure for wherever its tables actually live.
- `GET {DATA_TABLES_PATH}/{category}` -> an accordion-style listing
  page whose `<a href="{DATA_TABLES_PATH}/{category}/{slug}">Title</a>`
  links are every leaf table in that category (72 confirmed live across
  the two categories that have them: 20 for rental-market, 52 for
  household-characteristics).
- `GET {DATA_TABLES_PATH}/{category}/{slug}` -> one table's detail page.
  Confirmed live, all present directly in the static HTML with no JS
  execution required:
  * `<div class="pdf-landing">`'s first `<p>` is the table's
    description.
  * `#AuthorTag`/`#DocumentTag`/`#DatePublishedTag` hold author/
    document type/publish date as plain text.
  * `<input id="DataSource" value="/sitecore/content/CMHC/Sites/Main/
    Home{DATA_TABLES_PATH}/{category}/{slug}">` -- a Sitecore item
    *path* (not an opaque GUID), identical to the table's own URL -
    this is what `dataSource` means on the resolver API below.
  * `<select id="pdf_geo">`/`<select id="pdf_edition">` list every
    geography/edition option as `<option value="{SITECORE-GUID}">
    Label</option>` - neither confirmed to mark a `selected` option, so
    (standard `<select>` semantics, confirmed live) the *first* `<option>`
    in each is the default/most-recent one.
  * `<input id="document-url" value="https://assets.cmhc-schl.gc.ca/...
    .xlsx?rev=...">` -- the resolved download link for the *default*
    geography+edition, already present in the raw HTML. (A separate
    `<a id="download-periodical" href="#">` is what client-side JS
    copies this into on page load - `get_table` below reads the hidden
    input directly instead, so no JS execution is needed.)
- `GET /api/Sitecore/PubsAndReports/GetFileDetails?cityId={geoGUID}&
  edition={editionGUID}&dataSource={itemPath}&contextLanguage={lang}`
  -> `{FileName, Author, DatePublished, IdNumber, Thumbnail,
  ProductType, DocumentUrl}`. This is the real resolver API this site's
  own geography/edition dropdowns call (found via live network-request
  inspection of the rendered page, not documentation) - confirmed live
  end-to-end for a non-default edition (October 2022, returning a
  different `DocumentUrl` than the page's own default October 2023
  link). `get_download_url` below always calls this (even for the
  default geography/edition) rather than only reading the static
  `#document-url` value, for one consistent code path with richer
  metadata (Author/FileName/DatePublished) than the bare hidden input
  provides.
- Unlike the rest of modules/cmhc/, this site is a normal UTF-8-
  declared, UTF-8-encoded site (confirmed live against the raw response
  bytes) - no cp1252/latin-1 quirk here; that quirk is specific to
  HMIP's CSV export, not this Sitecore site.
- No numeric rate limit is published - see constants.py for the
  conservative default used.
"""

from __future__ import annotations

from typing import Any, NoReturn
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from maple_data_mcp.modules.cmhc.data_tables import constants
from maple_data_mcp.modules.cmhc.data_tables.schemas import (
    DownloadLink,
    EditionOption,
    GeographyOption,
    TableDetail,
    TableList,
    TableSummary,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import api_get, get_raw
from maple_data_mcp.shared.rate_limiter import get_limiter


def _limiter():
    return get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    )


def _require(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise InvalidInput(f"{name} must not be empty.")
    return value


def _require_category(category: str) -> str:
    category = _require(category, "category")
    if category not in constants.KNOWN_CATEGORIES:
        raise InvalidInput(
            f"category must be one of {constants.KNOWN_CATEGORIES}, got {category!r}."
        )
    return category


def _raise_for_status(exc: httpx.HTTPStatusError, context: str) -> NoReturn:
    status = exc.response.status_code
    if status == 404:
        raise NotFound(f"{context}: not found.") from exc
    if status == 400:
        raise InvalidInput(f"{context}: rejected the request (HTTP 400).") from exc
    raise UpstreamError(f"{context}: upstream returned HTTP {status}.") from exc


async def _get_html(url: str, params: dict[str, Any] | None = None) -> str:
    await _limiter().acquire()
    try:
        response = await get_raw(url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status(exc, url)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{url} did not respond in time (already retried by shared/http.py)."
        ) from exc
    return response.text


async def _get_json(url: str, params: dict[str, Any]) -> Any:
    await _limiter().acquire()
    try:
        return await api_get(url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status(exc, url)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"{url} did not respond in time (already retried by shared/http.py)."
        ) from exc


def _parse_table_list(body: str, category: str) -> list[TableSummary]:
    soup = BeautifulSoup(body, "html.parser")
    prefix = f"{constants.DATA_TABLES_PATH}/{category}/"
    seen: dict[str, TableSummary] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if not isinstance(href, str) or not href.startswith(prefix):
            continue
        title = anchor.get_text(strip=True)
        if not title:
            continue
        slug = href[len(prefix) :].strip("/")
        if not slug or "/" in slug:
            continue
        seen.setdefault(slug, TableSummary(category=category, slug=slug, title=title, path=href))
    return list(seen.values())


def _select_options(soup: BeautifulSoup, select_id: str) -> list[tuple[str, str]]:
    select = soup.find("select", id=select_id)
    if select is None:
        return []
    options: list[tuple[str, str]] = []
    for option in select.find_all("option"):
        value = option.get("value")
        label = option.get_text(strip=True)
        if isinstance(value, str) and value and label:
            options.append((value, label))
    return options


def _input_value(soup: BeautifulSoup, element_id: str) -> str | None:
    element = soup.find(id=element_id)
    if element is None:
        return None
    value = element.get("value")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _text_value(soup: BeautifulSoup, element_id: str) -> str | None:
    element = soup.find(id=element_id)
    text = element.get_text(strip=True) if element is not None else ""
    return text or None


def _parse_table_detail(body: str, category: str, slug: str) -> dict[str, Any]:
    soup = BeautifulSoup(body, "html.parser")
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else ""
    if not title:
        raise NotFound(f"CMHC data table {category}/{slug} was not found.")

    description_container = soup.select_one("div.pdf-landing")
    description = ""
    if description_container is not None:
        paragraph = description_container.find("p")
        if paragraph is not None:
            description = paragraph.get_text(strip=True)

    data_source = _input_value(soup, "DataSource")
    if not data_source:
        raise UpstreamError(
            f"CMHC data table {category}/{slug}: page had no #DataSource value to resolve downloads with."
        )

    geographies = [
        GeographyOption(id=value, name=label) for value, label in _select_options(soup, "pdf_geo")
    ]
    editions = [
        EditionOption(id=value, label=label)
        for value, label in _select_options(soup, "pdf_edition")
    ]

    return {
        "title": title,
        "description": description,
        "data_source": data_source,
        "document_type": _text_value(soup, "DocumentTag"),
        "date_published": _text_value(soup, "DatePublishedTag"),
        "geographies": geographies,
        "editions": editions,
        "default_download_url": _input_value(soup, "document-url"),
    }


def _table_url(category: str, slug: str) -> str:
    return f"{constants.BASE_URL}{constants.DATA_TABLES_PATH}/{category}/{slug}"


async def list_tables(category: str, *, lang: str = "en") -> TableList:
    del lang  # this site's category/table URLs are language-neutral; see module docstring
    category = _require_category(category)
    url = f"{constants.BASE_URL}{constants.DATA_TABLES_PATH}/{category}"
    cache_key = f"cmhc-dt:list_tables:{category}"

    async def fetch() -> list[TableSummary]:
        body = await _get_html(url)
        return _parse_table_list(body, category)

    tables, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_LISTING_SECONDS, fetch)
    return TableList(
        category=category,
        tables=tables,
        total_count=len(tables),
        provenance=make_provenance(
            source="cmhc-dt",
            url=url,
            cached=was_cached,
            schema_name="cmhc.data_tables.TableList",
        ),
    )


async def get_table(category: str, slug: str, *, lang: str = "en") -> TableDetail:
    del lang
    category = _require_category(category)
    slug = _require(slug, "slug")
    url = _table_url(category, slug)
    cache_key = f"cmhc-dt:table:{category}:{slug}"

    async def fetch() -> dict[str, Any]:
        body = await _get_html(url)
        return _parse_table_detail(body, category, slug)

    parsed, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_TABLE_SECONDS, fetch)
    return TableDetail(
        category=category,
        slug=slug,
        title=parsed["title"],
        description=parsed["description"],
        data_source=parsed["data_source"],
        document_type=parsed["document_type"],
        date_published=parsed["date_published"],
        geographies=parsed["geographies"],
        editions=parsed["editions"],
        default_download_url=parsed["default_download_url"],
        provenance=make_provenance(
            source="cmhc-dt",
            url=url,
            cached=was_cached,
            schema_name="cmhc.data_tables.TableDetail",
        ),
    )


async def get_download_url(
    category: str,
    slug: str,
    *,
    geography_id: str | None = None,
    edition_id: str | None = None,
    lang: str = "en",
) -> DownloadLink:
    if lang not in ("en", "fr"):
        raise InvalidInput(f"lang must be 'en' or 'fr', got {lang!r}.")
    table = await get_table(category, slug, lang=lang)
    if geography_id is None:
        if not table.geographies:
            raise NotFound(f"CMHC data table {category}/{slug} has no geography options.")
        geography_id = table.geographies[0].id
    if edition_id is None:
        if not table.editions:
            raise NotFound(f"CMHC data table {category}/{slug} has no edition options.")
        edition_id = table.editions[0].id

    known_geo_ids = {g.id for g in table.geographies}
    known_edition_ids = {e.id for e in table.editions}
    if geography_id not in known_geo_ids:
        raise InvalidInput(
            f"geography_id {geography_id!r} is not a valid option for {category}/{slug} "
            f"(known ids: {sorted(known_geo_ids)})."
        )
    if edition_id not in known_edition_ids:
        raise InvalidInput(
            f"edition_id {edition_id!r} is not a valid option for {category}/{slug} "
            f"(known ids: {sorted(known_edition_ids)})."
        )

    params = {
        "cityId": geography_id,
        "edition": edition_id,
        "dataSource": table.data_source,
        "contextLanguage": lang,
    }
    cache_key = f"cmhc-dt:download:{category}:{slug}:{geography_id}:{edition_id}:{lang}"

    async def fetch() -> dict[str, Any]:
        body = await _get_json(constants.GET_FILE_DETAILS_URL, params)
        if not isinstance(body, dict) or not body.get("DocumentUrl"):
            raise NotFound(
                f"CMHC has no published file for {category}/{slug} at geography_id="
                f"{geography_id!r}, edition_id={edition_id!r}."
            )
        return body

    details, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_DOWNLOAD_SECONDS, fetch)
    return DownloadLink(
        document_url=urljoin(constants.BASE_URL, details["DocumentUrl"]),
        file_name=details.get("FileName") or None,
        author=details.get("Author") or None,
        document_type=details.get("ProductType") or None,
        date_published=details.get("DatePublished") or None,
        geography_id=geography_id,
        edition_id=edition_id,
        provenance=make_provenance(
            source="cmhc-dt",
            url=constants.GET_FILE_DETAILS_URL,
            cached=was_cached,
            schema_name="cmhc.data_tables.DownloadLink",
        ),
    )
