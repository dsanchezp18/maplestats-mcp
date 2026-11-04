from __future__ import annotations

from datetime import date

import pytest

from maplestats_mcp.modules.statcan.daily import client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_URL = "https://www150.statcan.gc.ca/n1/daily-quotidien/261104/dq261104a-eng.htm"

# Trimmed from the live page of 2026-11-04 (read from the Azure server): the same
# elements, classes and link forms, fewer paragraphs.
_PAGE = """<!DOCTYPE html><html lang="en"><head>
<title>The Daily — Canadian international merchandise trade, September 2026</title>
<meta name="dcterms.issued" content="2026-11-04">
<meta name="dcterms.description" content="In September, Canada's merchandise exports edged up 0.2%.">
</head><body>
<main role="main" property="mainContentOfPage" class="container">
<div class="moduleHeading"><div class="DailyHeading">The Daily</div></div>
<h1 id="wb-cont">Canadian international merchandise trade, September 2026</h1>
<section>
<div class="release_nav">
<a class="btn" href="dq261104a-eng.htm">Text - Selected</a>
<a class="btn" href="dq261104a-cansim-eng.htm">Tables</a>
<a class="btn" href="dq261104a-info-eng.htm">Related information</a>
<a class="btn" href="/dai-quo/cal1-eng.htm?sk=3612">Release schedule</a>
<a class="btn" href="/daily-quotidien/261006/dq261006a-eng.htm">Previous release</a>
<a class="btn" href="dq261104a-eng.pdf">PDF (318 KB)</a>
</div>
<p class="sd-release-date">Released:&nbsp;2026-11-04</p>
<div class="panel panel-default sd-thumbnail"><div class="wb-tabs">
<a href="#panel1-0">Tab 1</a><p>Imports of goods $73.2 billion</p>
<a href="/t1/tbl1/en/tv.action?pid=1210001101">12-10-0011-01</a></div></div>
<p>In September, Canada's merchandise exports edged&nbsp;up 0.2%,
while imports decreased 0.3%.</p>
<div class="panel panel-default sd-thumbnail"><div class="panel-heading">
<h2 class="chartt">Chart&nbsp;1 Merchandise exports and imports</h2></div>
<div class="panel-body"><a href="cg-a001-eng.htm"><img alt=""></a></div></div>
<h2>Crude oil and gold are behind the increase</h2>
<p>Exports rose. See <a href="https://www150.statcan.gc.ca/n1/daily-quotidien/261022/dq261022a-eng.htm?indid=3556-1">higher prices</a>.</p>
<ul><li>Energy up 8.2%</li><li>Metals up 8.6%</li></ul>
<div class="tablebtn btn-group"><a class="btn" href="t001a-eng.htm">Table 1 Principal trading partners</a></div>
<div class="panel panel-Default sd-noteuser">
<div class="panel-heading sd-noteuser-heading"><h3 class="panel-title">Note to readers</h3></div>
<div class="panel-body sd-noteuser-body">
<p class="sd-first-para">Information on concepts and methods.</p>
<h3>Next release</h3>
<p>Data for October are scheduled for release on December 4.</p>
</div></div>
<h2>Contact information</h2>
<p>Contact <a href="mailto:infostats@statcan.gc.ca">infostats@statcan.gc.ca</a>.</p>
</section>
<div class="pagedetails">Date modified: 2026-11-04</div>
</main></body></html>"""


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.mark.parametrize(
    ("given", "lang", "expected"),
    [
        ("dq261104a", "en", _URL),
        ("https://www.statcan.gc.ca/daily-quotidien/261104/dq261104a-eng.htm", "en", _URL),
        (_URL.replace("-eng", "-fra"), "en", _URL),
        ("dq261104a", "fr", _URL.replace("-eng", "-fra")),
        ("DQ261104B", "en", _URL.replace("dq261104a", "dq261104b")),
    ],
)
def test_article_url_accepts_ids_and_both_hosts(given, lang, expected):
    assert client._article_url(given, lang)[1] == expected


def test_article_url_rejects_other_text():
    with pytest.raises(InvalidInput):
        client._article_url("labour force survey", "en")


