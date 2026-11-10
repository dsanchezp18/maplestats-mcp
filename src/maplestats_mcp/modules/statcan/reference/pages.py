"""Parsing for StatCan's catalogue pages and the publications they list (no I/O).

Checked live 2026-11-10 on 71-543-G (Guide to the Labour Force Survey), 62-553-X
(CPI Reference Paper), 13-017-X (Guide to the Income and Expenditure Accounts),
13-607-X (Methodological Guide: Canadian System of Macroeconomic Accounts),
15-203-X, 62F0014M2021011 and 46280001202500100004, English and French.

**Catalogue page** (`/n1/{en,fr}/catalogue/<number>`, Drupal): the title in the
<h1> (" - ARCHIVED"/" - ARCHIVÉ" appended when archived), the product type and
number in `section.block-ndm-conttype`, the description in a
`section.block-ndm-product-block` labelled "Description". A series (71-543-G)
lists its editions in `section.block-ndm-releases`' table, newest first, one row
per edition: a link to the edition (HTML, or PDF for old ones: the LFS guide is
PDF up to 2006), the release date with its ISO form in `data-order`
("2025-04-04_202500199999"), and a "More information" link to the edition's own
catalogue page (/n1/en/catalogue/71-543-G2025001). An edition or a single
article (62F0014M2021011) has `section.block-ndm-formats` instead: one row per
format (HTML, PDF) with the release date written out ("July 21, 2021",
"21 juillet 2021"). Numbers of the form 46-28-0001 are addressed without their
hyphens (/n1/en/catalogue/46280001: the hyphenated path is a 404).

**Publication pages** (`/n1/pub/<number lower case>/...`): an edition's main
page is `<number><issue>-eng.htm` (71-543-g2025001-eng.htm), French `-fra.htm`;
its other pages sit in a folder named after the issue (/n1/pub/71-543-g/2025001/,
/n1/pub/62-553-x/2023001/chap-10-eng.htm). Links in the pages are written
root-relative without /n1 ("/pub/62-553-x/2023001/chap-1-eng.htm", which answers
301 to the /n1/ path) or relative ("2008001/themes/ch01/5213332-eng.htm" on
13-017-X). Three layouts were seen:

- one long page with h2/h3 sections and an "On this page" list
  (`details.rel-article`), e.g. the LFS guide (333 KB, its appendices on
  separate pages);
- a short main page plus a table of contents in a modal
  (`section#toc-tdm`) linking one page per chapter, e.g. the CPI reference paper;
- the 2008-era layout (`div#wb-main`, a `div#wb-sec` side menu) with chapter
  links in the text, nested two or three pages deep (13-017-X, 13-607-X);
- the older CLF 2.0 layout of the LFS guide's 2007 to 2012 editions: no
  role="main", the text in `div.core div.center`, an empty skip-link <h1>
  before the real one, the archived notice in a `div#archived`, and pages
  served as windows-1252 under a "charset=UTF-8" header (client.py decodes them).

The text sits in the element with role="main" in the first three. Around it, and
dropped here: screen-reader text (span.wb-inv), the "Archived Content" notice
(section#archived, #archived-bnr), the release-date label and the PDF / "More
information" buttons, the modals (section.mfp-hide: "More information",
the table of contents), the "On this page" list, footnote return links
(p.fn-rtn) and the date-modified block. Tables are <table> with a <caption>
(its "Table summary" in span.wb-inv), header rows in <thead>, notes in <tfoot>.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

HOST = "www150.statcan.gc.ca"
BASE = f"https://{HOST}"

_ARCHIVED_SUFFIX = re.compile(r"\s*-\s*ARCHIV(?:ED|É|E)\s*$", re.IGNORECASE)
_ISSUE = re.compile(r"(\d{7})$")
# An edition's main page: <catalogue number, lower case, no separator><7-digit issue>.
_EDITION_FILE = re.compile(r"^(?P<stem>[a-z0-9-]*?)(?P<issue>\d{7})-(?:eng|fra)\.html?$")
_PAGE_SUFFIX = re.compile(r"-(eng|fra)\.(html?)$")
_SCREEN_READER = ("wb-inv", "wb-invisible", "navaid")
_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_SKIPPED = frozenset(
    {"script", "style", "noscript", "nav", "button", "img", "svg", "form", "input", "iframe"}
)
_CONTAINERS = frozenset(
    {
        "div", "section", "article", "aside", "details", "figure", "main", "header",
        "footer", "dl", "blockquote", "center",
    }
)  # fmt: skip
_PARAGRAPHS = frozenset({"p", "dt", "dd", "pre", "summary", "figcaption", "address"})
# Block elements: a "paragraph" holding one is walked as a container. html.parser
# leaves a <p> open when a <details> sits inside it (LFS guide, Figure 2.1), and
# everything after it, the next sections' headings too, ends up inside that <p>.
_BLOCKISH = (
    *_HEADINGS,
    "table",
    "ul",
    "ol",
    "div",
    "section",
    "details",
    "p",
    "dl",
    "blockquote",
)
_ARCHIVED_HEADINGS = frozenset({"archived content", "contenu archive"})
_BOILERPLATE = frozenset(
    {
        "view the most recent version.",
        "consulter la version la plus recente.",
        "skip to text",
        "text begins",
    }
)
_DATE_MODIFIED = frozenset({"date modified:", "date de modification :", "date de modification:"})
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}  # fmt: skip


def fold(text: str) -> str:
    """Lower case without accents, for matching titles and query words."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def clean(text: str) -> str:
    return " ".join(text.replace("−", "-").replace("﻿", "").split())


