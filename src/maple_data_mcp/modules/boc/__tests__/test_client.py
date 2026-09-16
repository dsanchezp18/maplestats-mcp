"""Tests for the boc module's client.py, shaped around the real Valet
quirks confirmed live this session (see client.py's module docstring
and scripts/smoke_test_boc.py) rather than the happy path alone:
mutually exclusive observation-filter params, unmerged rows when
mixing series of different frequencies, the seriesDetail(s)/
groupDetail(s) singular/plural split, groupDetail's missing "name"
field, and 404/400 surfacing as typed errors instead of raw
httpx.HTTPStatusError.
"""

from __future__ import annotations

import httpx
import pytest

from maple_data_mcp.modules.boc import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable


@pytest.fixture(autouse=True)
def _reset_shared_cache():
    """shared/cache.py's TTLCache is a process-local singleton keyed only
    by (ttl, cache_key) - not per-test. Without clearing it, a prior
    test's successful fetch (e.g. list_series, cached for 24h) would
    silently serve its cached result to a later test reusing the same
    cache key instead of exercising that test's own httpx_mock
    registration, making the suite order-dependent.
    """
    cache_module._caches.clear()
    yield


async def test_list_series_parses_series_dict(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}lists/series/json",
        json={
            "terms": {"url": "https://www.bankofcanada.ca/terms/"},
            "series": {
                "FXUSDCAD": {
                    "label": "USD/CAD",
                    "description": "Daily average exchange rate",
                    "link": "https://www.bankofcanada.ca/valet/series/FXUSDCAD",
                }
            },
        },
    )
    result = await client.list_series()
    assert result.total_count == 1
    assert result.series[0].name == "FXUSDCAD"
    assert result.series[0].label == "USD/CAD"
    assert result.provenance.cached is False


async def test_search_series_filters_client_side(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}lists/series/json",
        json={
            "series": {
                "FXUSDCAD": {"label": "USD/CAD", "description": "US dollar exchange rate"},
                "V39079": {"label": "Target rate", "description": "Policy interest rate"},
            }
        },
    )
    result = await client.search_series("exchange", limit=10)
    assert result.total_count == 1
    assert result.series[0].name == "FXUSDCAD"


async def test_get_series_parses_plural_seriesdetails_key(httpx_mock):
    """Confirmed live: /series/{name}/json wraps its payload in
    "seriesDetails" (plural), with a "name" field - unlike the
    observations endpoint's "seriesDetail" (singular, no "name")."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}series/FXUSDCAD/json",
        json={
            "seriesDetails": {
                "name": "FXUSDCAD",
                "label": "USD/CAD",
                "description": "Daily average exchange rate",
            }
        },
    )
    result = await client.get_series("FXUSDCAD")
    assert result.name == "FXUSDCAD"
    assert result.label == "USD/CAD"


async def test_get_series_raises_not_found_on_404_with_real_message(httpx_mock):
    """Confirmed live: unknown series names return HTTP 404 with a JSON
    body {"message": "Series X not found.", "docs": "..."}."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}series/NOTAREAL/json",
        status_code=404,
        json={"message": "Series NOTAREAL not found.", "docs": "https://example.invalid"},
    )
    with pytest.raises(NotFound, match="NOTAREAL not found"):
        await client.get_series("NOTAREAL")


async def test_get_group_parses_group_series_without_description(httpx_mock):
    """Confirmed live: groupDetails.groupSeries entries have only
    label + link, no description - GroupMemberSeries is deliberately
    smaller than SeriesSummary for this reason."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}groups/FX_RATES_DAILY/json",
        json={
            "groupDetails": {
                "name": "FX_RATES_DAILY",
                "label": "Daily exchange rates",
                "description": "The daily average exchange rates...",
                "groupSeries": {
                    "FXUSDCAD": {
                        "label": "USD/CAD",
                        "link": "https://www.bankofcanada.ca/valet/series/FXUSDCAD",
                    }
                },
            }
        },
    )
    result = await client.get_group("FX_RATES_DAILY")
    assert result.name == "FX_RATES_DAILY"
    assert len(result.series) == 1
    assert result.series[0].name == "FXUSDCAD"
    assert result.series[0].label == "USD/CAD"
    assert result.series[0].link == "https://www.bankofcanada.ca/valet/series/FXUSDCAD"


async def test_get_observations_parses_string_value_to_float(httpx_mock):
    """Confirmed live: "v" is always a JSON string, even for numeric
    series ("1.3917")."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}observations/FXUSDCAD/json?recent=1",
        json={
            "seriesDetail": {
                "FXUSDCAD": {
                    "label": "USD/CAD",
                    "description": "Daily average exchange rate",
                    "dimension": {"key": "d", "name": "Date"},
                }
            },
            "observations": [{"d": "2026-09-15", "FXUSDCAD": {"v": "1.3917"}}],
        },
    )
    result = await client.get_observations(["FXUSDCAD"], recent=1)
    assert result.observations[0].values == {"FXUSDCAD": 1.3917}
    assert result.series["FXUSDCAD"].label == "USD/CAD"


