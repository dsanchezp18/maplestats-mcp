"""statcan_reference_get_publication / _get_section_text against trimmed real pages.

The fixtures are StatCan pages fetched live on 2026-11-10 and cut down (each file's
first line names its URL): catalogue pages for 71-543-G (English and French),
62-553-X, 15-203-X (PDF only), 62F0014M2021011 (one article, a formats table) and
13-017-X; the LFS guide's 2025 edition (one long page, with the <p><details> nesting
that html.parser leaves open), the CPI Reference Paper's main page (a table of
contents modal) and its chapter 10, and 13-017-X's 2008-era main page. PDFs are
built here (`_pdf`), with the running header, wrapped and justified lines and
bookmarks the real ones have.
"""

from __future__ import annotations

import io
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest
from pypdf import PdfWriter

from maplestats_mcp.modules.statcan.reference import client, constants, pages, pdf
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

FIXTURES = Path(__file__).parent / "fixtures"
N1 = "https://www150.statcan.gc.ca/n1"
LFS_CATALOGUE = f"{N1}/en/catalogue/71-543-G"
LFS_2025 = f"{N1}/pub/71-543-g/71-543-g2025001-eng.htm"
LFS_APPENDICES = [f"{N1}/pub/71-543-g/2025001/app_ann_{x}-eng.htm" for x in "abc"]
CPI_CATALOGUE = f"{N1}/en/catalogue/62-553-X"
CPI_2023 = f"{N1}/pub/62-553-x/62-553-x2023001-eng.htm"
CPI_CHAP_10 = f"{N1}/pub/62-553-x/2023001/chap-10-eng.htm"
PGDP_CATALOGUE = f"{N1}/en/catalogue/15-203-X"
PGDP_PDF = f"{N1}/pub/15-203-x/15-203-x1999000-eng.pdf"
HEADER = "Statistics Canada - Catalogue no. 15-203 {n} Statistique Canada"

# Three pages as 15-203-X's methodology section reads: a running header, a heading,
# paragraphs wrapped at the line, a word split at a line end, and the 2006 LFS
# guide's justified lines that come out one word at a time.
PGDP_PAGES = [
    [
        HEADER.format(n=1),
        "Introduction",
        "This publication presents estimates of Gross Domestic Product by industry",
        "for each province and territory, reconciled with the provincial input-output",
        "tables and the provincial economic accounts.",
    ],
    [
        HEADER.format(n=2),
        "Gross Output Approach",
        "This approach consists in allocating national gross output and GDP for a",
        "particular industry based on the provincial distribution of gross output; the",
        "distribution is a valid proxy for intermediate inputs and GDP for the indus-",
        "try in question.",
    ],
    [
        HEADER.format(n=3),
        "Approach based on Selected Factor Incomes",
        "This approach consists in allocating national gross output and GDP based on",
        "the sum of selected factor incomes such as provincial wages and depreciation",
        "or",
        "only",
        "wages.",
    ],
]


Line = str | tuple[str, str]