def parse_date(text: str | None) -> date | None:
    """An ISO date, "July 21, 2021" or "21 juillet 2021"; None otherwise."""
    if not text:
        return None
    iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    words = re.findall(r"[a-z]+|\d+", fold(text))
    month = next((_MONTHS[w] for w in words if w in _MONTHS), None)
    numbers = [int(w) for w in words if w.isdigit()]
    year = next((n for n in numbers if n > 1900), None)
    day = next((n for n in numbers if 1 <= n <= 31), None)
    if month and year and day:
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


# --- URLs -------------------------------------------------------------------------


def normalize_url(url: str, base: str | None = None) -> str:
    """Absolute https www150 URL, /pub/ paths under /n1/, no fragment kept separately."""
    absolute = urljoin(base, url) if base else url
    parsed = urlparse(absolute)
    path = parsed.path
    # StatCan writes links root-relative without /n1 ("/pub/71-543-g/..."); those
    # answer 301 to the same path under /n1/.
    if parsed.netloc in ("", HOST) and path.startswith(("/pub/", "/en/", "/fr/")):
        path = "/n1" + path
    netloc = parsed.netloc or HOST
    query = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"https://{netloc}{path}{query}{fragment}"


def with_lang(url: str, lang: str) -> str:
    """The same page in `lang`: StatCan pages differ only by -eng/-fra."""
    suffix = "fra" if lang == "fr" else "eng"
    base, _, fragment = url.partition("#")
    base = _PAGE_SUFFIX.sub(lambda m: f"-{suffix}.{m.group(2)}", base)
    return f"{base}#{fragment}" if fragment else base


def edition_scope(edition_url: str) -> str:
    """The path prefix an edition's other pages live under.

    71-543-g2025001-eng.htm -> /n1/pub/71-543-g/2025001/ (its issue folder). Any
    other page (an article, /n1/pub/46-28-0001/2025001/article/00004-eng.htm) keeps
    its pages, if any, in a folder named after itself.
    """
    path = urlparse(edition_url).path
    directory, _, name = path.rpartition("/")
    match = _EDITION_FILE.match(name.lower())
    if match:
        return f"{directory}/{match.group('issue')}/"
    return f"{directory}/{_PAGE_SUFFIX.sub('', name)}/"


