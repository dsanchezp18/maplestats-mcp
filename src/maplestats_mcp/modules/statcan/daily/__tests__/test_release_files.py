"""The two-week release list, the annual-PDF pointer, and a release's tables and files.

Fixtures are trimmed from the live pages of 2026-11-04: the same elements, classes
and link forms, fewer items.
"""

from __future__ import annotations

from datetime import date

import pytest

from maplestats_mcp.modules.statcan.daily import client
from maplestats_mcp.modules.statcan.wds import constants as wds_constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError

_UPCOMING_URL = "https://www150.statcan.gc.ca/n1/dai-quo/cal2-eng.htm"
_MAJOR_URL = "https://www150.statcan.gc.ca/n1/dai-quo/cal1-eng.htm"

_UPCOMING = """<html><body><main>
<h1>Release schedule</h1>
<p><a href="/dai-quo/upcoming-a_venir-eng.pdf">PDF version (90 kb)</a></p>
<div class="upcoming"><div class="master">
<h2>November 2 <span class="hd3">to</span> 13, 2026</h2>
<div class="calendar">
<h3 class="hd1">November&nbsp;2</h3><hr>
<ol class="upcominglist">
<li><div class="releaseblock"><div class="lockup"></div><div class="releaseinfo">
<div class="rtitle">Machinery and Equipment Price Index, <span class="refper">August 2026</span></div>
<p class="contact">(Alice Xu, <span class="phone">613-614-3563</span>)</p></div></div></li>
<li><div class="releaseblock"><div class="lockup"></div><div class="releaseinfo">
<div class="rtitle">Census of Environment: Harvesting benefits from nature</div>
<p class="contact">(Jessica Andrews, <span class="phone">343-552-0894</span>)</p></div></div></li>
</ol>
<h3 class="hd1">November&nbsp;6</h3><hr>
<ol class="upcominglist">
<li><div class="releaseblock"><div class="lockup">(lockup)</div><div class="releaseinfo">
<div class="rtitle">Labour Force Survey, <span class="refper">October 2026</span></div>
<p class="contact">(Andrew Fields, <span class="phone">613-290-1655</span>)</p></div></div></li>
</ol>
</div></div></div></main></body></html>"""

_MAJOR = """<html><body><main>
<p>Annual release dates available in PDF format:</p>
<ul><li><a href="/release-diffusion/2026-eng.pdf">2026-2027 release dates (159 kb)</a></li></ul>
<select class="select_keylist" id="select_keylist">
<option value="3592">Building permits</option>
<option value="3587">Labour Force Survey</option>
</select></main></body></html>"""

_NEW_YEAR = """<html><body><div class="upcoming"><h2>December 29 to January 9, 2027</h2>
<div class="calendar">
<h3>December 30</h3><ol><li><div class="rtitle">Building permits,
<span class="refper">October 2026</span></div></li></ol>
<h3>January 8</h3><ol><li><div class="lockup">(lockup)</div><div class="rtitle">Labour Force
Survey, <span class="refper">December 2026</span></div></li></ol>
</div></div></body></html>"""

_FRENCH = """<html><body><div class="upcoming"><h2>Du 2 au 13 novembre 2026</h2>
<div class="calendar"><h3 class="hd1">6&nbsp;novembre</h3><ol class="upcominglist">
<li><div class="releaseblock"><div class="lockup">(huis clos)</div><div class="releaseinfo">
<div class="rtitle">Enquête sur la population active, <span class="refper">octobre 2026</span></div>
<p class="contact">(Andrew Fields, <span class="phone"><span class="phone">613-290-1655</span></span>)</p>
</div></div></li></ol></div></div></body></html>"""

_DAY = "https://www150.statcan.gc.ca/n1/daily-quotidien"
_ARTICLE = f"{_DAY}/261030/dq261030a-eng.htm"
_TABLES = f"{_DAY}/261030/dq261030a-cansim-eng.htm"
_INFO = f"{_DAY}/261030/dq261030a-info-eng.htm"
_PREVIOUS = f"{_DAY}/260929/dq260929a-eng.htm"

_NAV = """<div class="release_nav">
<a href="dq{id}-eng.htm">Text</a>
<a href="dq{id}-cansim-eng.htm">Tables</a>
<a href="dq{id}-info-eng.htm">Related information</a>
<a href="/dai-quo/cal1-eng.htm?sk=3569">Release schedule</a>
<a href="/daily-quotidien/{prev_day}/dq{prev_id}-eng.htm">Previous release</a>
<a href="dq{id}-eng.pdf">PDF (248 KB)</a>
</div>"""


def _page(title: str, nav: str, body: str = "") -> str:
    return f"<html><body><main><h1>{title}</h1><section>{nav}{body}</section></main></body></html>"


