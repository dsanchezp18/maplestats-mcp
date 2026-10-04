"""Parse the OEB open data listing and dataset pages (Drupal, read 2026-10-03).

Listing rows are `.views-row` blocks: title link `/open-data/<slug>`, a body
paragraph and "Update Frequency". A dataset page has Drupal fields:
`field--name-body` (description), `field--name-field-wysiwyg-url` (the files),
`field--name-field-file-types`, `field--name-field-update-frequency` and
`field--name-field-update-frequency-note` ("Last updated: April 30, 2026", or
"2026-08-28" on the mapping page).

Inside the URL field the current files come first; archived releases follow,
each introduced by "Data published <Month D, YYYY>" (one page writes "Date
published"), in a <details><summary> on most pages and in a plain paragraph on
others. Walking the field in document order and keeping the last such date
assigns every link to its release either way. Two pages link only to another
oeb.ca page that holds the files (the distribution rates databases and the
intervenor cost awards); those links are returned as `hops` for the client to
follow once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from maplestats_mcp.modules.oeb import constants

_PUBLISHED = re.compile(r"Dat[ae] published\s+([A-Z][a-z]+\.? \d{1,2},? \d{4})")
_FILE_EXT = re.compile(r"\.(xml|xlsx|xls|csv|zip)$", re.IGNORECASE)
_SPACES = re.compile(r"\s+")
CAPTION_MAX_CHARS = 220


@dataclass
class ListingRow:
    slug: str
    path: str
    title: str
    description: str
    update_frequency: str | None


@dataclass
class PageFile:
    url: str
    name: str
    caption: str | None
    release: str
    format: str


@dataclass
class DatasetPage:
    slug: str
    title: str
    description: str
    file_types: list[str]
    update_frequency: str | None
    last_updated: date | None
    fr_path: str | None
    files: list[PageFile] = field(default_factory=list)
    hops: list[str] = field(default_factory=list)


def _text(node: Tag | NavigableString | None) -> str:
    if node is None:
        return ""
    return _SPACES.sub(" ", node.get_text(" ") if isinstance(node, Tag) else str(node)).strip()


def parse_date(text: str) -> date | None:
    text = text.replace(".", "").replace(",", "").strip()
    for fmt in ("%B %d %Y", "%b %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC).date()
        except ValueError:
            continue
    return None


def file_format(url: str) -> str:
    match = _FILE_EXT.search(urlparse(url).path)
    if not match:
        return "other"
    ext = match.group(1).lower()
    return ext if ext in ("xml", "xlsx", "zip") else "other"


def is_file_link(url: str) -> bool:
    return bool(_FILE_EXT.search(urlparse(url).path))


def file_name(url: str) -> str:
    return unquote(urlparse(url).path.rsplit("/", 1)[-1])


def parse_listing(html: str, *, prefix: str = "/open-data/") -> tuple[list[ListingRow], bool]:
    """Rows of one listing page and whether a next page exists."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[ListingRow] = []
    for row in soup.select(".views-row"):
        link = row.select_one(".views-field-title a[href]")
        if link is None:
            continue
        path = urlparse(str(link["href"])).path
        if not path.startswith(prefix):
            continue
        frequency = row.select_one(".views-field-field-update-frequency .field-content")
        rows.append(
            ListingRow(
                slug=path.removeprefix(prefix).strip("/"),
                path=path,
                title=_text(link),
                description=_text(row.select_one(".views-field-body")),
                update_frequency=_text(frequency) or None,
            )
        )
    has_next = soup.select_one(".pager__item--next a, a[rel=next]") is not None
    return rows, has_next


