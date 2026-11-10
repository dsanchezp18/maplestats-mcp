from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.daily import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


# Shapes confirmed live 2026-10-02: indicator rows carry an artificial
# time-of-day in "date" and an empty "url" until published; product rows add
# "release_date" and "pid" and the file has no future dates.
_INDICATORS = [
    {
        "date": "2012-03-16 00:00:01",
        "type": "meeting",
        "title": "Monthly Survey of Manufacturing",
        "description": "January 2012",
        "url": "/daily-quotidien/120316/dq120316a-eng.htm",
    },
    {
        "date": "2099-01-09 00:00:02",
        "type": "meeting",
        "title": "Labour Force Survey",
        "description": "December 2098",
        "url": "",
    },
    {
        "date": "2099-01-09 00:00:01",
        "type": "meeting",
        "title": "Enquête sur la population active",
        "description": "December 2098",
        "url": "",
    },
    {
        "date": "2098-12-04 00:00:01",
        "type": "meeting",
        "title": "Canadian international merchandise trade",
        "description": "October 2098",
        "url": "",
    },
]
_PRODUCTS = [
    {
        "date": "2012-04-02 00:00:00",
        "release_date": "2012-04-02",
        "pid": "45-004-X2012001",
        "type": "meeting",
        "title": "The Supply and Disposition of Refined Petroleum Products in Canada",
        "description": "Catalogue number 45-004-X2012001 (HTML | PDF)",
        "url": "/en/catalogue/45-004-X",
    }
]
_INDICATORS_URL = constants.KEY_INDICATORS_URL.format(suffix="eng")
_PRODUCTS_URL = constants.PRODUCTS_URL.format(suffix="eng")
_ARCHIVE_URL = constants.FULL_ARCHIVE_URL.format(suffix="eng")
_UPCOMING_URL = constants.UPCOMING_URL.format(suffix="eng")


def _ptea(date: str, period: str, url: str = "/daily-quotidien/x/dq.htm") -> dict[str, str]:
    return {
        "date": f"{date} 00:00:01",
        "type": "meeting",
        "title": "Provincial and territorial economic accounts",
        "description": period,
        "url": url,
    }


async def test_calendar_upcoming_is_soonest_first_and_has_no_url(httpx_mock):
    httpx_mock.add_response(url=_INDICATORS_URL, json=_INDICATORS)
    result = await client.get_release_calendar()
    assert result.entries[0].title == "Canadian international merchandise trade"
    assert result.total_matched == 3
    assert all(e.scheduled and e.url is None for e in result.entries)
    assert str(result.latest_scheduled_date) == "2099-01-09"


async def test_calendar_query_ignores_accents_and_needs_every_word(httpx_mock):
    httpx_mock.add_response(url=_INDICATORS_URL, json=_INDICATORS)
    result = await client.get_release_calendar("enquete population")
    assert [e.title for e in result.entries] == ["Enquête sur la population active"]
    # Nothing scheduled: the archive is read for the release's history, and has none.
    httpx_mock.add_response(url=_ARCHIVE_URL, json=[])
    none = await client.get_release_calendar("labour trade")
    assert none.total_matched == 0 and none.not_scheduled is None


async def test_calendar_history_is_newest_first_with_full_url(httpx_mock):
    httpx_mock.add_response(url=_INDICATORS_URL, json=_INDICATORS)
    httpx_mock.add_response(url=_ARCHIVE_URL, json=[])
    result = await client.get_release_calendar(
        "manufacturing", upcoming_only=False, end_date="2012-12-31"
    )
    entry = result.entries[0]
    assert not entry.scheduled
    assert entry.release_date.year == 2012
    assert entry.url == "https://www150.statcan.gc.ca/daily-quotidien/120316/dq120316a-eng.htm"