def edition_of(page_url: str) -> str:
    """The edition main page a /n1/pub/ page belongs to (the page itself if it is one).

    /n1/pub/62-553-x/2023001/chap-10-eng.htm -> /n1/pub/62-553-x/62-553-x2023001-eng.htm.
    An article page (/article/ in its path) is its own edition.
    """
    parsed = urlparse(page_url)
    parts = parsed.path.split("/")
    # ["", "n1", "pub", "<number>", "<issue>", ...]
    if (
        len(parts) > 5
        and parts[1] == "n1"
        and parts[2] == "pub"
        and re.fullmatch(r"\d{7}", parts[4])
        and "article" not in parts
    ):
        lang = "fra" if parsed.path.endswith(("-fra.htm", "-fra.html")) else "eng"
        number = parts[3]
        return f"{BASE}/n1/pub/{number}/{number}{parts[4]}-{lang}.htm"
    return f"{BASE}{parsed.path}"


def page_key(page_url: str, edition_url: str) -> str:
    """A language-independent id for a page of an edition: "" for the main page,
    else its path under the edition's folder without -eng.htm ("chap-10")."""
    path = urlparse(page_url).path
    if path == urlparse(edition_url).path:
        return ""
    scope = edition_scope(edition_url)
    relative = path[len(scope) :] if path.startswith(scope) else path.rsplit("/", 1)[-1]
    return _PAGE_SUFFIX.sub("", relative)


def page_url_for_key(key: str, edition_url: str) -> str:
    if not key:
        return edition_url
    suffix = "fra" if edition_url.endswith("-fra.htm") else "eng"
    return f"{BASE}{edition_scope(edition_url)}{key}-{suffix}.htm"


def catalogue_path(number: str) -> str:
    """The catalogue page's path segment for a catalogue number.

    Numbers in the 12-34-5678 form are addressed without hyphens (checked live:
    /n1/en/catalogue/46-28-0001 is a 404, /n1/en/catalogue/46280001 the page).
    """
    number = number.strip().upper()
    if re.match(r"^\d{2}-\d{2}-\d{4}", number):
        return number.replace("-", "")
    return number


# --- Catalogue pages ----------------------------------------------------------------


@dataclass
class Edition:
    title: str
    url: str
    release_date: date | None
    catalogue_number: str | None
    issue: str | None
    format: str
    archived: bool
    pdf_url: str | None = None


@dataclass
class CataloguePage:
    title: str
    catalogue_number: str | None
    product_type: str | None
    description: str | None
    archived: bool
    editions: list[Edition] = field(default_factory=list)


def _block_value(soup: BeautifulSoup, *labels: str) -> str | None:
    for block in soup.select("section.block-ndm-product-block"):
        label = block.find("span", class_="ndm-product-title")
        if not isinstance(label, Tag):
            continue
        name = fold(clean(label.get_text())).rstrip(": ")
        if name in labels:
            label.extract()
            return clean(block.get_text(" ")) or None
    return None


def _issue_of(number: str | None, url: str) -> str | None:
    if number:
        match = _ISSUE.search(number)
        if match:
            return match.group(1)
    name = urlparse(url).path.rsplit("/", 1)[-1].lower()
    match = re.search(r"(\d{7})-(?:eng|fra)\.(?:html?|pdf)$", name)
    return match.group(1) if match else None


def _format_of(url: str) -> str:
    return "pdf" if urlparse(url).path.lower().endswith(".pdf") else "html"


