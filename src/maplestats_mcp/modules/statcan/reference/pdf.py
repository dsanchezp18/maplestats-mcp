"""Text of a StatCan PDF publication, read with pypdf (no I/O).

For editions published as PDF only: the Provincial Gross Domestic Product by
Industry PDFs (15-203-X, 1998 and 1999, 277 pages), the Guide to the Labour
Force Survey up to 2006 (71-543-G), and the 2008-era guides that also ship a
PDF of the whole edition (13-017-X2008001, 297 pages). Checked live 2026-11-10.

What the files look like, and what this module does about it:

- the text of a page comes out line by line, in reading order for one-column
  pages; two-column bilingual pages (15-203-X: English on the left, French on
  the right) come out a column at a time or interleaved, so a table or a
  paragraph can be split. Callers say so in provenance;
- each page repeats a running header or footer ("Statistics Canada - Catalogue
  no. 15-203 7 Statistique Canada - no 15-203 au catalogue"), which is dropped
  when the same line, digits and spaces aside, is among the first or last two
  lines of a third of the pages;
- lines are joined into paragraphs: a line much shorter than the page's usual
  line, or one ending a sentence before a short line, ends a paragraph; a word
  split at the end of a line ("situ-" / "ation") is joined;
- the outline (bookmarks), when the file has one (the CPI Reference Paper's PDF
  has 26), gives the sections; without one, each page is a section titled by
  its first heading or line ("Page 192 - Gross Output Approach");
- a short title-case line on its own ("Gross Output Approach") is a heading
  below the page's, so a query scores the text under it on its own.

The result is a `pages.Page` whose headings are the outline entries and one
heading per PDF page (anchor "page=N", so its URL is the PDF's own
"#page=N" open parameter), which the rest of the client searches and cuts like
an HTML page.
"""

from __future__ import annotations

import io
import logging
import re
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from maplestats_mcp.modules.statcan.reference import pages
from maplestats_mcp.shared.executor import check_deadline

# pypdf logs a warning for every font it cannot fully decode ("fontTools is
# required..."), dozens per StatCan PDF, while the text still comes out right.
logging.getLogger("pypdf").setLevel(logging.ERROR)

_DIGITS = re.compile(r"\d+")
_SPACES = re.compile(r"\s+")
_LETTER = re.compile(r"[^\W\d_]")
# Glyph names written for a font with no text mapping ("/G80/G114/G111" on a
# 15-203-X chart page): noise, dropped.
_GLYPHS = re.compile(r"(?:/G[0-9A-Fa-f]{2,4})+")
_EDGE = 2  # lines at the top and the bottom of a page where a running header sits
_SENTENCE_END = (".", ":", "?", "!", ";")


class PdfUnreadable(ValueError):
    """The bytes are not a PDF pypdf can open (damaged, encrypted, not a PDF)."""


@dataclass
class PdfText:
    page: pages.Page
    page_count: int  # pages in the file
    pages_read: int  # pages whose text was extracted, from the first
    has_outline: bool


def page_anchor(number: int) -> str:
    """The anchor of a PDF page's heading: its URL fragment is the standard
    PDF open parameter (#page=N), which browsers' PDF viewers honour."""
    return f"page={number}"