def _pdf(
    page_lines: Sequence[Sequence[Line]], outline: list[tuple[str, int]] | None = None
) -> bytes:
    """A PDF writing each line with its own text object, as Acrobat Distiller wrote
    StatCan's; a (left, right) pair is a line of two columns, as 15-203-X prints
    English and French side by side. With `outline`, (title, 0-based page)
    bookmarks."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # the page tree, filled in below
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    kids = []
    for lines in page_lines:
        text = b""
        for i, line in enumerate(lines):
            parts = [(40, line)] if isinstance(line, str) else list(zip((40, 320), line))
            for x, part in parts:
                if part:
                    encoded = part.encode("cp1252")
                    text += b"BT /F1 10 Tf %d %d Td (%s) Tj ET\n" % (x, 760 - 14 * i, encoded)
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(text), text))
        content = len(objects)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content
        )
        kids.append(b"%d 0 R" % len(objects))
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(kids), len(kids))
    body = io.BytesIO()
    body.write(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(body.tell())
        body.write(b"%d 0 obj\n%s\nendobj\n" % (number, obj))
    xref = body.tell()
    body.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        body.write(b"%010d 00000 n \n" % offset)
    body.write(b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1))
    body.write(b"startxref\n%d\n%%%%EOF\n" % xref)
    if not outline:
        return body.getvalue()
    writer = PdfWriter(clone_from=io.BytesIO(body.getvalue()))
    for title, page in outline:
        writer.add_outline_item(title, page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# 15-203-X's methodology pages: English on the left, French on the right, under a
# running header in both languages.
BILINGUAL_PARAGRAPHS = [
    (
        ("Gross Output Approach", "Méthode de la production brute"),
        [
            ("This approach consists in allocating the", "Cette méthode consiste à répartir la"),
            ("national gross output and the GDP of an", "production brute et le PIB d'une"),
            ("industry based on the provincial", "industrie donnée à l'échelle nationale"),
            ("distribution of gross output; this is a", "d'après la distribution provinciale de"),
            ("valid proxy for the intermediate inputs", "la production brute, qui est une"),
            ("of the industry in question, which is", "méthode de remplacement valable pour"),
            ("the case for most of the industries.", "la plupart des industries et des cas."),
        ],
    ),
    (
        ("Approach based on Selected Factor Incomes", "Méthode fondée sur certains revenus"),
        [
            ("This approach consists in allocating the", "Cette méthode consiste à répartir le"),
            ("GDP of an industry based on the sum of", "PIB d'une industrie d'après la somme"),
            ("selected factor incomes, such as the", "des revenus de certains facteurs, tels"),
            ("wages and the depreciation of capital", "que les salaires et l'amortissement du"),
            ("that are available by province for it.", "capital qui sont connus par province."),
        ],
    ),
]
OTHER_HEADINGS = [
    ("Net Output Approach", "Méthode de la production nette"),
    ("Other Substitute Approaches", "Autres méthodes de remplacement"),
]


def _bilingual_pages() -> list[list[Line]]:
    """Three such pages: the same paragraphs under each page's own first heading."""
    out: list[list[Line]] = []
    for first in [BILINGUAL_PARAGRAPHS[0][0], *OTHER_HEADINGS]:
        page: list[Line] = [
            ("Provincial Gross Domestic Product, 1999", "Produit intérieur brut provincial, 1999"),
            "",
        ]
        for index, (heading, lines) in enumerate(BILINGUAL_PARAGRAPHS):
            page.extend([first if index == 0 else heading, "", *lines, ""])
        out.append(page)
    return out


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_state():
    cache_module._caches.clear()
    yield


def _lfs(httpx_mock) -> None:
    httpx_mock.add_response(url=LFS_CATALOGUE, html=_fixture("catalogue_71-543-G_en.html"))
    httpx_mock.add_response(url=LFS_2025, html=_fixture("lfs_2025001_en.html"))


def _cpi(httpx_mock, *, chapter: bool = True) -> None:
    httpx_mock.add_response(url=CPI_CATALOGUE, html=_fixture("catalogue_62-553-X_en.html"))
    httpx_mock.add_response(url=CPI_2023, html=_fixture("cpi_2023001_en.html"))
    if chapter:
        httpx_mock.add_response(url=CPI_CHAP_10, html=_fixture("cpi_2023001_chap-10_en.html"))


# --- pages.py: catalogue pages and URLs ----------------------------------------------


def test_catalogue_page_lists_editions_newest_first():
    parsed = pages.parse_catalogue_page(_fixture("catalogue_71-543-G_en.html"), LFS_CATALOGUE)
    assert parsed is not None
    assert parsed.title == "Guide to the Labour Force Survey"
    assert parsed.catalogue_number == "71-543-G"
    assert parsed.product_type is not None and "Documentation" in parsed.product_type
    assert parsed.description and parsed.description.startswith("The Guide to the Labour")
    latest, *_, oldest = parsed.editions
    assert (latest.issue, latest.release_date, latest.format) == (
        "2025001",
        date(2025, 4, 4),
        "html",
    )
    assert latest.catalogue_number == "71-543-G2025001" and not latest.archived
    # The oldest editions are PDF only and marked "- ARCHIVED" in their title.
    assert (oldest.issue, oldest.format, oldest.archived) == ("1999001", "pdf", True)
    assert oldest.title == "Guide to the Labour Force Survey, 1999"


def test_french_catalogue_page():
    parsed = pages.parse_catalogue_page(
        _fixture("catalogue_71-543-G_fr.html"), f"{N1}/fr/catalogue/71-543-G"
    )
    assert parsed is not None
    assert parsed.title == "Guide de l'Enquête sur la population active"
    assert parsed.editions[0].url.endswith("71-543-g2025001-fra.htm")
    assert parsed.editions[0].release_date == date(2025, 4, 4)
    assert parsed.editions[-1].archived  # "- ARCHIVÉ"


def test_article_catalogue_page_has_one_edition_with_both_formats():
    parsed = pages.parse_catalogue_page(
        _fixture("catalogue_62F0014M2021011_en.html"), f"{N1}/en/catalogue/62F0014M2021011"
    )
    assert parsed is not None and parsed.archived
    (edition,) = parsed.editions
    assert edition.url == f"{N1}/pub/62f0014m/62f0014m2021011-eng.htm"
    assert edition.pdf_url == f"{N1}/pub/62f0014m/62f0014m2021011-eng.pdf"
    assert (edition.issue, edition.release_date) == ("2021011", date(2021, 7, 21))