def parse_catalogue_page(html: str, url: str) -> CataloguePage | None:
    """A catalogue page's title, number, description and editions (None: not one)."""
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    conttype = soup.select_one("section.block-ndm-conttype")
    if not isinstance(heading, Tag) or conttype is None:
        return None
    raw_title = clean(heading.get_text(" "))
    archived = bool(_ARCHIVED_SUFFIX.search(raw_title))
    title = _ARCHIVED_SUFFIX.sub("", raw_title)
    spans = conttype.find_all("span")
    product_type = clean(spans[0].get_text()).rstrip(": ") if spans else None
    number = clean(spans[1].get_text()) if len(spans) > 1 else None
    description = _block_value(soup, "description")

    editions: list[Edition] = []
    for row in soup.select("section.block-ndm-releases table tbody tr"):
        cells = row.find_all("td")
        link = cells[0].find("a", href=True) if cells else None
        if not isinstance(link, Tag):
            continue
        edition_url = normalize_url(str(link["href"]), url)
        edition_title = clean(link.get_text(" "))
        when = None
        if len(cells) > 1:
            when = parse_date(str(cells[1].get("data-order") or "")) or parse_date(
                cells[1].get_text(" ")
            )
        more = cells[2].find("a", href=True) if len(cells) > 2 else None
        edition_number = (
            str(more["href"]).rstrip("/").rsplit("/", 1)[-1] if isinstance(more, Tag) else None
        )
        editions.append(
            Edition(
                title=_ARCHIVED_SUFFIX.sub("", edition_title),
                url=edition_url,
                release_date=when,
                catalogue_number=edition_number,
                issue=_issue_of(edition_number, edition_url),
                format=_format_of(edition_url),
                archived=bool(_ARCHIVED_SUFFIX.search(edition_title)),
            )
        )

    if not editions:
        # One edition or article: a row per format (HTML, PDF).
        html_url = pdf_url = None
        when = None
        for row in soup.select("section.block-ndm-formats table tbody tr"):
            cells = row.find_all("td")
            link = cells[0].find("a", href=True) if cells else None
            if not isinstance(link, Tag):
                continue
            target = normalize_url(str(link["href"]), url)
            if _format_of(target) == "pdf":
                pdf_url = pdf_url or target
            elif urlparse(target).path.startswith("/n1/pub/"):
                html_url = html_url or target
            if when is None and len(cells) > 1:
                when = parse_date(cells[1].get_text(" "))
        if html_url or pdf_url:
            target = html_url or pdf_url or ""
            editions.append(
                Edition(
                    title=title,
                    url=target,
                    release_date=when,
                    catalogue_number=number,
                    issue=_issue_of(number, target),
                    format=_format_of(target),
                    archived=archived,
                    pdf_url=pdf_url,
                )
            )

    editions.sort(key=lambda e: e.release_date or date.min, reverse=True)
    return CataloguePage(
        title=title,
        catalogue_number=number,
        product_type=product_type,
        description=description,
        archived=archived,
        editions=editions,
    )


# --- Publication pages ------------------------------------------------------------


@dataclass
class Block:
    kind: str  # "heading" or "text"
    text: str
    level: int = 0
    anchor: str | None = None
    href: str | None = None  # a heading's own URL when not page.url#anchor (PDF bookmarks)


@dataclass
class Heading:
    position: int  # index into Page.blocks
    level: int
    title: str
    anchor: str | None
    href: str | None = None


@dataclass
class Link:
    url: str
    title: str


@dataclass
class Page:
    url: str
    title: str
    release_date: date | None
    archived: bool
    pdf_url: str | None
    blocks: list[Block]
    links: list[Link]

    @property
    def headings(self) -> list[Heading]:
        return [
            Heading(i, block.level, block.text, block.anchor, block.href)
            for i, block in enumerate(self.blocks)
            if block.kind == "heading"
        ]


def _is_screen_reader(tag: Tag) -> bool:
    classes = tag.get("class") or []
    return any(name in classes for name in _SCREEN_READER)


def _inline(element: Tag) -> str:
    """An element's text on one line, inline markup joined as written."""
    parts: list[str] = []
    for node in element.descendants:
        if isinstance(node, Tag) and node.name in ("br", "p", "div", "li", "td", "th"):
            parts.append(" ")
        elif type(node) is NavigableString:
            parts.append(str(node))
    return clean("".join(parts))


def _table_text(table: Tag) -> str:
    lines: list[str] = []
    caption = table.find("caption")
    if isinstance(caption, Tag):
        title = _inline(caption)
        if title:
            lines.append(title)
    sections = [table.find("thead"), *table.find_all("tbody"), table.find("tfoot")]
    rows: list[Tag] = []
    for part in sections:
        if isinstance(part, Tag):
            rows.extend(part.find_all("tr", recursive=False))
    if not rows:
        rows = table.find_all("tr")
    for row in rows:
        cells = [_inline(cell) for cell in row.find_all(["th", "td"], recursive=False)]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _list_text(element: Tag, depth: int = 0) -> str:
    lines: list[str] = []
    for item in element.find_all("li", recursive=False):
        nested = [child for child in item.find_all(["ul", "ol"], recursive=False)]
        for child in nested:
            child.extract()
        text = _inline(item)
        if text:
            lines.append(f"{'  ' * depth}- {text}")
        for child in nested:
            sub = _list_text(child, depth + 1)
            if sub:
                lines.append(sub)
    return "\n".join(lines)


