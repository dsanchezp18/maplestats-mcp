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

from maplestats_mcp.modules.boc import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable


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
    # as_of is the newest observation date.
    assert result.provenance.as_of is not None
    assert result.provenance.as_of.date().isoformat() == "2026-09-15"


async def test_get_group_with_null_group_series_has_no_members(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}groups/EMPTY_GROUP/json",
        json={"groupDetails": {"name": "EMPTY_GROUP", "label": "x", "groupSeries": None}},
    )
    result = await client.get_group("EMPTY_GROUP")
    assert result.series == []


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


async def test_observations_url_reproduces_the_query_and_keeps_latest(httpx_mock, monkeypatch):
    """The provenance URL carries the query string sent, and a history over the
    byte budget keeps its most recent dates (Valet lists oldest first)."""
    rows = [{"d": f"2026-01-{day:02d}", "FXUSDCAD": {"v": "1.35"}} for day in range(1, 31)]
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}observations/FXUSDCAD/json?start_date=2026-01-01",
        json={"seriesDetail": {"FXUSDCAD": {"label": "USD/CAD"}}, "observations": rows},
    )
    monkeypatch.setattr(constants, "OBSERVATIONS_MAX_BYTES", 500)
    result = await client.get_observations(["FXUSDCAD"], start_date="2026-01-01")
    assert result.provenance.url.endswith("observations/FXUSDCAD/json?start_date=2026-01-01")
    assert 0 < len(result.observations) < 30
    assert str(result.observations[-1].ref_date) == "2026-01-30"
    assert (result.provenance.limits or "").startswith("Returned the most recent")
    assert "Bank of Canada" in (result.provenance.licence or "")


# French: lang="fr" reads Valet on the Bank's French domain and writes
# MapleStats's own errors, limits and coverage in French.


async def test_french_series_comes_from_the_french_domain(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL_FR}series/V39079/json",
        json={
            "seriesDetails": {
                "name": "V39079",
                "label": "Taux cible du financement à un jour (quotidien ouvrable)",
                "description": "Aussi appelé taux directeur.",
            }
        },
    )
    result = await client.get_series("V39079", lang="fr")
    assert result.label.startswith("Taux cible")
    assert result.provenance.url == f"{constants.BASE_URL_FR}series/V39079/json"
    assert "Banque du Canada" in (result.provenance.licence or "")
    assert (result.provenance.reproduce or "").startswith("Pour obtenir")


async def test_french_not_found_uses_the_french_template(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL_FR}series/NOPE/json",
        status_code=404,
        json={"message": "Série NOPE non valide.", "docs": ""},
    )
    with pytest.raises(NotFound, match="Aucune correspondance trouvée : Série NOPE"):
        await client.get_series("NOPE", lang="fr")


async def test_french_timeout_message(httpx_mock):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
    with pytest.raises(UpstreamUnavailable, match="n'a pas répondu à temps"):
        await client.get_series("FXGBPCAD", lang="fr")


async def test_french_input_errors():
    with pytest.raises(InvalidInput, match="Entrée invalide : start_date/end_date ne peuvent"):
        await client.get_observations(["FXUSDCAD"], start_date="2024-01-01", recent=5, lang="fr")
    with pytest.raises(InvalidInput, match="au moins un nom de série"):
        await client.get_observations([], lang="fr")
    with pytest.raises(InvalidInput, match="Le nom du groupe ne doit pas être vide"):
        await client.get_group("  ", lang="fr")
    with pytest.raises(InvalidInput, match="limit doit être compris entre 1 et 200"):
        await client.search_series("taux", limit=0, lang="fr")


async def test_french_search_limits_and_coverage(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL_FR}lists/series/json",
        json={
            "series": {
                f"V{i}": {"label": f"Taux {i}", "description": "taux directeur"} for i in range(3)
            }
        },
    )
    result = await client.search_series("taux directeur", limit=2, lang="fr")
    assert result.total_count == 3
    assert result.provenance.limits == (
        "Seules les 2 premières séries correspondantes sur 3 sont renvoyées ; "
        "précisez la requête ou augmentez limit (max. 200)."
    )
    assert (result.provenance.coverage or "").startswith("recherche de sous-chaîne parmi 3 séries")


async def test_french_observation_limits(httpx_mock, monkeypatch):
    rows = [{"d": f"2026-01-{day:02d}", "FXUSDCAD": {"v": "1.35"}} for day in range(1, 31)]
    httpx_mock.add_response(
        url=f"{constants.BASE_URL_FR}observations/FXUSDCAD/json?start_date=2026-01-01",
        json={"seriesDetail": {"FXUSDCAD": {"label": "USD/CAD"}}, "observations": rows},
    )
    monkeypatch.setattr(constants, "OBSERVATIONS_MAX_BYTES", 500)
    result = await client.get_observations(["FXUSDCAD"], start_date="2026-01-01", lang="fr")
    limits = result.provenance.limits or ""
    assert limits.startswith("Seules les ")
    assert "sur 30 sont renvoyées ; passez start_date/end_date" in limits


def test_french_page_limits_use_no_break_thousands():
    note = client._page_limits(50, 2538, "groups", "fr")
    assert note == (
        "Seuls les 50 premiers groupes sur 2 538 sont renvoyés ; "
        "cherchez avec query ou augmentez limit (max. 1000)."
    )
