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
  links are every leaf table in that category (72 listed live across
  the two categories that have them: 20 for rental-market, 52 for
  household-characteristics). Two page templates exist; see
  `_parse_table_detail`.
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
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from defusedxml import ElementTree

from maplestats_mcp.modules.cmhc.data_tables import constants
from maplestats_mcp.modules.cmhc.data_tables.schemas import (
    DownloadLink,
    EditionOption,
    GeographyOption,
    TableDetail,
    TableList,
    TableSummary,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.http import api_get, get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_XHTML_NS = "http://www.w3.org/1999/xhtml"


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
    english = {fr: en for en, fr in constants.FRENCH_CATEGORIES.items()}
    category = english.get(category, category)
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


def _clean(text: str) -> str:
    """Collapse runs of whitespace: titles carry doubled and trailing spaces
    upstream ("Number  of Units", "Vacancy  Rates")."""
    return " ".join(text.split())


def _parse_table_list(body: str, category: str) -> list[TableSummary]:
    soup = BeautifulSoup(body, "html.parser")
    prefix = f"{constants.DATA_TABLES_PATH}/{category}/"
    seen: dict[str, TableSummary] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if not isinstance(href, str) or not href.startswith(prefix):
            continue
        title = _clean(anchor.get_text(" "))
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
        label = _clean(option.get_text(" "))
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
    text = _clean(element.get_text(" ")) if element is not None else ""
    return text or None


def _definition_list(soup: BeautifulSoup) -> dict[str, str]:
    """The landing block's <dl>: "Author:", "Document Type:", "Date Published:"
    (French: "Auteur :", "Type de document :", "Date de publication :")."""
    pairs: dict[str, str] = {}
    for term in soup.select("div.pdf-landing dt"):
        definition = term.find_next_sibling("dd")
        if definition is not None:
            key = _clean(term.get_text(" ")).rstrip(": ").lower()
            pairs[key] = _clean(definition.get_text(" "))
    return pairs


def _alternate_url(soup: BeautifulSoup, lang: str) -> str | None:
    link = soup.find("link", attrs={"rel": "alternate", "hreflang": lang})
    href = link.get("href") if link is not None else None
    return href if isinstance(href, str) and href else None


def _parse_table_detail(body: str, category: str, slug: str) -> dict[str, Any]:
    """Read a table page. Two page templates were found live (2026-10-03):

    - edition pages (20 of 72 tables): `#DataSource`, `#pdf_geo` and
      `#pdf_edition` selects, resolved through GetFileDetails;
    - single-file report pages (52 of 72: every rural-rental, percentile-rent
      and seniors-rental table, and 43 household-characteristics tables):
      no selects, a hidden `#document-id` GUID and a "Download" link whose
      href the site's script fills from
      GetReportFileUrl?documentId=...&contextLanguage=... (found in
      cmhc-custom.js). These used to fail with "no #DataSource value".
    """
    soup = BeautifulSoup(body, "html.parser")
    title_tag = soup.find("h1")
    title = _clean(title_tag.get_text(" ")) if title_tag else ""
    if not title:
        raise NotFound(f"CMHC data table {category}/{slug} was not found.")

    description_container = soup.select_one("div.pdf-landing")
    description = ""
    if description_container is not None:
        paragraph = description_container.find("p")
        if paragraph is not None:
            description = _clean(paragraph.get_text(" "))

    data_source = _input_value(soup, "DataSource")
    document_id = _input_value(soup, "document-id")
    if not data_source and not document_id:
        raise UpstreamError(
            f"CMHC data table {category}/{slug}: the page has neither a #DataSource nor a "
            "#document-id value to resolve its download with; the layout may have changed."
        )

    terms = _definition_list(soup)
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
        "document_id": None if data_source else document_id,
        "author": _text_value(soup, "AuthorTag") or terms.get("author") or terms.get("auteur"),
        "document_type": _text_value(soup, "DocumentTag")
        or terms.get("document type")
        or terms.get("type de document"),
        "date_published": _text_value(soup, "DatePublishedTag")
        or terms.get("date published")
        or terms.get("date de publication"),
        "geographies": geographies,
        "editions": editions,
        "default_download_url": _input_value(soup, "document-url"),
        "french_url": _alternate_url(soup, "fr"),
    }