def _blocks(root: Tag) -> list[Block]:
    blocks: list[Block] = []
    buffer: list[str] = []

    def flush() -> None:
        text = clean("".join(buffer))
        buffer.clear()
        if text:
            blocks.append(Block("text", text))

    def walk(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                if type(child) is NavigableString:
                    buffer.append(str(child))
                continue
            if not isinstance(child, Tag) or child.name in _SKIPPED:
                continue
            name = child.name
            if name in _HEADINGS:
                flush()
                title = _inline(child)
                if title:
                    anchor = child.get("id")
                    blocks.append(
                        Block(
                            "heading",
                            title,
                            level=int(name[1]),
                            anchor=str(anchor) if anchor else None,
                        )
                    )
            elif name == "table":
                flush()
                text = _table_text(child)
                if text:
                    blocks.append(Block("text", text))
            elif name in ("ul", "ol"):
                flush()
                text = _list_text(child)
                if text:
                    blocks.append(Block("text", text))
            elif name in _PARAGRAPHS and child.find(_BLOCKISH) is None:
                flush()
                text = _inline(child)
                if text:
                    blocks.append(Block("text", text))
            elif name in _CONTAINERS or name in _PARAGRAPHS or child.find(_BLOCKISH):
                flush()
                walk(child)
                flush()
            elif name == "br":
                buffer.append(" ")
            else:
                buffer.append(_inline(child) if child.find(True) else child.get_text())

    walk(root)
    flush()
    return blocks


def _content_root(soup: BeautifulSoup) -> Tag:
    for candidate in (
        soup.select_one("[role=main]"),
        soup.find("main"),
        soup.find(id="wb-main"),
        # The 2005-2010 layout (CLF 2.0: the LFS guide 2007 to 2012 editions) has
        # neither: its text is div.center, between a side menu and the footer.
        soup.select_one("div.core div.center"),
        soup.body,
    ):
        if isinstance(candidate, Tag):
            return candidate
    return soup


def _in_scope(url: str, scope: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.netloc == HOST
        and parsed.path.startswith(scope)
        and bool(_PAGE_SUFFIX.search(parsed.path))
    )


def parse_page(html: str, url: str, scope: str) -> Page:
    """A publication page's title, dates, PDF link, text blocks and in-scope links."""
    soup = BeautifulSoup(html, "html.parser")
    root = _content_root(soup)

    def meta(name: str) -> str | None:
        tag = soup.find("meta", attrs={"name": name})
        value = tag.get("content") if isinstance(tag, Tag) else None
        return str(value) if value else None

    archived = root.find(id="archived") is not None
    # The first h1 with text: the CLF 2.0 layout opens with an empty
    # <h1><a name="cont"></a></h1> skip-link target before the real title.
    title = ""
    for heading in root.find_all("h1"):
        if _is_screen_reader(heading):
            continue
        for small in heading.find_all("small"):
            small.insert_after(NavigableString(" – "))
        title = _inline(heading).strip(" –")
        if title:
            break

    # The release date is in dcterms.issued on most pages; the CPI reference paper
    # has only its "Release date: February 20, 2023" label (span.label).
    released = parse_date(meta("dcterms.issued"))
    if released is None:
        for label in root.select("span.label"):
            released = parse_date(_inline(label))
            if released:
                break

    pdf_url = None
    for link in root.find_all("a", href=True):
        href = str(link["href"])
        if href.lower().endswith(".pdf") and "pdf" in fold(_inline(link)):
            pdf_url = normalize_url(href, url)
            break

    # Links to the edition's other pages, in reading order: the table of contents
    # modal first (CPI reference paper), then the text (LFS appendices, 13-017-X).
    links: list[Link] = []
    seen = {urlparse(url).path}
    toc = root.find(id="toc-tdm")
    anchors = (toc.find_all("a", href=True) if isinstance(toc, Tag) else []) + root.find_all(
        "a", href=True
    )
    for link in anchors:
        href = str(link["href"])
        if href.startswith(("#", "mailto:", "javascript:")):
            continue
        target = normalize_url(href, url).partition("#")[0]
        text = _inline(link)
        if not text or not _in_scope(target, scope):
            continue
        path = urlparse(target).path
        if path in seen:
            continue
        seen.add(path)
        links.append(Link(target, text))

    # Footnote markers: "<sup><a class="fn-lnk"><span class="wb-inv">Note </span>1</a>"
    # reads "[1]", not a bare digit glued to the word before it.
    for marker in root.select("a.fn-lnk"):
        for hidden in marker.find_all(_is_screen_reader):
            hidden.decompose()
        number = clean(marker.get_text())
        marker.replace_with(NavigableString(f"[{number or 'note'}]"))
    removals = [
        *root.find_all(_is_screen_reader),
        *root.select(
            "#archived, #archived-bnr, section.mfp-hide, details.rel-article, "
            "p.fn-rtn, #wb-dtmd, .block-date-modified-block, #wb-sec, span.label, a.btn, "
            ".pagination, ul.pager, div.table_toc_buttons, div.footer"
        ),
        *root.find_all("h1"),
    ]
    for element in removals:
        if isinstance(element, Tag) and element.parent is not None:
            element.decompose()

    blocks = _blocks(root)
    # The 2008-era layout (13-017-X) writes its archived notice and the date
    # modified as plain text inside role=main, with no id to drop them by.
    kept: list[Block] = []
    drop_next = False  # the notice's paragraph, or the date after "Date modified:"
    for block in blocks:
        folded = fold(block.text).strip()
        if drop_next and block.kind == "text":
            drop_next = False
            continue
        drop_next = False
        if block.kind == "heading" and folded in _ARCHIVED_HEADINGS and len(kept) < 3:
            archived = drop_next = True
        elif folded in _DATE_MODIFIED:
            drop_next = True
        elif folded not in _BOILERPLATE:
            kept.append(block)
    blocks = kept
    return Page(
        url=url,
        title=title,
        release_date=released,
        archived=archived,
        pdf_url=pdf_url,
        blocks=blocks,
        links=links,
    )


# --- Sections -------------------------------------------------------------------------


def section_blocks(page: Page, heading: Heading | None) -> list[Block]:
    """The blocks of a heading's section (to the next heading at its level or above);
    the whole page for None."""
    if heading is None:
        return page.blocks
    end = len(page.blocks)
    for i in range(heading.position + 1, len(page.blocks)):
        block = page.blocks[i]
        if block.kind == "heading" and block.level <= heading.level:
            end = i
            break
    return page.blocks[heading.position : end]


def render(blocks: list[Block], top_level: int | None = None) -> str:
    """Plain text: headings as Markdown "#" lines, paragraphs separated by a blank line."""
    parts: list[str] = []
    base = top_level if top_level is not None else 2
    for block in blocks:
        if block.kind == "heading":
            depth = max(1, block.level - base + 1)
            parts.append(f"{'#' * depth} {block.text}")
        else:
            parts.append(block.text)
    return "\n\n".join(parts)


def cut(text: str, start: int, limit: int) -> tuple[str, int, bool]:
    """`limit` characters of `text` from `start`, ending at a paragraph or word break.

    Returns the piece, the offset just after it, and whether text remains.
    """
    start = max(0, min(start, len(text)))
    if len(text) - start <= limit:
        return text[start:], len(text), False
    end = start + limit
    window = text[start:end]
    for breaker in ("\n\n", "\n", ". ", " "):
        position = window.rfind(breaker)
        if position > limit // 2:
            end = start + position + len(breaker)
            break
    return text[start:end].rstrip(), end, True


def edition_issue(edition_url: str) -> str | None:
    """The 7-digit issue of an edition main page's URL (71-543-g2025001-eng.htm)."""
    name = urlparse(edition_url).path.rsplit("/", 1)[-1].lower()
    match = _EDITION_FILE.match(name)
    return match.group("issue") if match else None