_ARTICLE_PAGE = _page(
    "Gross domestic product by industry, August 2026",
    _NAV.format(id="261030a", prev_day="260929", prev_id="260929a"),
    '<p>See <a href="/t1/tbl1/en/tv.action?pid=3610043401">36-10-0434-01</a> and '
    '<a href="/en/catalogue/13-605-X202400100002">Revisions to Canada\'s GDP</a>.</p>'
    '<p>Catalogue number<a href="/en/catalogue/13-605-X">13-605-X</a></p>',
)

_TABLES_PAGE = _page(
    "Gross domestic product by industry, August 2026",
    _NAV.format(id="261030a", prev_day="260929", prev_id="260929a"),
    """<table id="release-list"><tbody>
<tr><td><a href="/t1/tbl1/en/tv.action?pid=3610043401"><h3 class="aKeyInd">Gross domestic
product (GDP) at basic prices, by industry, monthly <span class="frq">(monthly)</span></h3>
<p class="arrayid">(36-10-0434-01)</p></a></td></tr>
<tr><td><a href="/t1/tbl1/en/tv.action?pid=3610044901"><h3 class="aKeyInd">GDP, quarterly
average <span class="frq">(quarterly)</span></h3><p class="arrayid">(36-10-0449-01)</p></a></td></tr>
</tbody></table>""",
)

_INFO_PAGE = _page(
    "Gross domestic product by industry, August 2026",
    _NAV.format(id="261030a", prev_day="260929", prev_id="260929a"),
    """<h2>Definitions, data sources and methods</h2><ul><li>
<a href="http://www23.statcan.gc.ca/imdb/p2SV.pl?Function=getSurvey&amp;SDDS=1301">1301
&mdash; Gross Domestic Product by Industry - National (Monthly)</a></li></ul>
<h2>Related subjects</h2><ul><li>
<a href="/dai-quo/ssi/homepage/rel-com/theme36-eng.htm">Economic accounts</a></li></ul>""",
)

# The previous release links no previous release of its own here: the chain ends.
_PREVIOUS_PAGE = _page(
    "Gross domestic product by industry, July 2026",
    '<div class="release_nav"><a href="dq260929a-eng.pdf">PDF (240 KB)</a></div>',
    '<p><a href="/t1/tbl1/en/tv.action?pid=3610043401">36-10-0434-01</a></p>',
)

# 2012 layout: no <main>, no tabs (they answer 404), old CANSIM numbers in the text.
_OLD_URL = f"{_DAY}/120601/dq120601a-eng.htm"
_OLD_PAGE = """<html><body><div id="wb-main"><h1>Canadian economic accounts, first quarter
2012</h1>
<a href="dq120601a-eng.pdf">PDF version</a>
<a href="/daily-quotidien/120302/dq120302a-eng.htm">Previous release</a>
<p>Available in <a href="/n1/en/cansim/379-0027">CANSIM table 379-0027</a> and
<a href="/n1/en/type/data?cansim=380-0001,380-0002">CANSIM table 380-0001 to 380-0002</a>,
survey number <a href="http://www.statcan.gc.ca/imdb-bmdi/1301-eng.htm">1301</a>.</p>
<p><a href="/n1/en/catalogue/13-010-X">Catalogue number 13-010-X</a></p>
</div></body></html>"""

_CUBES_URL = f"{wds_constants.BASE_URL}getAllCubesListLite"


def _cube(pid: int, cansim: str) -> dict[str, object]:
    return {
        "productId": pid,
        "cansimId": cansim,
        "cubeTitleEn": "t",
        "cubeTitleFr": "t",
        "cubeStartDate": "2000-01-01",
        "cubeEndDate": "2012-01-01",
        "releaseTime": "2012-06-01T08:30",
        "archived": "2",
        "frequencyCode": 9,
        "subjectCode": ["36"],
        "surveyCode": ["1301"],
    }


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


async def test_upcoming_dates_lockup_contact_and_annual_pdf(httpx_mock):
    httpx_mock.add_response(url=_UPCOMING_URL, text=_UPCOMING)
    httpx_mock.add_response(url=_MAJOR_URL, text=_MAJOR)
    result = await client.get_upcoming_releases()
    assert result.period == "November 2 to 13, 2026"
    assert (result.start_date, result.end_date) == (date(2026, 11, 2), date(2026, 11, 6))
    assert result.total_in_window == result.returned_count == 3
    first, study, lfs = result.releases
    assert (first.title, first.reference_period) == (
        "Machinery and Equipment Price Index",
        "August 2026",
    )
    assert (first.contact, first.phone, first.lockup) == ("Alice Xu", "613-614-3563", False)
    assert study.reference_period is None
    assert lfs.lockup and lfs.release_date == date(2026, 11, 6)
    assert result.pdf_url == "https://www150.statcan.gc.ca/n1/dai-quo/upcoming-a_venir-eng.pdf"
    assert result.annual_schedule_pdf_url == (
        "https://www150.statcan.gc.ca/n1/release-diffusion/2026-eng.pdf"
    )
    assert result.annual_schedule_label == "2026-2027 release dates"
    assert result.major_indicators == ["Building permits", "Labour Force Survey"]