def test_urls():
    assert pages.catalogue_path("71-543-g") == "71-543-G"
    # 12-34-5678 numbers are addressed without hyphens (the hyphenated path is a 404).
    assert pages.catalogue_path("46-28-0001202500100004") == "46280001202500100004"
    assert pages.edition_scope(LFS_2025) == "/n1/pub/71-543-g/2025001/"
    assert pages.edition_of(CPI_CHAP_10) == CPI_2023
    assert pages.edition_of(LFS_2025) == LFS_2025
    article = f"{N1}/pub/46-28-0001/2025001/article/00004-eng.htm"
    assert pages.edition_of(article) == article
    assert pages.page_key(CPI_CHAP_10, CPI_2023) == "chap-10"
    assert pages.page_url_for_key("chap-10", CPI_2023) == CPI_CHAP_10
    assert pages.with_lang(f"{CPI_CHAP_10}#a2", "fr").endswith("chap-10-fra.htm#a2")
    assert pages.normalize_url("/pub/62-553-x/2023001/chap-1-eng.htm", CPI_2023).startswith(
        f"{N1}/pub/62-553-x/2023001/"
    )
    assert pages.parse_date("21 juillet 2021") == date(2021, 7, 21)
    assert pages.parse_date("February 20, 2023") == date(2023, 2, 20)


# --- pages.py: publication pages ----------------------------------------------------


def test_long_page_keeps_every_section_after_a_details_inside_a_paragraph():
    page = pages.parse_page(_fixture("lfs_2025001_en.html"), LFS_2025, "/n1/pub/71-543-g/2025001/")
    titles = [h.title for h in page.headings]
    # Figure 2.1's <details> sits inside a <p>; html.parser left that <p> open and
    # every later heading used to vanish into one paragraph.
    assert "Section 3: Dictionary of concepts and definitions" in titles
    assert "Section 4: Survey methodology" in titles
    assert page.release_date == date(2025, 4, 4)
    assert page.pdf_url == f"{N1}/pub/71-543-g/71-543-g2025001-eng.pdf"
    assert [link.url for link in page.links] == LFS_APPENDICES
    text = pages.render(page.blocks)
    assert "Involuntary part-time rate: The rate of involuntary part-time workers" in text
    # Navigation, screen-reader text and the "More information" modal are gone.
    for junk in ("On this page", "Skip to text", "Note of appreciation", "PDF version"):
        assert junk not in text


def test_table_of_contents_modal_and_footnote_markers():
    page = pages.parse_page(_fixture("cpi_2023001_en.html"), CPI_2023, "/n1/pub/62-553-x/2023001/")
    keys = [pages.page_key(link.url, CPI_2023) for link in page.links]
    assert keys[:2] == ["chap-1", "chap-2"] and "chap-10" in keys and "glos" in keys
    assert page.release_date == date(2023, 2, 20)  # from the "Release date:" label
    text = pages.render(page.blocks)
    assert "published in 2019.[note]" in text
    assert "Table of contents" not in text


def test_2008_layout_drops_archived_notice_and_date_modified():
    url = f"{N1}/pub/13-017-x/13-017-x2008001-eng.htm"
    page = pages.parse_page(_fixture("iea_2008001_en.html"), url, pages.edition_scope(url))
    assert page.archived
    assert page.title == "Guide to the Income and Expenditure Accounts"
    assert len(page.links) == 11
    assert page.links[2].url == f"{N1}/pub/13-017-x/2008001/themes/ch03/5213342-eng.htm"
    text = pages.render(page.blocks)
    assert "Archived Content" not in text and "Date modified" not in text
    assert "View the most recent version" not in text


def test_cut_ends_at_a_paragraph():
    text = "one two three.\n\nfour five six seven.\n\neight"
    piece, end, more = pages.cut(text, 0, 25)
    assert piece == "one two three." and more and text[end:].startswith("four")
    assert pages.cut(text, end, 100) == (text[end:], len(text), False)


# --- client: get_publication ------------------------------------------------------------


