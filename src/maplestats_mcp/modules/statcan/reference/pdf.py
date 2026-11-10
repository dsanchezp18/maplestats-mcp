"""Text of a StatCan PDF publication, read with pypdf (no I/O).

For editions published as PDF only: the Provincial Gross Domestic Product by
Industry PDFs (15-203-X, 1998 and 1999, 277 pages), the Guide to the Labour
Force Survey up to 2006 (71-543-G), and the 2008-era guides that also ship a
PDF of the whole edition (13-017-X2008001, 297 pages). Checked live 2026-11-10.

What the files look like, and what this module does about it:

- the text of a page comes out line by line, in reading order for one-column
  pages. Two-column bilingual pages (15-203-X: English on the left, French on
  the right) come out interleaved, with accented words split ("constitu ées").
  A page with plenty of both English and French words is laid out again with
  pypdf's layout mode, which places each text run on a grid of characters; a
  run of blank characters down the middle with text on both sides is the
  gutter, and each band of two-column prose (not a table: no cell gaps) is cut
  there and read a column at a time. The column in the requested language is
  kept, told apart by English and French function words; both, labelled, when
  that cannot be told. A table across the page stays as it was. Layout mode
  costs about as much again as the plain extraction, so only those pages pay
  it (78 of 15-203-X's 277);
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
  below the page's, so a query scores the text under it on its own, when the
  paragraph after it is running text: a table's labels ("Vanity Industries",
  "NFLD. - T.-N.", "Table 1") are not. On a two-column page, French headings in
  sentence case ("Méthode de la production brute") count too.

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
_WORD = re.compile(r"[^\W\d_]+")
# Function words for telling an English column from a French one: cheap, and enough
# on a paragraph of either (a page column of 15-203-X holds hundreds of words).
_EN_WORDS = frozenset(
    [
        "the",
        "and",
        "of",
        "to",
        "in",
        "is",
        "are",
        "for",
        "by",
        "which",
        "this",
        "that",
        "with",
        "be",
        "on",
        "as",
        "from",
        "or",
        "it",
        "its",
        "was",
        "were",
        "has",
        "have",
        "been",
        "not",
        "these",
        "those",
        "than",
    ]
)
_FR_WORDS = frozenset(
    [
        "le",
        "la",
        "les",
        "des",
        "du",
        "de",
        "et",
        "est",
        "une",
        "un",
        "pour",
        "dans",
        "par",
        "qui",
        "sur",
        "au",
        "aux",
        "que",
        "ne",
        "pas",
        "sont",
        "ces",
        "cette",
        "leur",
        "ont",
        "été",
        "entre",
        "selon",
    ]
)
# French words that are not also in place names ("Rivière-du-Loup", "Baie-de-la-
# Trinité" fill the 2006 LFS guide's English lists of CMA parts): the test for a
# page holding French at all.
_FR_SENTENCE_WORDS = frozenset(
    [
        "est",
        "et",
        "une",
        "pour",
        "dans",
        "qui",
        "que",
        "ne",
        "pas",
        "sont",
        "ces",
        "cette",
        "ont",
        "été",
        "aux",
        "par",
        "leur",
        "selon",
    ]
)
_GUTTER_SPACES = 2  # blank character columns, at least, between two text columns
_TABLE_GAP = re.compile(r"\S {4,}\S")  # a cell gap inside one column's line


class PdfUnreadable(ValueError):
    """The bytes are not a PDF pypdf can open (damaged, encrypted, not a PDF)."""


@dataclass
class PdfText:
    page: pages.Page
    page_count: int  # pages in the file
    pages_read: int  # pages whose text was extracted, from the first
    has_outline: bool
    # Two-column pages with English in one column and French in the other, of which
    # only the column in the requested language was kept.
    bilingual_pages: int = 0
    # Two-column pages read a column at a time with both columns kept (the same
    # language in each, or a language that could not be told).
    two_column_pages: int = 0


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


def _is_running(key: str, running: set[str], *, part: bool) -> bool:
    # A column of a two-column page holds its half of the running header
    # ("Provincial Gross Domestic Product by Industry, 1984-1999" without its
    # French half), so there (`part`) a long enough part of a running line counts
    # too. Not on other pages: the 2006 LFS guide's cover line "Catalogue no.
    # 71-543-GIE Guide to the Labour" is part of its running footer.
    return key in running or (part and len(key) >= 15 and any(key in o for o in running))


def _without_running(lines: list[str], running: set[str], *, columned: bool = False) -> list[str]:
    """The page's lines less a running header or footer among its first and last
    lines (blank lines, paragraph breaks of a two-column page, not counted)."""
    filled = [index for index, line in enumerate(lines) if line]
    edges = set(filled) if len(filled) <= 2 * _EDGE else {*filled[:_EDGE], *filled[-_EDGE:]}
    return [
        line
        for index, line in enumerate(lines)
        if not (index in edges and _is_running(_line_key(line), running, part=columned))
    ]


def language(text: str) -> str | None:
    """'en' or 'fr' when one language's function words clearly outnumber the
    other's in `text`, else None (too short, a table, or mixed)."""
    words = [w.lower() for w in _WORD.findall(text)]
    english = sum(1 for w in words if w in _EN_WORDS)
    french = sum(1 for w in words if w in _FR_WORDS)
    if english >= 5 and english >= 2 * french:
        return "en"
    if french >= 5 and french >= 2 * english:
        return "fr"
    return None