def _table_url(category: str, slug: str) -> str:
    return f"{constants.BASE_URL}{constants.DATA_TABLES_PATH}/{category}/{slug}"


async def _report_file_url(document_id: str, lang: str) -> str | None:
    """The single file of a report-template table, in `lang`."""

    async def fetch() -> str:
        body = await _get_json(
            constants.GET_REPORT_FILE_URL, {"documentId": document_id, "contextLanguage": lang}
        )
        return body if isinstance(body, str) else ""

    url, _ = await cached_fetch(
        f"cmhc-dt:report-file:{document_id}:{lang}", constants.CACHE_TTL_DOWNLOAD_SECONDS, fetch
    )
    return urljoin(constants.BASE_URL, url) if url else None


def _sitemap_pairs(body: str) -> dict[str, str]:
    """English data-table path -> French path, from the sitemap's hreflang alternates."""
    root = ElementTree.fromstring(body.lstrip("\N{ZERO WIDTH NO-BREAK SPACE}").encode())
    english_prefix = f"{constants.BASE_URL}/en{constants.DATA_TABLES_PATH}/"
    french_prefix = f"{constants.BASE_URL}/fr"
    pairs: dict[str, str] = {}
    for entry in root.iter(f"{{{_SITEMAP_NS}}}url"):
        alternates = {
            link.get("hreflang"): link.get("href") or ""
            for link in entry.iter(f"{{{_XHTML_NS}}}link")
        }
        english, french = alternates.get("en", ""), alternates.get("fr", "")
        if english.startswith(english_prefix) and french.startswith(french_prefix + "/"):
            english_path = english[len(constants.BASE_URL) + len("/en") :].rstrip("/")
            pairs[english_path] = french[len(french_prefix) :].rstrip("/")
    return pairs


async def _pairing() -> tuple[dict[str, str], bool]:
    async def fetch() -> dict[str, str]:
        body = await _get_html(constants.SITEMAP_URL)
        pairs = await run_parse(_sitemap_pairs, body)
        if not pairs:
            raise UpstreamError(f"{constants.SITEMAP_URL} lists no data table pages.")
        return pairs

    return await cached_fetch("cmhc-dt:pairing", constants.CACHE_TTL_PAIRING_SECONDS, fetch)