async def test_get_publication_latest_edition(httpx_mock):
    _lfs(httpx_mock)
    result = await client.get_publication("71-543-g")
    assert result.catalogue_number == "71-543-G"
    assert (result.issue, result.release_date, result.format) == (
        "2025001",
        date(2025, 4, 4),
        "html",
    )
    assert result.url == LFS_2025
    assert result.pdf_url == f"{N1}/pub/71-543-g/71-543-g2025001-eng.pdf"
    ids = [s.id for s in result.sections]
    assert ids[:2] == ["a1", "h2"]  # an h3 without an id is numbered
    assert "a3" in ids and ids[-3:] == ["app_ann_a", "app_ann_b", "app_ann_c"]
    assert result.editions_total == len(result.editions) == 4
    assert result.provenance.as_of is not None and result.provenance.as_of.year == 2025


def _pgdp(httpx_mock, body: bytes) -> None:
    httpx_mock.add_response(url=PGDP_CATALOGUE, html=_fixture("catalogue_15-203-X_en.html"))
    httpx_mock.add_response(url=PGDP_PDF, content=body)


async def test_get_publication_pdf_only_lists_its_pages(httpx_mock):
    _pgdp(httpx_mock, _pdf(PGDP_PAGES))
    result = await client.get_publication("15-203-X")
    assert result.format == "pdf"
    assert result.url == result.pdf_url == PGDP_PDF
    assert [(s.id, s.title) for s in result.sections] == [
        ("page=1", "Page 1 - Introduction"),
        ("page=2", "Page 2 - Gross Output Approach"),
        ("page=3", "Page 3 - Approach based on Selected Factor Incomes"),
    ]
    assert result.sections[1].url == f"{PGDP_PDF}#page=2"
    limits = result.provenance.limits or ""
    assert "PDF only" in limits and "extracted from the PDF (3 pages)" in limits


async def test_get_publication_pdf_bookmarks_are_its_sections(httpx_mock):
    _pgdp(httpx_mock, _pdf(PGDP_PAGES, outline=[("1. Introduction", 0), ("2. Methodology", 1)]))
    result = await client.get_publication("15-203-X")
    assert [(s.title, s.url) for s in result.sections] == [
        ("1. Introduction", f"{PGDP_PDF}#page=1"),
        ("2. Methodology", f"{PGDP_PDF}#page=2"),
    ]
    # A bookmark's section runs over its pages, up to the next bookmark.
    text = await client.get_section_text("15-203-X", section="2. Methodology")
    section = text.sections[0]
    assert section.url == f"{PGDP_PDF}#page=2"
    assert "## Page 2" in section.text and "Selected Factor Incomes" in section.text


async def test_get_publication_unknown_edition_lists_the_editions(httpx_mock):
    httpx_mock.add_response(url=LFS_CATALOGUE, html=_fixture("catalogue_71-543-G_en.html"))
    with pytest.raises(NotFound, match="2025001, 2020001"):
        await client.get_publication("71-543-G", edition="1990")


async def test_get_publication_unknown_number(httpx_mock):
    httpx_mock.add_response(url=f"{N1}/en/catalogue/99-999-Z", status_code=404, html="<h1>404</h1>")
    with pytest.raises(NotFound, match="statcan_reference_search_documents"):
        await client.get_publication("99-999-Z")


async def test_get_publication_in_french_reads_the_fra_page(httpx_mock):
    httpx_mock.add_response(
        url=f"{N1}/fr/catalogue/71-543-G", html=_fixture("catalogue_71-543-G_fr.html")
    )
    httpx_mock.add_response(
        url=LFS_2025.replace("-eng.htm", "-fra.htm"),
        html="<main><h1>Guide</h1><h2 id='a1'>Section 1 : Contexte</h2><p>Texte.</p></main>",
    )
    result = await client.get_publication("71-543-G", lang="fr")
    assert result.url.endswith("-fra.htm")
    assert result.sections[0].title == "Section 1 : Contexte"
    assert "Lisez une section" in (result.provenance.limits or "")


@pytest.mark.parametrize(
    ("argument", "hint"),
    [
        ("http://localhost:8000/n1/pub/x-eng.htm", "only Statistics Canada"),
        ("https://www150.statcan.gc.ca.evil.example/n1/pub/x-eng.htm", "only Statistics Canada"),
        ("https://www23.statcan.gc.ca/imdb/p2SV.pl?Function=getSurvey&SDDS=3701", "IMDB"),
        ("https://www150.statcan.gc.ca/n1/daily-quotidien/250404/dq250404a-eng.htm", "Daily"),
        ("not a number", "not a catalogue number"),
    ],
)
async def test_get_publication_refuses_other_inputs(argument, hint, httpx_mock):
    with pytest.raises(InvalidInput, match=hint):
        await client.get_publication(argument)
    assert httpx_mock.get_requests() == []