async def test_get_article_parses_sections_tables_and_pdf(httpx_mock):
    httpx_mock.add_response(url=_URL, text=_PAGE)
    article = await client.get_article("dq261104a")

    assert article.article_id == "dq261104a"
    assert article.title == "Canadian international merchandise trade, September 2026"
    assert article.release_date == date(2026, 11, 4)
    assert article.summary == "In September, Canada's merchandise exports edged up 0.2%."
    assert article.pdf_url == _URL.replace(".htm", ".pdf")
    assert article.tables_page_url == _URL.replace("a-eng", "a-cansim-eng")
    assert article.related_info_url == _URL.replace("a-eng", "a-info-eng")
    assert article.previous_release_url is not None
    assert "dq261006a" in article.previous_release_url

    headings = [section.heading for section in article.sections]
    assert headings == [
        None,
        "Crude oil and gold are behind the increase",
        "Note to readers",
        "Note to readers: Next release",
        "Contact information",
    ]
    # The release date, the key-figure tabs and chart panels are not body text.
    first = article.sections[0].text
    assert (
        first
        == "In September, Canada's merchandise exports edged up 0.2%, while imports decreased 0.3%."
    )
    assert "- Energy up 8.2%\n- Metals up 8.6%" in article.sections[1].text
    assert "December 4" in article.sections[3].text

    assert article.charts == ["Chart 1 Merchandise exports and imports"]
    assert [(t.table_id, t.product_id) for t in article.tables] == [("12-10-0011-01", 12100011)]

    urls = {link.url: link.text for link in article.links}
    assert urls["https://www150.statcan.gc.ca/n1/daily-quotidien/261104/t001a-eng.htm"].startswith(
        "Table 1"
    )
    assert "higher prices" in urls.values()
    # Nav buttons, chart thumbnails, anchors and e-mail addresses are left out.
    assert not any(
        "cal1" in url or "cg-a001" in url or url.startswith("mailto") or url.endswith(".pdf")
        for url in urls
    )
    assert article.word_count > 20
    assert article.provenance.url == _URL
    assert article.archived is False
    # Root-relative links answer 301 to the same path under /n1/; given in that form.
    assert article.previous_release_url == (
        "https://www150.statcan.gc.ca/n1/daily-quotidien/261006/dq261006a-eng.htm"
    )


async def test_archived_article_skips_the_archive_notice(httpx_mock):
    # Older articles (checked 2013, 2017, 2021, 2024) put an "Archived Content" notice
    # in its own <section> between the <h1> and the article's section.
    archived = _PAGE.replace(
        '<section>\n<div class="release_nav">',
        '<p>View the <a href="dq261204a-eng.htm">most recent version</a>.</p>\n'
        '<section id="archived" class="alert alert-warning"><h2>Archived Content</h2>'
        "<p>Information identified as archived is provided for reference.</p></section>\n"
        '<section id="archived-bnr"><header>Archived</header><p>This page has been archived.</p>'
        '</section>\n<section>\n<div class="release_nav">',
    )
    httpx_mock.add_response(url=_URL, text=archived)
    article = await client.get_article("dq261104a")
    assert article.archived is True
    assert article.sections[0].text.startswith("In September")
    assert all("Archived" not in (section.heading or "") for section in article.sections)
    assert article.pdf_url is not None


async def test_get_article_404_is_not_found(httpx_mock):
    httpx_mock.add_response(url=_URL, status_code=404)
    with pytest.raises(NotFound, match="dq261104a"):
        await client.get_article("dq261104a")


async def test_get_article_without_article_layout_is_an_upstream_error(httpx_mock):
    httpx_mock.add_response(url=_URL, text="<html><main><p>Maintenance</p></main></html>")
    with pytest.raises(UpstreamError, match="layout"):
        await client.get_article("dq261104a")


async def test_get_article_is_cached(httpx_mock):
    httpx_mock.add_response(url=_URL, text=_PAGE)
    first = await client.get_article("dq261104a")
    second = await client.get_article(
        "https://www.statcan.gc.ca/daily-quotidien/261104/dq261104a-eng.htm"
    )
    assert not first.provenance.cached
    assert second.provenance.cached
