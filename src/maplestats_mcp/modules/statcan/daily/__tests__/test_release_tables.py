"""The release's own tables (statcan_daily_get_release_tables) and number text.

Fixtures are trimmed from the live pages read on 2026-11-07: the January 2018 LFS
release (dq180209a, its Table 3 by province, English and French) and Table 1 of the
November 2012 CPI release (t121221b001, the pre-2014 file name, no <main>).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from maplestats_mcp.modules.statcan.daily import client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

_FIXTURES = Path(__file__).parent / "fixtures"
_DAY = "https://www150.statcan.gc.ca/n1/daily-quotidien/180209"
_ARTICLE_EN = f"{_DAY}/dq180209a-eng.htm"
_ARTICLE_FR = f"{_DAY}/dq180209a-fra.htm"


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _text(html: str) -> str:
    return client._text(BeautifulSoup(html, "html.parser"))


# Paragraphs as the live pages write them: StatCan wraps the sign and first digit of
# a negative number in <span class="nowrap">.
@pytest.mark.parametrize(
    ("html", "expected"),
    [
        # dq180209a-eng, January 2018 LFS: the case that came out as "( -1 37,000)".
        (
            (
                'Part-time employment declined (<span class="nowrap">-1</span>37,000), while '
                "full-time employment was up (+49,000)."
            ),
            (
                "Part-time employment declined (-137,000), while full-time employment was up "
                "(+49,000)."
            ),
        ),
        (
            (
                'fewer people working part time (<span class="nowrap">-1</span>25,000&#160;or '
                '<span class="nowrap">-3</span>.5%)'
            ),
            "fewer people working part time (-125,000 or -3.5%)",
        ),
        # dq180209a-fra: spaces for thousands, decimal comma, space before %.
        (
            (
                'Le travail &#224; temps partiel a connu un recul (<span class="nowrap">-1</span>'
                "37&#160;000), le taux de ch&#244;mage a augment&#233; de&#160;0,1&#160;point "
                "pour s'&#233;tablir &#224;&#160;5,9&#160;%."
            ),
            (
                "Le travail à temps partiel a connu un recul (-137 000), le taux de chômage a "
                "augmenté de 0,1 point pour s'établir à 5,9 %."
            ),
        ),
        # dq261106a-fra, October 2026 LFS.
        (
            (
                'l\'&#206;le-du-Prince-&#201;douard (<span class="nowrap">-1</span>&#160;300; '
                '<span class="nowrap">-1</span>,3&#160;%)'
            ),
            "l'Île-du-Prince-Édouard (-1 300; -1,3 %)",
        ),
        # dq261019a-eng (CPI, September 2026) and dq121130a-eng (GDP, 2012).
        (
            'fresh vegetables (<span class="nowrap">-2</span>.9%) and sugar',
            "fresh vegetables (-2.9%) and sugar",
        ),
        (
            'Mining and oil and gas extraction (<span class="nowrap">-2</span>.0%) and',
            "Mining and oil and gas extraction (-2.0%) and",
        ),
        # A Unicode minus reads as an ASCII one.
        ("prices fell &#8722;2.3% and 1&#8722;2 points", "prices fell -2.3% and 1-2 points"),
        # Typographic superscripts stay attached; screen-reader text is its own phrase.
        (
            "le&#160;1<sup>er</sup>&#160;mars, vol.&#160;94, n<sup>o</sup>&#160;11",
            "le 1er mars, vol. 94, no 11",
        ),
        (
            (
                'dashboard (<a href="x"><span class="navaid">Catalogue number</span>71-607-X</a>) '
                'and (<a><span class="wb-inv">Catalogue number</span>71-001-X</a>)'
            ),
            "dashboard (Catalogue number 71-607-X) and (Catalogue number 71-001-X)",
        ),
        # Block elements still separate words, with or without whitespace around them.
        ("<div><p>One</p>two<ul><li>a</li><li>b</li></ul></div>", "One two a b"),
    ],
)
def test_text_keeps_numbers_whole(html, expected):
    assert _text(html) == expected


async def test_article_text_and_release_tables(httpx_mock):
    httpx_mock.add_response(url=_ARTICLE_EN, text=_fixture("dq180209a_eng.htm"))
    article = await client.get_article("dq180209a")
    first = article.sections[0].text
    assert "Part-time employment declined (-137,000)" in first
    assert "(-125,000 or -3.5%)" in first
    assert [(t.number, t.title) for t in article.release_tables] == [
        ("Table 1", "Labour force characteristics by age group and sex – Seasonally adjusted"),
        (
            "Table 2",
            "Employment by class of worker and industry (based on NAICS) – Seasonally adjusted",
        ),
        ("Table 3", "Labour force characteristics by province – Seasonally adjusted"),
    ]
    assert article.release_tables[2].url == f"{_DAY}/t003a-eng.htm"


async def test_french_article_text(httpx_mock):
    httpx_mock.add_response(url=_ARTICLE_FR, text=_fixture("dq180209a_fra.htm"))
    article = await client.get_article("dq180209a", lang="fr")
    assert "(-137 000)" in article.sections[0].text
    assert "5,9 %" in article.sections[0].text
    assert article.release_tables[0].number == "Tableau 1"
    assert article.release_tables[2].url == f"{_DAY}/t003a-fra.htm"


async def test_alberta_january_2018_as_first_published(httpx_mock):
    httpx_mock.add_response(url=_ARTICLE_EN, text=_fixture("dq180209a_eng.htm"))
    httpx_mock.add_response(url=f"{_DAY}/t003a-eng.htm", text=_fixture("t003a_180209_eng.htm"))
    result = await client.get_release_tables("dq180209a", tables=[3], search="Alberta")

    assert result.release_date == date(2018, 2, 9)
    assert len(result.available_tables) == 3
    table = result.tables[0]
    assert table.number == "Table 3"
    assert table.title == "Labour force characteristics by province – Seasonally adjusted"
    assert table.csv_url == f"{_DAY}/t003a-eng.csv"
    assert table.units == [
        "thousands (except rates)",
        "change in thousands (except rates)",
        "% change",
    ]
    assert "Standard error" in table.columns
    assert "... not applicable" in table.notes
    assert any(note.startswith("Table note 1: Average standard error") for note in table.notes)
    assert "Source(s): CANSIM table 282-0087." in table.notes

    rows = {(r.row, r.column, r.unit): r for r in table.rows}
    change = rows[
        ("Employment", "December 2017 to January 2018", "change in thousands (except rates)")
    ]
    assert change.group == "Alberta"
    assert change.parents == ["Population", "Labour force"]
    assert change.value_text == "-5.9"
    assert change.value == -5.9
    rate = rows[("Unemployment rate", "January 2018", "thousands (except rates)")]
    assert rate.value == 7.0
    assert rate.parents == []
    # The column's footnote marker is a reference, not part of the heading.
    error = rows[("Employment", "Standard error", "thousands (except rates)")]
    assert error.note_refs == ["1"]
    # Symbols are kept as published, with no number.
    na = rows[("Unemployment rate", "January 2017 to January 2018", "% change")]
    assert na.value_text == "..." and na.value is None
    assert all(r.group == "Alberta" for r in table.rows)
    assert result.provenance.url == f"{_DAY}/t003a-eng.htm"
    assert result.truncated is False and result.note is None


async def test_french_table_reads_spaces_and_decimal_commas(httpx_mock):
    httpx_mock.add_response(url=_ARTICLE_FR, text=_fixture("dq180209a_fra.htm"))
    httpx_mock.add_response(url=f"{_DAY}/t003a-fra.htm", text=_fixture("t003a_180209_fra.htm"))
    result = await client.get_release_tables(
        "dq180209a", lang="fr", tables=[3], search="alberta emploi"
    )
    table = result.tables[0]
    assert table.number == "Tableau 3"
    rows = {(r.row, r.column, r.unit): r for r in table.rows}
    level = rows[("Emploi", "Janvier 2018", "milliers (sauf les taux)")]
    assert level.value_text == "2 314,5" and level.value == 2314.5
    change = next(r for r in table.rows if r.row == "Emploi" and r.value_text == "-5,9")
    assert change.value == -5.9
    # "emploi" starts a word: "Taux de chômage" and "Emploi" rows, not "chômage" alone.
    assert {r.row for r in table.rows} == {"Emploi", "Temps partiel"}
    assert any(note.startswith("Note de tableau 1 : ") for note in table.notes)


async def test_limit_truncates_across_tables_with_a_note(httpx_mock):
    httpx_mock.add_response(url=_ARTICLE_EN, text=_fixture("dq180209a_eng.htm"))
    httpx_mock.add_response(url=f"{_DAY}/t003a-eng.htm", text=_fixture("t003a_180209_eng.htm"))
    result = await client.get_release_tables("dq180209a", tables=[3], limit=10)
    assert result.returned_count == 10
    assert result.total_rows > 10
    assert result.truncated is True
    assert result.note is not None and "limit=10" in result.note


async def test_unknown_table_number_lists_the_tables(httpx_mock):
    httpx_mock.add_response(url=_ARTICLE_EN, text=_fixture("dq180209a_eng.htm"))
    with pytest.raises(NotFound, match="Table 1, Table 2, Table 3"):
        await client.get_release_tables("dq180209a", tables=[9])


async def test_limit_out_of_range_is_invalid():
    with pytest.raises(InvalidInput):
        await client.get_release_tables("dq180209a", limit=0)


async def test_release_without_tables_says_so(httpx_mock):
    page = _fixture("dq180209a_eng.htm")
    page = page[: page.index('<div class="tablebtn')] + "</section></main></body></html>"
    httpx_mock.add_response(url=_ARTICLE_EN, text=page)
    result = await client.get_release_tables("dq180209a")
    assert result.tables == [] and result.available_tables == []
    assert result.note is not None and "no tables" in result.note


def test_pre_2014_links_and_2012_table_layout():
    # 2012-2013 articles name their tables tYYMMDDx00N-eng.htm (dq131206a, dq121221b).
    article = BeautifulSoup(
        '<div class="tablebtn"><a href="t121221b001-eng.htm"><span class="sd-tablet">Table 1'
        "<br/>Consumer Price Index and major components, Canada</span></a></div>"
        '<a href="t121221b001-eng.htm">Table 1</a><a href="cg-a001-eng.htm">Chart 1</a>',
        "html.parser",
    )
    url = "https://www150.statcan.gc.ca/n1/daily-quotidien/121221/dq121221b-eng.htm"
    links = client._release_table_links(article, url)
    assert links == [
        {
            "number": "Table 1",
            "title": "Consumer Price Index and major components, Canada",
            "url": "https://www150.statcan.gc.ca/n1/daily-quotidien/121221/t121221b001-eng.htm",
        }
    ]

    # 2012 table pages have no <main>, data cells in <th class="data">, merged unit
    # cells and numbered notes under the table.
    parsed = client._parse_release_table(_fixture("t121221b001_eng.htm"), links[0]["url"], "en")
    assert parsed["number"] == "Table 1"
    assert parsed["title"].startswith("Consumer Price Index and major components")
    rows = {(r["row"], r["column"]): r for r in parsed["rows"]}
    weight = rows[("All-items Consumer Price Index (CPI)", "Relative importance")]
    assert weight["value"] == 100.0 and weight["unit"] == "%"
    # The note marker on the column and the one on the cell both count.
    assert weight["note_refs"] == ["1", "2"]
    index = rows[("All-items Consumer Price Index (CPI)", "November 2012")]
    assert index["value"] == 121.9 and index["unit"] == "(2002=100)"
    change = rows[("All-items Consumer Price Index (CPI)", "October to November 2012")]
    assert change["value"] == -0.2 and change["unit"] == "% change"
    assert parsed["notes"][0].startswith("1. 2009 CPI basket weights")


@pytest.mark.parametrize(
    ("text", "lang", "expected"),
    [
        ("-5.9", "en", -5.9),
        ("3,447.3", "en", 3447.3),
        ("+1.5", "en", 1.5),
        ("12.3E", "en", 12.3),
        ("...", "en", None),
        ("x", "en", None),
        ("2 314,5", "fr", 2314.5),
        ("-5,9", "fr", -5.9),
        ("100,00", "fr", 100.0),
        ("1,234", "fr", 1.234),  # in French the comma is the decimal mark
        ("1 234.5", "fr", None),
    ],
)
def test_number(text, lang, expected):
    assert client._number(text, lang) == expected