async def test_redirect_off_statcan_is_refused(httpx_mock):
    httpx_mock.add_response(
        url=LFS_CATALOGUE, status_code=301, headers={"Location": "http://169.254.169.254/latest"}
    )
    with pytest.raises(InvalidInput, match="only Statistics Canada"):
        await client.get_publication("71-543-G")
    assert len(httpx_mock.get_requests()) == 1


async def test_redirect_within_statcan_is_followed(httpx_mock):
    moved = f"{N1}/en/catalogue/71-543-G-moved"
    httpx_mock.add_response(url=LFS_CATALOGUE, status_code=301, headers={"Location": moved})
    httpx_mock.add_response(url=moved, html=_fixture("catalogue_71-543-G_en.html"))
    httpx_mock.add_response(url=LFS_2025, html=_fixture("lfs_2025001_en.html"))
    result = await client.get_publication("71-543-G")
    assert result.issue == "2025001"


# --- client: get_section_text -----------------------------------------------------------


async def test_query_finds_the_definition_and_skips_broken_links(httpx_mock):
    _lfs(httpx_mock)
    for url in LFS_APPENDICES:  # broken links inside a publication are skipped
        httpx_mock.add_response(url=url, status_code=404, html="<h1>404</h1>")
    result = await client.get_section_text("71-543-G", query="involuntary part-time")
    best = result.sections[0]
    assert best.id == "a3"
    assert best.url == f"{LFS_2025}#a3"
    assert best.text.startswith("Involuntary part-time rate: The rate of involuntary")
    assert best.start_char > 0 and best.score is not None
    assert result.pages_read == 1
    assert result.release_date == date(2025, 4, 4)


async def test_section_by_id_pages_through_long_text(httpx_mock):
    _lfs(httpx_mock)
    first = await client.get_section_text("71-543-G", section="a3", max_chars=400)
    section = first.sections[0]
    assert section.text.startswith("# Section 3: Dictionary of concepts and definitions")
    assert section.next_start_char is not None and len(section.text) <= 400
    assert "start_char=" in (first.provenance.limits or "")
    second = await client.get_section_text(
        "71-543-G", section="a3", start_char=section.next_start_char, max_chars=400
    )
    assert second.sections[0].start_char == section.next_start_char
    assert second.sections[0].text and second.sections[0].text not in section.text


async def test_section_on_another_page_of_the_edition(httpx_mock):
    _cpi(httpx_mock)
    result = await client.get_section_text("62-553-X", section="chap-10#a2")
    section = result.sections[0]
    assert section.title == "Treatment of Owned Accommodation in the Consumer Price Index"
    assert section.url == f"{CPI_CHAP_10}#a2"
    assert "10.8" in section.text and "10.1 " not in section.text


async def test_section_by_chapter_title(httpx_mock):
    _cpi(httpx_mock)
    result = await client.get_section_text("62-553-X", section="treatment of owned accommodation")
    assert result.sections[0].id == "chap-10"
    assert result.sections[0].text.startswith("# Concepts Surrounding the Treatment")
    assert [s.id for s in result.subsections][:2] == ["chap-10#a1", "chap-10#a2"]


async def test_section_from_a_page_url(httpx_mock):
    httpx_mock.add_response(url=CPI_CATALOGUE, html=_fixture("catalogue_62-553-X_en.html"))
    httpx_mock.add_response(url=CPI_2023, html=_fixture("cpi_2023001_en.html"))
    httpx_mock.add_response(url=CPI_CHAP_10, html=_fixture("cpi_2023001_chap-10_en.html"))
    # A /pub/ link as StatCan writes it, without /n1/.
    result = await client.get_section_text(
        "https://www150.statcan.gc.ca/pub/62-553-x/2023001/chap-10-eng.htm#a1"
    )
    assert result.catalogue_number == "62-553-X"
    assert result.sections[0].id == "chap-10#a1"
    assert result.edition_url == CPI_2023


async def test_unknown_section_names_the_ids(httpx_mock):
    _lfs(httpx_mock)
    for url in LFS_APPENDICES:
        httpx_mock.add_response(url=url, status_code=404, html="<h1>404</h1>")
    with pytest.raises(NotFound, match="a1, h2"):
        await client.get_section_text("71-543-G", section="no such heading anywhere")


async def test_pdf_query_finds_the_page(httpx_mock):
    _pgdp(httpx_mock, _pdf(PGDP_PAGES))
    result = await client.get_section_text("15-203-X", query="selected factor incomes")
    best = result.sections[0]
    # "Approach based on Selected Factor Incomes" (one word in lower case among
    # five) is a heading of its own inside page 3.
    assert (result.format, best.title, best.url) == (
        "pdf",
        "Approach based on Selected Factor Incomes",
        f"{PGDP_PDF}#page=3",
    )
    # The lines are one paragraph; the one-word lines run on.
    assert "selected factor incomes such as provincial wages and depreciation or only wages." in (
        best.text
    )
    assert result.pages_read == 3
    limits = result.provenance.limits or ""
    assert "extracted from the PDF" in limits
    # The hint pointing to 15-203-X is not shown on 15-203-X itself.
    assert "pages 188 to 196" not in limits