async def test_calendar_products_have_no_future_rows(httpx_mock):
    httpx_mock.add_response(url=_PRODUCTS_URL, json=_PRODUCTS)
    upcoming = await client.get_release_calendar(kind="products")
    assert upcoming.total_matched == 0
    httpx_mock.add_response(url=_ARCHIVE_URL, json=[])
    history = await client.get_release_calendar("45-004-X", kind="products", upcoming_only=False)
    assert history.entries[0].catalogue_number == "45-004-X2012001"
    assert history.entries[0].reference_period is None


async def test_calendar_and_releases_errors_in_french():
    with pytest.raises(InvalidInput, match="kind doit être l'une des valeurs"):
        await client.get_release_calendar(kind="nope", lang="fr")
    with pytest.raises(InvalidInput, match="subject doit être l'une des valeurs"):
        await client.get_releases("not_a_real_subject", lang="fr")
    with pytest.raises(InvalidInput, match="date attendue au format AAAA-MM-JJ"):
        await client.search_archive(start_date="soon", lang="fr")
    with pytest.raises(InvalidInput, match="kind must be one of"):
        await client.get_release_calendar(kind="nope")


async def test_calendar_rejects_bad_kind_and_date():
    with pytest.raises(InvalidInput):
        await client.get_release_calendar(kind="nope")
    with pytest.raises(InvalidInput):
        await client.get_release_calendar(start_date="soon")


# The release-history guide (added 2026-11-04): a query that matches nothing scheduled gets
# the same release's past dates, any already scheduled, and an estimate called one.
_PTEA_PAST = [
    _ptea("2023-11-08", "2022"),
    _ptea("2024-11-07", "2023"),
    _ptea("2025-11-06", "2024"),
    {**_ptea("2023-07-25", "2017 to 2020"), "title": "Digital supply and use tables"},
]


async def test_calendar_gives_history_and_a_labelled_estimate_for_the_year_asked(httpx_mock):
    # The 2098 accounts are on the calendar; the 2099 ones are asked for.
    scheduled = {**_ptea("2099-11-05", "2098"), "url": ""}
    httpx_mock.add_response(url=_INDICATORS_URL, json=[*_INDICATORS, scheduled])
    httpx_mock.add_response(url=_ARCHIVE_URL, json=_PTEA_PAST)
    httpx_mock.add_response(url=_UPCOMING_URL, status_code=404)
    result = await client.get_release_calendar(
        "next provincial and territorial economic accounts release 2099"
    )
    assert result.total_matched == 0
    history = result.not_scheduled
    assert history is not None
    assert history.title == "Provincial and territorial economic accounts"
    assert [str(e.release_date) for e in history.previous_releases] == [
        "2025-11-06",
        "2024-11-07",
        "2023-11-08",
    ]
    assert [e.reference_period for e in history.scheduled_releases] == ["2098"]
    assert history.typical_gap_days == 365  # gaps of 364 and 365 days (2024 is a leap year)
    assert str(history.estimated_next_date) == "2100-11-05"
    assert "not a scheduled date" in history.note and "2025-11-06 (2024)" in history.note


async def test_history_drops_an_estimate_already_in_the_past(httpx_mock):
    httpx_mock.add_response(url=_INDICATORS_URL, json=_INDICATORS)
    httpx_mock.add_response(
        url=_ARCHIVE_URL,
        json=[
            _ptea("2015-11-09", "2014"),
            _ptea("2016-11-14", "2015"),
            _ptea("2017-11-08", "2016"),
        ],
    )
    httpx_mock.add_response(url=_UPCOMING_URL, status_code=404)
    result = await client.get_release_calendar("provincial and territorial economic accounts")
    history = result.not_scheduled
    assert history is not None and history.estimated_next_date is None
    assert "estimate" not in history.note


async def test_question_words_do_not_hide_a_scheduled_release(httpx_mock):
    # "next ... release date" once matched nothing: no title contains "next".
    httpx_mock.add_response(url=_INDICATORS_URL, json=_INDICATORS)
    result = await client.get_release_calendar("next labour force survey release date")
    assert [e.title for e in result.entries] == ["Labour Force Survey"]
    assert result.not_scheduled is None


