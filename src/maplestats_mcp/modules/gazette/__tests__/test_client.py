"""Tests for modules/gazette/client.py, shaped on live 2026-09-23 pages."""

from __future__ import annotations

from datetime import date

import pytest

from maplestats_mcp.modules.gazette import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_FEED = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><title>Canada Gazette - Part I, September 12, 2026</title>
<link>https://gazette.gc.ca/rp-pr/p1/2026/2026-09-12/html/index-eng.html</link></item>
<item><title>Canada Gazette - Part I, September 19, 2026</title>
<link>https://gazette.gc.ca/rp-pr/p1/2026/2026-09-19/html/index-eng.html</link></item>
</channel></rss>"""
_ISSUE_URL = "https://gazette.gc.ca/rp-pr/p1/2026/2026-09-19/html/index-eng.html"
_ISSUE = """<main>
<h2>Commissions</h2><a href="./commis-eng.html">Commissions</a>
<h3>Canadian International Trade Tribunal</h3><h4>Appeals</h4>
<a href="./commis-eng.html#cs1">Notice No. HA-2026-015</a>
<h2>Government notices</h2><a href="./notice-avis-eng.html">Government notices</a>
<h3>Privy Council Office</h3>
<a href="./notice-avis-eng.html#ne3">Appointment opportunities</a>
<a href="#fn1">footnote *</a>
</main>"""
_SECTION_PAGE = """<main>
<h2 id="ne2">MAJOR PROJECTS OFFICE</h2><p>Deep geological repository.</p>
<h2 id="ne3">PRIVY COUNCIL OFFICE</h2><h4>Appointment opportunities</h4>
<p>The Government of Canada is committed to appointing qualified people.</p>
<ul><li>Chairperson</li></ul>
<h2 id="ne4">NEXT</h2><p>Not part of the notice.</p>
</main>"""


async def test_list_issues_sorts_newest_first(httpx_mock):
    httpx_mock.add_response(url=constants.FEED_URL.format(part=1, lang="eng"), content=_FEED)
    result = await client.list_issues(1, limit=1)
    assert [i.date for i in result.issues] == [date(2026, 9, 19)]


async def test_get_issue_groups_notices_and_skips_section_links(httpx_mock):
    httpx_mock.add_response(url=_ISSUE_URL, text=_ISSUE)
    issue = await client.get_issue(1, "2026-09-19")
    assert [(n.section, n.organization, n.act, n.title) for n in issue.notices] == [
        (
            "Commissions",
            "Canadian International Trade Tribunal",
            "Appeals",
            "Notice No. HA-2026-015",
        ),
        ("Government notices", "Privy Council Office", None, "Appointment opportunities"),
    ]
    assert issue.notices[1].url.endswith("/2026-09-19/html/notice-avis-eng.html#ne3")


async def test_get_notice_stops_at_next_anchor(httpx_mock):
    page = "https://gazette.gc.ca/rp-pr/p1/2026/2026-09-19/html/notice-avis-eng.html"
    httpx_mock.add_response(url=page, text=_SECTION_PAGE)
    notice = await client.get_notice(page + "#ne3")
    assert notice.title == "PRIVY COUNCIL OFFICE"
    assert notice.text.splitlines() == [
        "Appointment opportunities",
        "The Government of Canada is committed to appointing qualified people.",
        "Chairperson",
    ]


async def test_validation(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.list_issues(3)
    with pytest.raises(InvalidInput):
        await client.get_issue(1, "September 19")
    with pytest.raises(InvalidInput):
        await client.get_notice("https://example.com/notice.html")
    page = "https://gazette.gc.ca/rp-pr/p1/2026/2026-09-19/html/notice-avis-eng.html"
    httpx_mock.add_response(url=page, text=_SECTION_PAGE)
    with pytest.raises(NotFound):
        await client.get_notice(page + "#ne99")


# The Part II feed as served 2026-10-03: the Consolidated Index comes first,
# with a pubDate that is not a publication day and no html/index page.
_FEED_P2 = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<link>https://gazette.gc.ca/rss/p2-eng.xml</link>
<item><title>Canada Gazette - Consolidated Index of Statutory Instruments
(January 1, 1955 to June 30, 2026)</title>
<link>https://gazette.gc.ca/rp-pr/p2/2026/2026-06-30-c2/index-eng.html</link>
<pubDate>Tue, 29 Sep 2026 12:00:00 -0400</pubDate></item>
<item><title>Canada Gazette - Part II, September 23, 2026</title>
<link>https://gazette.gc.ca/rp-pr/p2/2026/2026-09-23/html/index-eng.html</link>
<pubDate>Wed, 23 Sep 2026 12:00:00 -0400</pubDate></item>
</channel></rss>"""

# The Canada.ca not-found template, served with HTTP 200 (live 2026-10-03).
_SOFT_404_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Nous ne pouvons trouver cette page Web (Erreur 404) - Thème Canada.ca /
We couldn't find that Web page (Error 404) - Canada.ca theme</title></head>
<body><main><h1>Nous ne pouvons trouver cette page Web (Erreur 404)</h1>
<ul><li><a href="https://www.canada.ca/fr.html">page d'accueil</a></li></ul>
<h1>We couldn't find that Web page (Error 404)</h1>
<ul><li><a href="https://www.canada.ca/en.html">home page</a></li></ul></main></body></html>"""


async def test_feed_skips_items_that_are_not_issues(httpx_mock):
    httpx_mock.add_response(url=constants.FEED_URL.format(part=2, lang="eng"), content=_FEED_P2)
    result = await client.list_issues(2)
    assert [i.date for i in result.issues] == [date(2026, 9, 23)]


async def test_get_issue_default_opens_latest_real_issue(httpx_mock):
    httpx_mock.add_response(url=constants.FEED_URL.format(part=2, lang="eng"), content=_FEED_P2)
    url = "https://gazette.gc.ca/rp-pr/p2/2026/2026-09-23/html/index-eng.html"
    httpx_mock.add_response(url=url, text=_ISSUE)
    issue = await client.get_issue(2)
    assert issue.date == date(2026, 9, 23)
    assert issue.notices


async def test_soft_404_page_is_not_found(httpx_mock):
    missing = "https://gazette.gc.ca/rp-pr/p1/2026/2026-09-24/html/index-eng.html"
    httpx_mock.add_response(url=missing, text=_SOFT_404_PAGE)
    with pytest.raises(NotFound):
        await client.get_issue(1, "2026-09-24")
    page = "https://gazette.gc.ca/rp-pr/p1/2026/2026-10-03/html/zzz-eng.html"
    httpx_mock.add_response(url=page, text=_SOFT_404_PAGE)
    with pytest.raises(NotFound):
        await client.get_notice(page)