@pytest.mark.parametrize("section", ["page=2", "2", "p2", "page 2"])
async def test_pdf_page_by_number(section, httpx_mock):
    _pgdp(httpx_mock, _pdf(PGDP_PAGES))
    result = await client.get_section_text("15-203-X", section=section)
    text = result.sections[0].text
    assert text.startswith("# Page 2 - Gross Output Approach")
    # The running header is dropped and the word split at the line end is joined.
    assert "Catalogue no." not in text and "for the industry in question." in text


async def test_pdf_url_as_publication_and_a_heading_inside_a_page(httpx_mock):
    httpx_mock.add_response(url=PGDP_PDF, content=_pdf(PGDP_PAGES))
    result = await client.get_section_text(PGDP_PDF, query="gross output approach", limit=1)
    best = result.sections[0]
    assert result.format == "pdf"
    # "Gross Output Approach", a title-case line before a paragraph, is a heading of
    # its own inside page 2.
    assert (best.title, best.url) == ("Gross Output Approach", f"{PGDP_PDF}#page=2")
    assert best.text.startswith("This approach consists in allocating national gross output")
    again = await client.get_section_text(PGDP_PDF, section=best.id)
    assert again.sections[0].text.startswith("# Gross Output Approach")


def test_pdf_headings_skip_table_rows_and_repeated_lines():
    assert pdf.looks_like_heading("Gross Output Approach")
    assert pdf.looks_like_heading("2.iii. Constant Price GDP Estimates")
    assert not pdf.looks_like_heading("E159 Other Rubber Products Gross output Industries")
    assert not pdf.looks_like_heading("This approach consists in allocating national output.")
    assert not pdf.looks_like_heading("Quebec")  # one word: a table's row label
    paragraph = "A paragraph of running text that is long enough to follow a heading."
    by_page = [["Running Title Here", paragraph], ["Running Title Here", paragraph]] * 2
    assert pdf._headings(by_page) == set()  # on more than two pages: a running title


async def test_pdf_that_is_not_a_pdf_is_an_upstream_error(httpx_mock):
    _pgdp(httpx_mock, b"<html>maintenance</html>")
    with pytest.raises(UpstreamError, match="could not be read as a PDF"):
        await client.get_section_text("15-203-X", query="gross output")


async def test_pdf_over_the_size_cap_is_refused(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "PDF_MAX_BYTES", 1000)
    _pgdp(httpx_mock, b"%PDF-1.4" + b"x" * 5000)
    with pytest.raises(UpstreamError, match="1,000"):
        await client.get_publication("15-203-X")


def test_pdf_page_cap_reads_the_first_pages():
    document = pdf.extract(_pdf(PGDP_PAGES), PGDP_PDF, max_pages=2, max_chars=10**6, seconds=60.0)
    assert (document.page_count, document.pages_read) == (3, 2)
    assert [h.anchor for h in document.page.headings] == ["page=1", "page=2"]


@pytest.mark.parametrize(
    ("lang", "heading", "kept", "dropped"),
    [
        ("en", "Gross Output Approach", "allocating the national gross output", "répartir"),
        ("fr", "Méthode de la production brute", "consiste à répartir la production", "allocating"),
    ],
)
async def test_bilingual_two_column_pdf_keeps_the_column_in_lang(
    lang, heading, kept, dropped, httpx_mock
):
    # Plain extraction reads such a page line by line across both columns; the
    # columns are read one at a time and only the one in `lang` is kept.
    httpx_mock.add_response(url=PGDP_PDF, content=_pdf(_bilingual_pages()))
    result = await client.get_section_text(PGDP_PDF, section="page=1", lang=lang)
    text = result.sections[0].text
    assert text.startswith(f"# Page 1 - {heading}\n\n## {heading}\n")
    assert kept in text and dropped not in text
    # The running header's half in that column is dropped too.
    assert "1999" not in text
    limits = result.provenance.limits or ""
    assert "3 pages" in limits and ("English column" in limits or "colonne française" in limits)