async def test_upcoming_gives_history_when_the_window_lacks_the_release(httpx_mock):
    html = (
        '<div class="upcoming"><h2>November 2 to 13, 2099</h2>'
        '<h3>November 5</h3><ol><li><div class="rtitle">Provincial and territorial '
        'economic accounts, <span class="refper">2098</span></div></li></ol></div>'
    )
    httpx_mock.add_response(url=_UPCOMING_URL, text=html, is_reusable=True)
    httpx_mock.add_response(url=constants.MAJOR_RELEASES_URL.format(suffix="eng"), status_code=404)
    httpx_mock.add_response(url=_ARCHIVE_URL, json=_PTEA_PAST)
    result = await client.get_upcoming_releases("provincial and territorial economic accounts 2099")
    assert result.returned_count == 0
    history = result.not_scheduled
    assert history is not None
    assert [str(e.release_date) for e in history.scheduled_releases] == ["2099-11-05"]
    assert str(history.estimated_next_date) == "2100-11-05"


# The archive as the Daily's previous-releases file has it (2026-11-10): the
# provisional poverty estimates are a Daily release, in neither schedule file.
_POVERTY = {
    "date": "2026-11-04 00:00:02",
    "type": "meeting",
    "title": "Provisional poverty estimates",
    "description": "2025",
    "url": "/daily-quotidien/261104/dq261104e-eng.htm",
}
_GDP_PROVINCES = {
    "date": "2026-05-01 00:00:01",
    "type": "meeting",
    "title": "Gross domestic product by industry: Provinces and territories",
    "description": "2025",
    "url": "/daily-quotidien/260501/dq260501a-eng.htm",
}


async def test_calendar_history_includes_every_daily_release(httpx_mock):
    httpx_mock.add_response(url=_INDICATORS_URL, json=_INDICATORS)
    httpx_mock.add_response(url=_ARCHIVE_URL, json=[_POVERTY, _GDP_PROVINCES])
    result = await client.get_release_calendar(
        "poverty", upcoming_only=False, start_date="2025-01-01", end_date="2027-12-31"
    )
    assert [(e.title, str(e.release_date), e.kind) for e in result.entries] == [
        ("Provisional poverty estimates", "2026-11-04", "daily_release")
    ]
    assert result.entries[0].reference_period == "2025"
    assert result.entries[0].url == (
        "https://www150.statcan.gc.ca/daily-quotidien/261104/dq261104e-eng.htm"
    )


async def test_calendar_history_does_not_repeat_a_schedule_row(httpx_mock):
    httpx_mock.add_response(url=_INDICATORS_URL, json=_INDICATORS)
    httpx_mock.add_response(url=_ARCHIVE_URL, json=[_INDICATORS[0]])
    result = await client.get_release_calendar("manufacturing", upcoming_only=False)
    assert [e.kind for e in result.entries] == ["key_indicator"]


@pytest.mark.parametrize(
    ("query", "title"),
    [
        # A phrase match missed both: the title has a colon, the year is the period.
        ("gross domestic product by industry provinces", _GDP_PROVINCES["title"]),
        ("provisional poverty estimates 2025", "Provisional poverty estimates"),
        ("When did StatCan publish the provisional poverty estimates?", _POVERTY["title"]),
        ("estimations provisoires", None),
    ],
)
async def test_archive_search_matches_every_word(httpx_mock, query, title):
    httpx_mock.add_response(url=_ARCHIVE_URL, json=[_POVERTY, _GDP_PROVINCES])
    result = await client.search_archive(query)
    assert [e.title for e in result.entries] == ([title] if title else [])
    assert result.note is None


async def test_archive_search_falls_back_to_most_words_and_says_so(httpx_mock):
    httpx_mock.add_response(url=_ARCHIVE_URL, json=[_POVERTY, _GDP_PROVINCES])
    result = await client.search_archive("GDP by industry provinces territories 2025")
    assert [e.title for e in result.entries] == [_GDP_PROVINCES["title"]]
    assert result.note is not None and "match 4 of 5" in result.note