async def test_get_observations_treats_empty_value_as_none():
    """Defensive parsing for a suppressed/empty data point - not seen
    live for the series checked this session, but the "v" field is
    string-typed so an empty string is a plausible upstream shape and
    must not crash parsing."""
    rows = [{"d": "2026-09-15", "FXUSDCAD": {"v": ""}}]
    observations = client._observations_from_json(rows)
    assert observations[0].values == {"FXUSDCAD": None}


async def test_get_observations_mixed_frequency_returns_unmerged_rows(httpx_mock):
    """Confirmed live: requesting a daily FX series and a monthly CPI
    series together under `recent` returns separate rows, each carrying
    only its own series - not one row per date with both keys."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}observations/FXUSDCAD,V41690973/json?recent=2",
        json={
            "seriesDetail": {
                "FXUSDCAD": {"label": "USD/CAD", "description": "", "dimension": {}},
                "V41690973": {"label": "Total CPI", "description": "", "dimension": {}},
            },
            "observations": [
                {"d": "2026-08-01", "V41690973": {"v": "169.8"}},
                {"d": "2026-09-15", "FXUSDCAD": {"v": "1.3917"}},
            ],
        },
    )
    result = await client.get_observations(["FXUSDCAD", "V41690973"], recent=2)
    assert len(result.observations) == 2
    assert all(len(row.values) == 1 for row in result.observations)


async def test_get_observations_treats_null_observations_as_empty(httpx_mock):
    """Valet can send "observations": null (not just an absent key) for
    a range/recent request matching no rows - list_or_empty() must
    coalesce this to [] rather than let None reach the row parser."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}observations/FXUSDCAD/json?recent=1",
        json={
            "seriesDetail": {"FXUSDCAD": {"label": "USD/CAD", "description": ""}},
            "observations": None,
        },
    )
    result = await client.get_observations(["FXUSDCAD"], recent=1)
    assert result.observations == []


async def test_get_observations_rejects_mixing_recent_and_date_range():
    """Mirrors Valet's own HTTP 400 for this combination (confirmed
    live) - caught client-side before making a request."""
    with pytest.raises(InvalidInput, match="Cannot mix"):
        await client.get_observations(["FXUSDCAD"], start_date="2024-01-01", recent=5)


async def test_get_observations_raises_invalid_input_on_bad_date_order(httpx_mock):
    """Confirmed live: end_date before start_date returns HTTP 400 with
    "The End date must be greater than the Start date."."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}observations/FXUSDCAD/json?start_date=2024-05-01&end_date=2024-01-01",
        status_code=400,
        json={"message": "The End date must be greater than the Start date.", "docs": ""},
    )
    with pytest.raises(InvalidInput, match="End date must be greater"):
        await client.get_observations(["FXUSDCAD"], start_date="2024-05-01", end_date="2024-01-01")


async def test_get_observations_rejects_empty_series_list():
    with pytest.raises(InvalidInput):
        await client.get_observations([])


async def test_get_group_observations_fills_name_from_argument(httpx_mock):
    """Confirmed live: /observations/group/{name}/json's "groupDetail"
    (singular) has no "name" field at all, unlike GroupDetail's
    "groupDetails" (plural). The caller's own group_name is used."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}observations/group/FX_RATES_DAILY/json?recent=1",
        json={
            "groupDetail": {
                "label": "Daily exchange rates",
                "description": "The daily average exchange rates...",
                "link": "https://www.bankofcanada.ca/?p=190892",
            },
            "seriesDetail": {},
            "observations": [],
        },
    )
    result = await client.get_group_observations("FX_RATES_DAILY", recent=1)
    assert result.group.name == "FX_RATES_DAILY"
    assert result.group.label == "Daily exchange rates"
    assert result.group.link == "https://www.bankofcanada.ca/?p=190892"


async def test_get_group_raises_not_found_on_404(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}groups/NOTAREAL/json",
        status_code=404,
        json={"message": "Group NOTAREAL not found.", "docs": ""},
    )
    with pytest.raises(NotFound, match="Group NOTAREAL not found"):
        await client.get_group("NOTAREAL")


async def test_get_series_rejects_empty_name():
    with pytest.raises(InvalidInput):
        await client.get_series("   ")


async def test_timeout_raises_upstream_unavailable(httpx_mock):
    # Uses a distinct series name from the other get_series tests above -
    # shared/cache.py's cache is a process-local singleton, so reusing
    # "FXUSDCAD" here would hit the cache entry a prior successful test
    # already populated instead of exercising the network path.
    for _ in range(3):
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
    with pytest.raises(UpstreamUnavailable):
        await client.get_series("FXEURCAD")