def test_two_columns_in_one_language_are_read_one_after_the_other():
    left = [f"English text line {n} of the left column" for n in range(8)]
    right = [f"and the right column holds line {n} too" for n in range(8)]
    layout = "\n".join(f"{a:<60}{b}" for a, b in zip(left, right, strict=True))
    segments = pdf.columns(layout)
    assert segments is not None
    pieces, dropped = pdf._pick_columns(segments, "en")
    assert not dropped
    assert [line for piece in pieces for line in piece] == [*left, *right]


def test_a_table_is_not_cut_into_columns():
    rows = [f"Industry {n}        {n * 10}        {n * 7.5}        {n * 3}" for n in range(10)]
    assert pdf.columns("\n".join(f"{row:<60}{row}" for row in rows)) is None


def test_language_of_a_column():
    assert (
        pdf.language(
            "This approach consists in allocating the output of the industry to the provinces, which is the case for most of them."
        )
        == "en"
    )
    assert (
        pdf.language(
            "Cette méthode consiste à répartir la production de l'industrie entre les provinces, ce qui est le cas pour la plupart des industries."
        )
        == "fr"
    )
    assert pdf.language("172 75.4 226261 37.4") is None


def test_pdf_table_labels_are_not_headings():
    assert not pdf.looks_like_heading("NFLD. - T.-N.")
    assert not pdf.looks_like_heading("Table 1")
    assert pdf.looks_like_heading("Approach based on Selected Factor Incomes")
    # A label in a table is followed by figures, not by running text.
    row = "E159 R3069 Gross output 1,234 2,345 3,456 4,567 5,678 6,789 7,890 8,901 9,012"
    by_page = [["Vanity Industries", row]]
    assert pdf._headings(by_page) == set()


async def test_large_edition_searches_its_whole_pdf_past_the_page_cap(httpx_mock, monkeypatch):
    # 13-017-X's 2008 edition: 146 HTML pages, more than CRAWL_MAX_PAGES, and a PDF
    # of the whole edition linked from its side menu (outside role=main).
    monkeypatch.setattr(constants, "CRAWL_MAX_PAGES", 2)
    base = f"{N1}/pub/13-017-x"
    main = f"{base}/13-017-x2008001-eng.htm"
    whole = f"{base}/13-017-x2008001-eng.pdf"
    chapters = [f"{base}/2008001/themes/ch0{n}/52133{n}0-eng.htm" for n in range(1, 4)]
    links = "".join(f'<li><a href="{url}">Chapter {n}</a></li>' for n, url in enumerate(chapters))
    httpx_mock.add_response(url=f"{N1}/en/catalogue/13-017-X", status_code=404, html="<h1/>")
    httpx_mock.add_response(
        url=main,
        html=f"""<html><body><div role="main"><h1>Guide</h1><p>Overview.</p><ul>{links}</ul>
        </div><nav><a href="/pub/13-017-x/13-017-x2008001-eng.pdf">PDF version</a></nav>
        </body></html>""",
    )
    first = "Games of chance are the sales of lottery tickets net of prizes awarded."
    httpx_mock.add_response(url=chapters[0], html=f"<main><h1>Chapter 1</h1><p>{first}</p></main>")
    httpx_mock.add_response(url=chapters[1], is_optional=True, html="<main><h1>C</h1></main>")
    httpx_mock.add_response(url=chapters[2], is_optional=True, html="<main><h1>C</h1></main>")
    httpx_mock.add_response(
        url=whole,
        content=_pdf(
            [
                ["Chapter 1", first],
                [
                    "Chapter 3",
                    "Lottery winnings are not income: they are transfers between",
                    "households, and lottery sales net of prizes are output.",
                ],
            ]
        ),
    )
    result = await client.get_section_text(main, query="lottery")
    urls = [s.url for s in result.sections]
    # Page 1 of the PDF is chapter 1's text, read already: the HTML page stands
    # for it; page 2 is only in the PDF.
    assert chapters[0] in urls and f"{whole}#page=2" in urls
    assert f"{whole}#page=1" not in urls
    assert "whole PDF" in (result.provenance.limits or "")


def _lfs_appendices_missing(httpx_mock) -> None:
    for url in LFS_APPENDICES:
        httpx_mock.add_response(url=url, status_code=404, html="<h1>404</h1>", is_optional=True)


async def test_query_hint_for_supplementary_unemployment_rates(httpx_mock):
    _lfs(httpx_mock)
    _lfs_appendices_missing(httpx_mock)
    result = await client.get_section_text("71-543-G", query="supplementary unemployment rates R8")
    limits = result.provenance.limits or ""
    assert limits.startswith("The supplementary unemployment rates R1 to R8 are not defined")
    assert "14-10-0077-01" in limits