def _outline(reader: PdfReader) -> list[tuple[int, str, int]]:
    """(level from 1, title, 1-based page) of each bookmark, in order."""
    entries: list[tuple[int, str, int]] = []

    def page_of(item: Any) -> int | None:
        try:
            return reader.get_destination_page_number(item)
        except Exception:  # noqa: BLE001 (pypdf raises several types for a bad bookmark)
            return None

    def walk(items: list[Any], level: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            number = page_of(item)
            title = pages.clean(str(getattr(item, "title", "") or ""))
            if title and number is not None and number >= 0:
                entries.append((level, title, number + 1))

    try:
        walk(list(reader.outline), 1)
    except Exception:  # noqa: BLE001 (a damaged outline leaves the pages readable)
        return []
    return entries


def _line_key(line: str) -> str:
    """A line with its digits and spaces removed: 15-203-X's running header comes out
    as "intérieur" on some pages and "int érieur" on others."""
    return _SPACES.sub("", _DIGITS.sub("#", line))


def _running_lines(texts: list[list[str]]) -> set[str]:
    """Keys of the lines with letters that start or end at least a third of the pages."""
    if len(texts) < 3:
        return set()
    counts: Counter[str] = Counter()
    for lines in texts:
        counts.update({_line_key(line) for line in _edges(lines) if _LETTER.search(line)})
    threshold = max(3, len(texts) // 3)
    return {key for key, count in counts.items() if count >= threshold}


def _edges(lines: list[str]) -> list[str]:
    return [*lines[:_EDGE], *lines[-_EDGE:]] if len(lines) > 2 * _EDGE else list(lines)


def _without_running(lines: list[str], running: set[str]) -> list[str]:
    """The page's lines less a running header or footer among its first and last lines."""
    head = len(lines) if len(lines) <= 2 * _EDGE else _EDGE
    tail = len(lines) - _EDGE if len(lines) > 2 * _EDGE else len(lines)
    return [
        line
        for index, line in enumerate(lines)
        if not ((index < head or index >= tail) and _line_key(line) in running)
    ]


def _paragraphs(lines: list[str]) -> list[str]:
    """A page's lines joined into paragraphs.

    A paragraph ends at a blank line, after a line ending a sentence that is
    shorter than the page's usual line, and after any short line (a heading, a
    table row) followed by one that does not start in lower case. Justified text
    in the 2006 LFS guide comes out a word per line ("or" / "only" / "job."):
    those lines run on, since the next one starts in lower case.
    """
    lengths = [len(line) for line in lines if len(line) > 20]
    usual = statistics.median(lengths) if lengths else 60
    paragraphs: list[str] = []
    current = ""
    for index, line in enumerate(lines):
        if not line:
            continue
        if not current:
            current = line
        elif current.endswith("-") and line[:1].islower() and current[-2:-1].isalpha():
            current = current[:-1] + line
        else:
            current = f"{current} {line}"
        following = next((other for other in lines[index + 1 :] if other), "")
        blank_next = index + 1 < len(lines) and not lines[index + 1]
        runs_on = following[:1].islower()
        if (
            not following
            or (blank_next and not runs_on)
            or (line.endswith(_SENTENCE_END) and len(line) < 0.85 * usual)
            or (len(line) < 0.6 * usual and not runs_on)
        ):
            paragraphs.append(current)
            current = ""
    if current:
        paragraphs.append(current)
    return paragraphs


_SECTION_NUMBER = re.compile(
    r"^(?:\d+|[ivx]+|[a-z])(?:\.(?:\d+|[ivx]+|[a-z]))*\.?\s+", re.IGNORECASE
)
_MINOR_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "de",
        "des",
        "du",
        "en",
        "et",
        "for",
        "from",
        "in",
        "la",
        "le",
        "les",
        "of",
        "on",
        "or",
        "par",
        "pour",
        "the",
        "to",
        "with",
    ]
)


def looks_like_heading(paragraph: str) -> bool:
    """One short title-case line of two words or more ("Gross Output Approach",
    "2.iii. Constant Price GDP Estimates"), not a sentence or a table row ("E159
    Other Rubber Products Gross output Industries" has a code in it)."""
    text = _SECTION_NUMBER.sub("", paragraph)
    words = text.split()
    if not 2 <= len(words) <= 10 or len(paragraph) > 80 or text.endswith((".", ",", ";", ":")):
        return False
    if any(ch.isdigit() for ch in text) or not words[0][:1].isupper():
        return False
    major = [w for w in words if w.lower() not in _MINOR_WORDS]
    capitalized = [w for w in major if w[:1].isupper()]
    return text.isupper() or len(capitalized) == len(major)