def parse_yearbook_links(html: str) -> list[PageFile]:
    """The 2021 yearbook workbooks linked from the open data page itself."""
    soup = BeautifulSoup(html, "html.parser")
    files: list[PageFile] = []
    seen: set[str] = set()
    for link in soup.select("main a[href]"):
        url = urljoin(constants.BASE_URL + "/", str(link["href"]))
        if "yearbook-" not in url.lower() or not is_file_link(url) or url in seen:
            continue
        seen.add(url)
        caption = re.sub(r"\s*\(xlsx\)\s*$", "", _text(link), flags=re.IGNORECASE)
        files.append(
            PageFile(
                url=url,
                name=file_name(url),
                caption=caption or None,
                release="current",
                format=file_format(url),
            )
        )
    return files


def _caption(link: Tag) -> str | None:
    """The text of the link's block before the link, without the release phrase."""
    block = link.find_parent(["p", "li", "div"])
    if block is None:
        return None
    parts: list[str] = []
    for node in block.descendants:
        if node is link:
            break
        if isinstance(node, NavigableString) and not node.find_parent("summary"):
            if node.find_parent("a") is not None:
                continue
            parts.append(str(node))
    text = _PUBLISHED.sub("", _SPACES.sub(" ", " ".join(parts))).strip(" :")
    if not text or text.lower().startswith("archive"):
        return None
    return text[:CAPTION_MAX_CHARS].rstrip()


def parse_dataset_page(html: str, slug: str) -> DatasetPage:
    soup = BeautifulSoup(html, "html.parser")
    alternate = soup.select_one('link[rel=alternate][hreflang="fr"]')
    fr_path = urlparse(str(alternate["href"])).path if alternate else None
    note = _text(soup.select_one(".field--name-field-update-frequency-note"))
    page = DatasetPage(
        slug=slug,
        title=_text(soup.select_one("h1.page-title")) or slug,
        description=_text(soup.select_one(".field--name-body .field__item")),
        file_types=[_text(n) for n in soup.select(".field--name-field-file-types .field__item")],
        update_frequency=_text(soup.select_one(".field--name-field-update-frequency .field__item"))
        or None,
        last_updated=parse_date(note.split(":", 1)[-1]) if note else None,
        fr_path=fr_path,
    )
    url_field = soup.select_one(".field--name-field-wysiwyg-url .field__item")
    if url_field is None:
        return page
    release = "current"
    seen: set[tuple[str, str]] = set()
    for node in url_field.descendants:
        if isinstance(node, NavigableString):
            match = _PUBLISHED.search(str(node))
            if match:
                published = parse_date(match.group(1))
                release = published.isoformat() if published else match.group(1)
            continue
        if not isinstance(node, Tag) or node.name != "a" or not node.get("href"):
            continue
        url = urljoin(constants.BASE_URL + "/", str(node["href"]).strip())
        host = urlparse(url).hostname or ""
        if not is_file_link(url):
            if host in constants.ALLOWED_HOSTS and url not in page.hops:
                page.hops.append(url)
            continue
        if (url, release) in seen:
            continue  # a link split in two anchors on some pages (2.1.7, 2.1.5.8)
        seen.add((url, release))
        page.files.append(
            PageFile(
                url=url,
                name=file_name(url),
                caption=_caption(node),
                release=release,
                format=file_format(url),
            )
        )
    return page


def parse_hop_page(html: str, base_url: str) -> list[PageFile]:
    """File links on a page a dataset page points to (one level only)."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main") or soup
    files: list[PageFile] = []
    seen: set[str] = set()
    last_text = ""
    for link in main.select("a[href]"):
        text = _text(link)
        url = urljoin(base_url, str(link["href"]).strip())
        if not is_file_link(url) or (urlparse(url).hostname or "") not in constants.ALLOWED_HOSTS:
            last_text = text or last_text
            continue
        if url in seen:
            continue
        seen.add(url)
        # The cost awards page labels each file ".xml" after a link to the report.
        caption = text if len(text) > 6 else last_text
        files.append(
            PageFile(
                url=url,
                name=file_name(url),
                caption=caption or None,
                release="current",
                format=file_format(url),
            )
        )
    return files