async def test_upcoming_query_filters_but_counts_the_window(httpx_mock):
    httpx_mock.add_response(url=_UPCOMING_URL, text=_UPCOMING)
    httpx_mock.add_response(url=_MAJOR_URL, text=_MAJOR)
    result = await client.get_upcoming_releases("labour october")
    assert [r.title for r in result.releases] == ["Labour Force Survey"]
    assert result.total_in_window == 3


async def test_upcoming_window_over_new_year(httpx_mock):
    httpx_mock.add_response(url=_UPCOMING_URL, text=_NEW_YEAR)
    httpx_mock.add_response(url=_MAJOR_URL, status_code=404)
    result = await client.get_upcoming_releases()
    assert [r.release_date for r in result.releases] == [date(2026, 12, 30), date(2027, 1, 8)]
    assert result.annual_schedule_pdf_url is None


async def test_upcoming_in_french(httpx_mock):
    httpx_mock.add_response(url=_UPCOMING_URL.replace("eng", "fra"), text=_FRENCH)
    # Retried by shared/http.py, then left out: the two-week list still comes back.
    httpx_mock.add_response(url=_MAJOR_URL.replace("eng", "fra"), status_code=500, is_reusable=True)
    result = await client.get_upcoming_releases("enquete", lang="fr")
    assert result.annual_schedule_pdf_url is None
    (lfs,) = result.releases
    assert lfs.release_date == date(2026, 11, 6) and lfs.lockup
    assert lfs.reference_period == "octobre 2026" and lfs.phone == "613-290-1655"


async def test_upcoming_without_the_list_is_an_upstream_error(httpx_mock):
    httpx_mock.add_response(url=_UPCOMING_URL, text="<html><main>Maintenance</main></html>")
    with pytest.raises(UpstreamError):
        await client.get_upcoming_releases()


async def test_release_files_reads_tabs_and_walks_previous(httpx_mock):
    httpx_mock.add_response(url=_ARTICLE, text=_ARTICLE_PAGE)
    httpx_mock.add_response(url=_TABLES, text=_TABLES_PAGE)
    httpx_mock.add_response(url=_INFO, text=_INFO_PAGE)
    httpx_mock.add_response(url=_PREVIOUS, text=_PREVIOUS_PAGE)
    result = await client.get_release_files("dq261030a", previous=3)
    assert result.returned_count == 2 and result.chain_ended
    latest, older = result.releases
    assert latest.release_date == date(2026, 10, 30)
    assert latest.pdf_url == f"{_DAY}/261030/dq261030a-eng.pdf"
    assert latest.previous_release_url == _PREVIOUS
    assert latest.release_schedule_url == (
        "https://www150.statcan.gc.ca/n1/dai-quo/cal1-eng.htm?sk=3569"
    )
    assert [(t.table_id, t.product_id, t.frequency) for t in latest.tables] == [
        ("36-10-0434-01", 36100434, "monthly"),
        ("36-10-0449-01", 36100449, "quarterly"),
    ]
    assert latest.tables[1].title == "GDP, quarterly average"
    (survey,) = latest.surveys
    assert survey.sdds == 1301
    assert survey.name == "Gross Domestic Product by Industry - National (Monthly)"
    assert latest.subjects == ["Economic accounts"]
    assert {p.catalogue_number: p.title for p in latest.products} == {
        "13-605-X": "Revisions to Canada's GDP"
    }
    # No tabs on the older page: tables come from the links in its text.
    assert [t.product_id for t in older.tables] == [36100434]
    assert older.pdf_url == f"{_DAY}/260929/dq260929a-eng.pdf"


async def test_release_files_old_layout_maps_cansim_numbers(httpx_mock):
    httpx_mock.add_response(url=_OLD_URL, text=_OLD_PAGE)
    httpx_mock.add_response(
        url=_CUBES_URL, json=[_cube(36100398, "379-0027"), _cube(36100239, "380-0001")]
    )
    result = await client.get_release_files(_OLD_URL)
    (release,) = result.releases
    assert release.title.startswith("Canadian economic accounts")
    assert release.pdf_url == f"{_DAY}/120601/dq120601a-eng.pdf"
    assert not result.chain_ended  # previous asked as 0, but a previous release exists
    assert [(t.legacy_cansim_id, t.product_id, t.table_id) for t in release.tables] == [
        ("379-0027", 36100398, "36-10-0398-01"),
        ("380-0001", 36100239, "36-10-0239-01"),
        ("380-0002", None, None),
    ]
    (survey,) = release.surveys
    assert survey.sdds == 1301 and survey.name is None
    assert [(p.catalogue_number, p.title) for p in release.products] == [("13-010-X", None)]


async def test_release_files_rejects_bad_previous():
    with pytest.raises(InvalidInput):
        await client.get_release_files("dq261030a", previous=13)
    with pytest.raises(InvalidInput):
        await client.get_release_files("not an article")