async def test_query_hint_for_provincial_allocation(httpx_mock):
    _lfs(httpx_mock)
    _lfs_appendices_missing(httpx_mock)
    result = await client.get_section_text("71-543-G", query="gross output approach")
    assert "15-203-X" in (result.provenance.limits or "")


async def test_query_reads_matching_chapters_first_and_stops(httpx_mock):
    _cpi(httpx_mock)
    other = re.compile(re.escape(f"{N1}/pub/62-553-x/2023001/") + r"(?!chap-10-).*-eng\.htm")
    httpx_mock.add_response(
        url=other,
        html="<main><h1>Other</h1><p>Nothing here.</p></main>",
        is_optional=True,
        is_reusable=True,
    )
    result = await client.get_section_text("62-553-X", query="owned accommodation", limit=2)
    assert [s.id for s in result.sections] == ["chap-10#a2", "chap-10#a1"]
    requested = [str(r.url) for r in httpx_mock.get_requests()]
    # Chapter 10's title holds both words, so it is the first chapter fetched, and
    # the search stops before reading all eleven.
    assert requested[2] == CPI_CHAP_10
    assert len(requested) < 2 + 11
    assert "stopped once 2 sections held every word" in (result.provenance.limits or "")


async def test_query_on_one_long_page_fetches_nothing_else(httpx_mock):
    _lfs(httpx_mock)  # no appendix registered: the main page alone is enough
    result = await client.get_section_text("71-543-G", query="involuntary part-time", limit=1)
    assert result.sections[0].id == "a3" and result.pages_read == 1


async def test_section_by_a_page_id_deeper_than_the_main_page(httpx_mock):
    main = f"{N1}/pub/13-607-x/13-607-x2016001-eng.htm"
    deep = f"{N1}/pub/13-607-x/2016001/224-eng.htm"
    httpx_mock.add_response(url=f"{N1}/en/catalogue/13-607-X", status_code=404, html="<h1/>")
    httpx_mock.add_response(url=main, html="<main><h1>Guide</h1><p>Overview.</p></main>")
    httpx_mock.add_response(
        url=deep, html="<main><h1>Provincial GDP</h1><p>GDP by province.</p></main>"
    )
    result = await client.get_section_text(main, section="224")
    assert (result.sections[0].id, result.sections[0].title) == ("224", "Provincial GDP")


async def test_windows_1252_page_sent_as_utf8_is_decoded(httpx_mock):
    url = f"{N1}/pub/71-543-g/71-543-g2008001-eng.htm"
    html = "<main><h1>Dictionnaire</h1><p>Données sur la durée du chômage.</p></main>"
    httpx_mock.add_response(url=f"{N1}/en/catalogue/71-543-G", status_code=404, html="<h1/>")
    httpx_mock.add_response(
        url=url,
        content=html.encode("cp1252"),
        headers={"Content-Type": "text/html; charset=UTF-8"},
    )
    result = await client.get_section_text(url)
    assert "Données sur la durée du chômage." in result.sections[0].text


def test_clf2_layout_reads_div_center_and_drops_the_archived_notice():
    html = """<html><body><div class="page"><div class="core">
      <div class="fp"><h1 class="navaid">Common menu bar links</h1><ul><li>Home</li></ul></div>
      <div class="left"><a href="/pub/71-543-g/2008001/5204012-eng.htm">Sections</a></div>
      <div class="center"><h1><a name="cont" id="cont"></a></h1>
        <div id="archived"><h2>Archived Content</h2><p>Information identified as archived.</p>
        </div>
        <h1 class="tableNo">Section 3: Dictionary of concepts and definitions</h1>
        <p>Employment: Employed persons are those who worked.</p>
        <div class="table_toc_buttons"><form><input value="Next"/></form></div>
        <div class="footer">Date Modified: 2008-05-27 Top of Page Important Notices</div>
      </div></div></div></body></html>"""
    url = f"{N1}/pub/71-543-g/2008001/5204157-eng.htm"
    page = pages.parse_page(html, url, "/n1/pub/71-543-g/2008001/")
    assert page.title == "Section 3: Dictionary of concepts and definitions"
    assert page.archived and page.headings == []
    assert [b.text for b in page.blocks] == ["Employment: Employed persons are those who worked."]


async def test_section_and_query_together_are_refused():
    with pytest.raises(InvalidInput, match="not both"):
        await client.get_section_text("71-543-G", section="a3", query="part-time")


@pytest.mark.parametrize(
    "kwargs", [{"max_chars": 10}, {"max_chars": 10**6}, {"start_char": -1}, {"limit": 9}]
)
async def test_text_arguments_are_checked(kwargs):
    with pytest.raises(InvalidInput):
        await client.get_section_text("71-543-G", **kwargs)