def _last_segment(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


async def _english_slug(category: str, slug: str) -> str | None:
    """The English slug of a table given its French slug, if CMHC pairs them."""
    pairs, _ = await _pairing()
    prefix = f"{constants.DATA_TABLES_PATH}/{category}/"
    for english, french in pairs.items():
        if english.startswith(prefix) and _last_segment(french) == slug:
            return english[len(prefix) :]
    return None


def _parse_french_titles(body: str, prefix: str) -> dict[str, str]:
    """French path -> title, for paths whose listing links all say the same.

    The French listing has 52 links to 50 pages (live 2026-10-03): some
    pages are linked twice, once under another table's title ("Ménages
    selon le type..." on the household count and size table, "médian" on
    the average after-tax income table) or with a title split over two
    links ("à"). Those paths are left out, and their title is read from
    the French page itself.
    """
    soup = BeautifulSoup(body, "html.parser")
    texts: dict[str, set[str]] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if isinstance(href, str) and href.startswith(prefix):
            title = _clean(anchor.get_text(" "))
            if title:
                texts.setdefault(href.rstrip("/"), set()).add(title)
    return {path: titles.pop() for path, titles in texts.items() if len(titles) == 1}


async def _french_titles(category: str) -> tuple[dict[str, str], bool]:
    """French listing of a category: French path -> French title."""
    french_category = constants.FRENCH_CATEGORIES[category]
    url = f"{constants.BASE_URL}{constants.FR_DATA_TABLES_PATH}/{french_category}"

    async def fetch() -> dict[str, str]:
        body = await _get_html(url)
        return _parse_french_titles(body, f"{constants.FR_DATA_TABLES_PATH}/{french_category}/")

    return await cached_fetch(
        f"cmhc-dt:list_tables_fr:{category}", constants.CACHE_TTL_LISTING_SECONDS, fetch
    )


async def _french_path(category: str, table: TableSummary, pairs: dict[str, str]) -> str | None:
    french = pairs.get(table.path.rstrip("/"))
    if french:
        return french
    # Not in the sitemap (a table added since): the English page's own
    # language switch, read from its hreflang link.
    try:
        parsed, _ = await _parsed_page(
            _table_url(category, table.slug),
            f"cmhc-dt:table:{category}:{table.slug}",
            category,
            table.slug,
        )
    except (NotFound, UpstreamError):
        return None
    french_url = parsed.get("french_url")
    return urlparse(french_url).path.rstrip("/") if french_url else None


async def _french_summaries(
    category: str, tables: list[TableSummary]
) -> tuple[list[TableSummary], str | None, bool]:
    """Each English table as its French twin: French slug, title and path."""
    pairs, pairs_cached = await _pairing()
    titles, titles_cached = await _french_titles(category)
    summaries: list[TableSummary] = []
    missing: list[str] = []
    for table in tables:
        french_path = await _french_path(category, table, pairs)
        title = titles.get(french_path) if french_path else None
        if french_path and title is None:
            # Two household-characteristics tables have a French page that
            # the French listing leaves out (50 pages listed against 52,
            # live 2026-10-03), and a few listing titles are ambiguous:
            # read the title from the French page itself.
            try:
                page, _ = await _parsed_page(
                    constants.BASE_URL + french_path,
                    f"cmhc-dt:table-fr:{category}:{table.slug}",
                    category,
                    table.slug,
                )
                title = page["title"]
            except (NotFound, UpstreamError):
                title = None
        if not french_path or not title:
            missing.append(table.slug)
            note = "No French page found for this table: English title and slug."
            summaries.append(table.model_copy(update={"english_slug": table.slug, "note": note}))
            continue
        summaries.append(
            TableSummary(
                category=category,
                slug=_last_segment(french_path),
                title=title,
                path=french_path,
                english_slug=table.slug,
            )
        )
    note = (
        f"{len(missing)} table(s) have no French page and keep their English title: "
        + ", ".join(missing)
        if missing
        else None
    )
    return summaries, note, pairs_cached and titles_cached


async def list_tables(category: str, *, lang: str = "en") -> TableList:
    # The French listing pages use other slugs and list a different number
    # of tables (50 against 52 for household characteristics, live
    # 2026-10-03), so French titles are paired through CMHC's own English
    # to French links, not matched by title.
    if lang not in ("en", "fr"):
        raise InvalidInput(f"lang must be 'en' or 'fr', got {lang!r}.")
    category = _require_category(category)
    url = f"{constants.BASE_URL}{constants.DATA_TABLES_PATH}/{category}"
    cache_key = f"cmhc-dt:list_tables:{category}"

    async def fetch() -> list[TableSummary]:
        body = await _get_html(url)
        return _parse_table_list(body, category)

    tables, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_LISTING_SECONDS, fetch)
    note = None
    if lang == "fr" and tables:
        tables, note, french_cached = await _french_summaries(category, tables)
        was_cached = was_cached and french_cached
    return TableList(
        category=category,
        tables=tables,
        total_count=len(tables),
        note=note,
        provenance=make_provenance(
            source="cmhc-dt",
            url=url,
            cached=was_cached,
            schema_name="cmhc.data_tables.TableList",
        ),
    )


async def _parsed_page(
    url: str, cache_key: str, category: str, slug: str
) -> tuple[dict[str, Any], bool]:
    async def fetch() -> dict[str, Any]:
        body = await _get_html(url)
        return _parse_table_detail(body, category, slug)

    return await cached_fetch(cache_key, constants.CACHE_TTL_TABLE_SECONDS, fetch)


