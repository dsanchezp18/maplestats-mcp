"""statcan_reference_get_publication / _get_section_text against trimmed real pages.

The fixtures are StatCan pages fetched live on 2026-11-10 and cut down (each file's
first line names its URL): catalogue pages for 71-543-G (English and French),
62-553-X, 15-203-X (PDF only), 62F0014M2021011 (one article, a formats table) and
13-017-X; the LFS guide's 2025 edition (one long page, with the <p><details> nesting
that html.parser leaves open), the CPI Reference Paper's main page (a table of
contents modal) and its chapter 10, and 13-017-X's 2008-era main page.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from maplestats_mcp.modules.statcan.reference import client, pages
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

FIXTURES = Path(__file__).parent / "fixtures"
N1 = "https://www150.statcan.gc.ca/n1"
LFS_CATALOGUE = f"{N1}/en/catalogue/71-543-G"
LFS_2025 = f"{N1}/pub/71-543-g/71-543-g2025001-eng.htm"
LFS_APPENDICES = [f"{N1}/pub/71-543-g/2025001/app_ann_{x}-eng.htm" for x in "abc"]
CPI_CATALOGUE = f"{N1}/en/catalogue/62-553-X"
CPI_2023 = f"{N1}/pub/62-553-x/62-553-x2023001-eng.htm"
CPI_CHAP_10 = f"{N1}/pub/62-553-x/2023001/chap-10-eng.htm"


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


async def test_get_publication_pdf_only(httpx_mock):
    httpx_mock.add_response(
        url=f"{N1}/en/catalogue/15-203-X", html=_fixture("catalogue_15-203-X_en.html")
    )
    result = await client.get_publication("15-203-X")
    assert result.format == "pdf" and result.sections == []
    assert result.url == result.pdf_url == f"{N1}/pub/15-203-x/15-203-x1999000-eng.pdf"
    assert "PDF only" in (result.provenance.limits or "")


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


async def test_pdf_only_text_gives_the_link(httpx_mock):
    httpx_mock.add_response(
        url=f"{N1}/en/catalogue/15-203-X", html=_fixture("catalogue_15-203-X_en.html")
    )
    result = await client.get_section_text("15-203-X", query="gross output")
    assert result.sections == [] and result.pdf_url and result.pdf_url.endswith(".pdf")


async def test_section_and_query_together_are_refused():
    with pytest.raises(InvalidInput, match="not both"):
        await client.get_section_text("71-543-G", section="a3", query="part-time")


@pytest.mark.parametrize(
    "kwargs", [{"max_chars": 10}, {"max_chars": 10**6}, {"start_char": -1}, {"limit": 9}]
)
async def test_text_arguments_are_checked(kwargs):
    with pytest.raises(InvalidInput):
        await client.get_section_text("71-543-G", **kwargs)