def _bilingual(text: str) -> bool:
    """Plenty of both English and French function words on one page: only such a
    page is laid out again to look for two columns (a cheap test first, since
    layout extraction costs as much again as the plain one)."""
    words = [w.lower() for w in _WORD.findall(text)]
    english = sum(1 for w in words if w in _EN_WORDS)
    french = sum(1 for w in words if w in _FR_WORDS)
    sentences = sum(1 for w in words if w in _FR_SENTENCE_WORDS)
    return (
        min(english, french) >= 15
        and min(english, french) >= 0.25 * max(english, french)
        and sentences >= 5
    )


def _side_ok(text: str) -> bool:
    """One column's part of a line: no cell gap inside it (a table row has them),
    other than after a heading's number ("2.ii.     Autres méthodes")."""
    return not _TABLE_GAP.search(_SECTION_NUMBER.sub("", text.strip(), count=1))


def _gutter(lines: list[str]) -> int | None:
    """The character column between the two text columns of a page laid out by
    pypdf's layout mode, or None: the column in the page's middle (30 to 70% of its
    width), blank with blank neighbours, that the most lines have text on both
    sides of; at least six such lines."""
    filled = [line for line in lines if line.strip()]
    if len(filled) < 8:
        return None
    width = max(len(line) for line in filled)
    counts: dict[int, int] = {}
    for cut in range(int(width * 0.3), int(width * 0.7) + 1):
        counts[cut] = sum(
            1
            for line in filled
            if not line[cut - 1 : cut + _GUTTER_SPACES - 1].strip()
            and line[:cut].strip()
            and line[cut:].strip()
            and _side_ok(line[:cut])
            and _side_ok(line[cut:])
        )
    most = max(counts.values(), default=0)
    if most < 6:
        return None
    # The gutter is several characters wide: its middle, for ragged left lines.
    best = [cut for cut, count in counts.items() if count >= 0.9 * most]
    return best[len(best) // 2]


Segment = tuple[list[str], list[str]] | list[str]


def columns(layout: str) -> list[Segment] | None:
    """A page laid out by pypdf's layout mode (text placed on a grid of
    characters) cut into its two-column bands, as (left lines, right lines), and
    the lines between them (a table, a title across the page, the running footer)
    as they are; None when the page has no band of two columns of prose.

    A band is a run of lines that are blank at the gutter and hold no table cell
    gap on either side, with at least three lines holding text on both sides;
    blank lines (paragraph breaks) stay in it. 15-203-X page 194: a bilingual
    table across the page, then two columns of text.
    """
    lines = [line.rstrip() for line in layout.splitlines()]
    cut = _gutter(lines)
    if cut is None:
        return None

    def fits(line: str) -> bool:
        return (
            not line[cut - 1 : cut + _GUTTER_SPACES - 1].strip()
            and _side_ok(line[:cut])
            and _side_ok(line[cut:])
        )

    segments: list[Segment] = []
    run: list[str] = []

    def close() -> None:
        two_sided = sum(1 for line in run if line[:cut].strip() and line[cut:].strip())
        if two_sided >= 3:
            segments.append(([line[:cut] for line in run], [line[cut:] for line in run]))
        elif run:
            segments.append(list(run))
        run.clear()

    for line in lines:
        if fits(line):
            run.append(line)
        else:
            close()
            segments.append([line])
    close()
    if not any(isinstance(segment, tuple) for segment in segments):
        return None
    return segments


def _column_lines(column: list[str]) -> list[str]:
    """Lines cleaned, with runs of blank lines (paragraph breaks in the layout)
    kept as one blank line."""
    out: list[str] = []
    for line in column:
        text = pages.clean(line)
        if text or (out and out[-1]):
            out.append(text)
    while out and not out[-1]:
        out.pop()
    return out


def _pick_columns(segments: list[Segment], lang: str) -> tuple[list[list[str]], bool]:
    """(pieces, a column was dropped) of a page cut by `columns`, each piece a run
    of lines read top to bottom: in each band, the column in `lang` when the
    page's left columns are in one of English and French and its right columns in
    the other; both, left first, when they share a language; both, labelled, when
    a side's language cannot be told."""
    bands = [segment for segment in segments if isinstance(segment, tuple)]
    left_lang = language(" ".join(" ".join(left) for left, _ in bands))
    right_lang = language(" ".join(" ".join(right) for _, right in bands))
    split = bool(left_lang and right_lang and left_lang != right_lang)
    pieces: list[list[str]] = []
    for segment in segments:
        if not isinstance(segment, tuple):
            pieces.append(_column_lines(segment))
            continue
        left, right = _column_lines(segment[0]), _column_lines(segment[1])
        if split:
            pieces.append(left if left_lang == lang else right)
        elif left_lang and left_lang == right_lang:
            pieces.extend([left, right])
        else:
            pieces.extend([["[Left column]", *left], ["[Right column]", *right]])
    return [piece for piece in pieces if piece], split


def _capitals(line: str) -> bool:
    """A line of words in capitals, no figures ("PROVINCIAL GROSS DOMESTIC"), not a
    table's row of codes ("SR_Q01", "AB 260 300")."""
    words = line.split()
    return (
        line.isupper()
        and len(words) >= 2
        and not any(ch.isdigit() or ch == "_" for ch in line)
        and all(len(word) >= 2 for word in words)
    )


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
        # A title in capitals set over several lines ("SOURCES AND METHODS OF" /
        # "PROVINCIAL GROSS DOMESTIC") is one paragraph.
        runs_on = following[:1].islower() or (
            _capitals(line) and _capitals(following) and not line.endswith(_SENTENCE_END)
        )
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


def looks_like_heading(paragraph: str, *, sentence_case: bool = False) -> bool:
    """One short title-case line of two words or more ("Gross Output Approach",
    "2.iii. Constant Price GDP Estimates"), not a sentence or a table row ("E159
    Other Rubber Products Gross output Industries" has a code in it, "Table 1" a
    number). With `sentence_case`, a line of eight words at most in sentence case
    too, as French headings are ("Méthode de la production brute")."""
    text = _SECTION_NUMBER.sub("", paragraph)
    words = text.split()
    if not 2 <= len(words) <= 10 or len(paragraph) > 80 or text.endswith((".", ",", ";", ":")):
        return False
    if any(ch.isdigit() for ch in text) or not words[0][:1].isupper():
        return False
    if not all(_LETTER.search(word) for word in words):
        return False  # "NFLD. - T.-N.", "Total * $": a table's labels
    major = [w for w in words if w.lower() not in _MINOR_WORDS]
    capitalized = [w for w in major if w[:1].isupper()]
    # One word in lower case among four or more ("Approach based on Selected
    # Factor Incomes").
    lower = len(major) - len(capitalized)
    if text.isupper() or lower == 0 or (lower == 1 and len(major) >= 4):
        return True
    return sentence_case and len(words) <= 8


def _running_text(paragraph: str) -> bool:
    """A paragraph of sentences, not a table row run together ("Vanity Industries"
    followed by codes and figures is a table cell, not a heading): long enough,
    few digits, and English or French function words in it."""
    if len(paragraph) < 60:
        return False
    digits = sum(1 for ch in paragraph if ch.isdigit())
    words = [w.lower() for w in _WORD.findall(paragraph)]
    function = sum(1 for w in words if w in _EN_WORDS or w in _FR_WORDS)
    return digits <= 0.1 * len(paragraph) and function >= max(2, 0.15 * len(words))


def _headings(
    by_page: list[list[str]], columned: frozenset[int] = frozenset()
) -> set[tuple[int, int]]:
    """(page index, paragraph index) of the paragraphs taken as headings: those that
    look like one, come before a paragraph of running text, and appear at most
    twice in the file (a column label of the statistical tables, a running title
    the header check missed, such as "The Canadian Consumer Price Index Reference
    Paper", comes back on many pages). On the two-column pages (`columned`, page
    indexes), a heading in sentence case counts too when the paragraph before it
    is running text, a heading or none, so a short line inside a table is not
    one: 15-203-X's French headings are in sentence case. Elsewhere the last line
    of a sentence cut by a page break ("The definition was changed in") would be
    taken for one."""
    seen: Counter[str] = Counter()
    for paragraphs in by_page:
        seen.update(p for p in paragraphs if looks_like_heading(p, sentence_case=True))
    found: set[tuple[int, int]] = set()
    for page, paragraphs in enumerate(by_page):
        for index, paragraph in enumerate(paragraphs[:-1]):
            following = paragraphs[index + 1]
            if seen[paragraph] > 2 or not _running_text(following):
                continue
            before = paragraphs[index - 1] if index else ""
            if looks_like_heading(paragraph) or (
                page in columned
                and looks_like_heading(paragraph, sentence_case=True)
                and (not before or _running_text(before) or (page, index - 1) in found)
            ):
                found.add((page, index))
    return found


def _page_title(number: int, paragraphs: list[str], headings: list[str]) -> str:
    first = headings[0] if headings else ""
    first = first or next((p for p in paragraphs if any(ch.isalpha() for ch in p)), "")
    if len(first) > 70:
        first = first[:70].rsplit(" ", 1)[0] + "..."
    return f"Page {number} - {first}" if first else f"Page {number}"


def extract(
    body: bytes, url: str, *, max_pages: int, max_chars: int, seconds: float, lang: str = "en"
) -> PdfText:
    """The PDF's text as a pages.Page, from its first page until the last page or
    until `max_pages` pages, `max_chars` characters or `seconds` of work. On a
    two-column page with English in one column and French in the other, only the
    `lang` column is kept."""
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
        plain: list[list[str]] = []  # as extracted, for finding the running header
        total = 0
        bilingual = two_column = 0
        # Pages read a column at a time: their pieces (see _pick_columns).
        columned: dict[int, list[list[str]]] = {}
        for index in range(min(page_count, max_pages)):
            check_deadline()
            text = _GLYPHS.sub("", reader.pages[index].extract_text() or "")
            lines = [pages.clean(line) for line in text.replace("\r", "\n").split("\n")]
            plain.append(lines)
            split = None
            if _bilingual(text):
                # 15-203-X prints English and French side by side: the plain text
                # interleaves them (and splits accented words, "constitu ées"). The
                # layout mode keeps each run where it sits, so the columns separate.
                layout = reader.pages[index].extract_text(extraction_mode="layout")
                split = columns(_GLYPHS.sub("", layout or ""))
            if split is not None:
                columned[index], dropped = _pick_columns(split, lang)
                bilingual += dropped
                two_column += not dropped
            texts.append(lines)
            total += len(text)
            if total > max_chars or time.monotonic() - started > seconds:
                break
    except PdfReadError as exc:
        raise PdfUnreadable(str(exc)) from exc

    running = _running_lines(plain)
    # A column holds its half of the running header and footer at its own top or
    # bottom, so each piece is cleared of them, not the page as a whole.
    for index, pieces in columned.items():
        joined: list[str] = []
        for piece in pieces:
            joined.extend(["", *_without_running(piece, running, columned=True)])
        texts[index] = _column_lines(joined)
    by_page: dict[int, list[tuple[int, str]]] = {}
    for level, title, number in outline:
        by_page.setdefault(number, []).append((level, title))
    outline_levels = [level for level, _, number in outline if number <= len(texts)]
    # Pages sit one level below the deepest bookmark, so a bookmark's section
    # runs over its pages up to the next bookmark at its level or above.
    page_level = min(6, max(outline_levels, default=0) + 1)

    paragraphs_by_page = [
        _paragraphs(lines if index in columned else _without_running(lines, running))
        for index, lines in enumerate(texts)
    ]
    # A heading inside a page is its own piece for a query, below the page's own
    # heading, so "gross output approach" finds the paragraph under "Gross Output
    # Approach" rather than a table that repeats "gross output".
    sub_level = page_level + 1
    inner = _headings(paragraphs_by_page, frozenset(columned)) if sub_level <= 6 else set()

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
    return PdfText(page, page_count, len(texts), bool(outline_levels), bilingual, two_column)