def _headings(by_page: list[list[str]]) -> set[tuple[int, int]]:
    """(page index, paragraph index) of the paragraphs taken as headings: those that
    look like one, come before a paragraph of text, and appear at most twice in the
    file (a column label of the statistical tables, a running title the header
    check missed, such as "The Canadian Consumer Price Index Reference Paper",
    comes back on many pages)."""
    seen: Counter[str] = Counter()
    for paragraphs in by_page:
        seen.update(p for p in paragraphs if looks_like_heading(p))
    found: set[tuple[int, int]] = set()
    for page, paragraphs in enumerate(by_page):
        for index, paragraph in enumerate(paragraphs[:-1]):
            following = paragraphs[index + 1]
            if (
                seen[paragraph] <= 2
                and looks_like_heading(paragraph)
                and len(following) >= 60
                and not looks_like_heading(following)
            ):
                found.add((page, index))
    return found


def _page_title(number: int, paragraphs: list[str], headings: list[str]) -> str:
    first = headings[0] if headings else ""
    first = first or next((p for p in paragraphs if any(ch.isalpha() for ch in p)), "")
    if len(first) > 70:
        first = first[:70].rsplit(" ", 1)[0] + "..."
    return f"Page {number} - {first}" if first else f"Page {number}"


def extract(body: bytes, url: str, *, max_pages: int, max_chars: int, seconds: float) -> PdfText:
    """The PDF's text as a pages.Page, from its first page until the last page or
    until `max_pages` pages, `max_chars` characters or `seconds` of work."""
    if not body.startswith(b"%PDF"):
        raise PdfUnreadable("not a PDF file")
    try:
        reader = PdfReader(io.BytesIO(body))
        if reader.is_encrypted:
            raise PdfUnreadable("the PDF is encrypted")
        page_count = len(reader.pages)
        outline = _outline(reader)
        started = time.monotonic()
        texts: list[list[str]] = []
        total = 0
        for index in range(min(page_count, max_pages)):
            check_deadline()
            text = _GLYPHS.sub("", reader.pages[index].extract_text() or "")
            lines = [pages.clean(line) for line in text.replace("\r", "\n").split("\n")]
            texts.append(lines)
            total += len(text)
            if total > max_chars or time.monotonic() - started > seconds:
                break
    except PdfReadError as exc:
        raise PdfUnreadable(str(exc)) from exc

    running = _running_lines(texts)
    by_page: dict[int, list[tuple[int, str]]] = {}
    for level, title, number in outline:
        by_page.setdefault(number, []).append((level, title))
    outline_levels = [level for level, _, number in outline if number <= len(texts)]
    # Pages sit one level below the deepest bookmark, so a bookmark's section
    # runs over its pages up to the next bookmark at its level or above.
    page_level = min(6, max(outline_levels, default=0) + 1)

    paragraphs_by_page = [_paragraphs(_without_running(lines, running)) for lines in texts]
    # A heading inside a page is its own piece for a query, below the page's own
    # heading, so "gross output approach" finds the paragraph under "Gross Output
    # Approach" rather than a table that repeats "gross output".
    sub_level = page_level + 1
    inner = _headings(paragraphs_by_page) if sub_level <= 6 else set()

    blocks: list[pages.Block] = []
    for index, paragraphs in enumerate(paragraphs_by_page):
        number = index + 1
        page_url = f"{url}#{page_anchor(number)}"
        for level, title in by_page.get(number, []):
            blocks.append(
                pages.Block("heading", title, level=min(level, page_level - 1), href=page_url)
            )
        headings = [p for i, p in enumerate(paragraphs) if (index, i) in inner]
        blocks.append(
            pages.Block(
                "heading",
                f"Page {number}" if outline_levels else _page_title(number, paragraphs, headings),
                level=page_level,
                anchor=page_anchor(number),
            )
        )
        for position, paragraph in enumerate(paragraphs):
            if (index, position) in inner:
                blocks.append(pages.Block("heading", paragraph, level=sub_level, href=page_url))
            else:
                blocks.append(pages.Block("text", paragraph))

    title = ""
    try:
        info = reader.metadata
        title = pages.clean(str(info.title)) if info and info.title else ""
    except Exception:  # noqa: BLE001 (damaged document information is not needed)
        title = ""
    page = pages.Page(
        url=url,
        title=title,
        release_date=None,
        archived=False,
        pdf_url=url,
        blocks=blocks,
        links=[],
    )
    return PdfText(page, page_count, len(texts), bool(outline_levels))