async def get_table(category: str, slug: str, *, lang: str = "en") -> TableDetail:
    if lang not in ("en", "fr"):
        raise InvalidInput(f"lang must be 'en' or 'fr', got {lang!r}.")
    category = _require_category(category)
    slug = _require(slug, "slug")
    try:
        parsed, was_cached = await _parsed_page(
            _table_url(category, slug), f"cmhc-dt:table:{category}:{slug}", category, slug
        )
    except NotFound:
        # A French slug (from cmhc_dt_list_tables with lang="fr") is not an
        # English page: read its English twin.
        english = await _english_slug(category, slug)
        if english is None:
            raise
        slug = english
        parsed, was_cached = await _parsed_page(
            _table_url(category, slug), f"cmhc-dt:table:{category}:{slug}", category, slug
        )
    url = _table_url(category, slug)
    page_url = url
    shown = parsed
    if lang == "fr" and parsed.get("french_url"):
        # The French page is the same Sitecore item (same geography and
        # edition ids), with French title, description and labels.
        page_url = parsed["french_url"]
        shown, was_cached = await _parsed_page(
            page_url, f"cmhc-dt:table-fr:{category}:{slug}", category, slug
        )
    default_url = shown["default_download_url"]
    # A single-file table's French page has its own document id; the
    # English id gives the English file whatever contextLanguage says
    # (table_23_..._en_w.xls for both, live 2026-10-03).
    document_id = shown.get("document_id") or parsed["document_id"]
    if document_id:
        default_url = await _report_file_url(document_id, lang)
    french_url = parsed.get("french_url")
    return TableDetail(
        category=category,
        slug=slug,
        french_slug=_last_segment(urlparse(french_url).path) if french_url else None,
        title=shown["title"],
        description=shown["description"],
        data_source=parsed["data_source"],
        document_id=document_id,
        author=shown["author"],
        document_type=shown["document_type"],
        date_published=shown["date_published"],
        geographies=shown["geographies"] or parsed["geographies"],
        editions=shown["editions"] or parsed["editions"],
        default_download_url=default_url,
        provenance=make_provenance(
            source="cmhc-dt",
            url=page_url,
            cached=was_cached,
            schema_name="cmhc.data_tables.TableDetail",
        ),
    )


def _file_name(url: str) -> str:
    return unquote(urlparse(url).path.rsplit("/", 1)[-1])


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
    slug = table.slug  # the English slug when a French one was given
    if table.document_id:
        if geography_id is not None or edition_id is not None:
            raise InvalidInput(
                f"CMHC data table {category}/{slug} is a single file with no geography or "
                "edition options; call it without geography_id and edition_id."
            )
        if not table.default_download_url:
            raise NotFound(f"CMHC has no published file for {category}/{slug} in {lang!r}.")
        return DownloadLink(
            document_url=table.default_download_url,
            file_name=_file_name(table.default_download_url),
            author=table.author,
            document_type=table.document_type,
            date_published=table.date_published,
            geography_id=None,
            edition_id=None,
            provenance=make_provenance(
                source="cmhc-dt",
                url=constants.GET_REPORT_FILE_URL,
                cached=table.provenance.cached,
                schema_name="cmhc.data_tables.DownloadLink",
            ),
        )
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
    document_url = urljoin(constants.BASE_URL, details["DocumentUrl"])
    return DownloadLink(
        document_url=document_url,
        # FileName and ProductType come back null; the site's own script reads
        # DocumentType, and the file name is the URL's last segment.
        file_name=details.get("FileName") or _file_name(document_url),
        author=details.get("Author") or None,
        document_type=details.get("DocumentType") or details.get("ProductType") or None,
        date_published=details.get("DatePublished") or None,
        geography_id=geography_id,
        edition_id=edition_id,
        provenance=make_provenance(
            source="cmhc-dt",
            url=str(httpx.URL(constants.GET_FILE_DETAILS_URL, params=params)),
            cached=was_cached,
            schema_name="cmhc.data_tables.DownloadLink",
        ),
    )
