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

from datetime import date

import httpx
import pytest

from maplestats_mcp.modules.boc import client, constants
from maplestats_mcp.modules.boc.schemas import SeriesSummary
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)


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


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    """Statuses compare a series' newest date with today: fix today."""
    monkeypatch.setattr(client, "today", lambda: date(2026, 11, 9))


def _latest(httpx_mock, names: str, newest: dict[str, str], *, lang: str = "en", **detail):
    """The observations?recent=1 response a status check reads: each series' newest row."""
    base = constants.BASE_URL_FR if lang == "fr" else constants.BASE_URL
    httpx_mock.add_response(
        url=f"{base}observations/{names}/json?recent=1",
        json={
            "seriesDetail": {
                n: {"label": n, "dateFormat": "daily", **detail} for n in names.split(",")
            },
            "observations": [{"d": d, n: {"v": "1"}} for n, d in newest.items()],
        },
    )


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
    _latest(httpx_mock, "FXUSDCAD", {"FXUSDCAD": "2026-11-06"})
    result = await client.search_series("exchange", limit=10)
    assert result.total_count == 1
    assert result.series[0].name == "FXUSDCAD"
    assert result.series[0].status == "active"
    assert result.series[0].last_observation == date(2026, 11, 6)
    assert "not a transactional rate" in (result.series[0].note or "")


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
    _latest(httpx_mock, "FXUSDCAD", {"FXUSDCAD": "2026-11-06"})
    result = await client.get_series("FXUSDCAD")
    assert result.name == "FXUSDCAD"
    assert result.label == "USD/CAD"
    assert (result.status, result.successor) == ("active", None)


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


async def test_get_group_reads_current_group_detail_key(httpx_mock):
    """Confirmed live in October 2026: Valet now wraps the group in
    "groupDetail" (singular), and each groupSeries entry carries a
    description and dateFormat."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}groups/FX_RATES_DAILY/json",
        json={
            "groupDetail": {
                "name": "FX_RATES_DAILY",
                "label": "Daily exchange rates",
                "description": "Daily average exchange rates...",
                "groupSeries": {
                    "FXUSDCAD": {
                        "label": "USD/CAD",
                        "description": "Daily average exchange rate...",
                        "dateFormat": "daily",
                        "link": "https://www.bankofcanada.ca/valet/series/FXUSDCAD",
                    }
                },
            }
        },
    )
    result = await client.get_group("FX_RATES_DAILY")
    assert result.name == "FX_RATES_DAILY"
    assert [m.name for m in result.series] == ["FXUSDCAD"]


async def test_get_group_parses_legacy_group_details_key(httpx_mock):
    """Before October 2026 the key was "groupDetails" (plural) and
    groupSeries entries had only label + link. Both shapes still parse."""
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
        json={"groupDetail": {"name": "EMPTY_GROUP", "label": "x", "groupSeries": None}},
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
    has no "name" field at all, unlike /groups/{name}/json's. The
    caller's own group_name is used."""
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


async def test_observations_without_a_window_keep_the_newest_dates_only(httpx_mock):
    """No window: the NO_WINDOW_DATES newest dates, and a limit saying how to get more."""
    rows = [{"d": f"2025-{m:02d}-01", "V41690973": {"v": "160.0"}} for m in range(1, 13)]
    rows += [{"d": f"2026-{m:02d}-01", "V41690973": {"v": "165.0"}} for m in range(1, 13)]
    rows += [{"d": f"2024-{m:02d}-01", "V41690973": {"v": "155.0"}} for m in range(1, 13)]
    rows.sort(key=lambda r: r["d"])
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}observations/V41690973/json",
        json={"seriesDetail": {"V41690973": {"label": "CPI"}}, "observations": rows},
    )
    result = await client.get_observations(["V41690973"])
    assert len(result.observations) == constants.NO_WINDOW_DATES
    assert str(result.observations[-1].ref_date) == "2026-12-01"
    assert "start_date" in (result.provenance.limits or "")


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
    _latest(httpx_mock, "V39079", {"V39079": "2026-11-06"}, lang="fr")
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
    _latest(httpx_mock, "V0,V1", {}, lang="fr")
    result = await client.search_series("taux directeur", limit=2, lang="fr")
    assert result.total_count == 3
    assert result.provenance.limits == (
        "Seules les 2 premières séries correspondantes sur 3 sont renvoyées ; "
        "précisez la requête ou augmentez limit (max. 200)."
    )
    assert (result.provenance.coverage or "").startswith(
        "recherche de sous-chaîne ou de tous les mots parmi 3 séries"
    )


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


async def test_get_series_without_series_details_raises_upstream_error(httpx_mock):
    # A changed payload must be a typed UpstreamError naming the field, not
    # a bare KeyError (which bypasses the typed-error mapping).
    url = f"{constants.BASE_URL}series/FXUSDCAD/json"
    httpx_mock.add_response(url=url, json={"terms": {}, "message": "moved"})
    with pytest.raises(UpstreamError, match="seriesDetails"):
        await client.get_series("FXUSDCAD")
    # The bad payload was not cached: the next call reaches Valet again.
    httpx_mock.add_response(url=url, json={"seriesDetails": {"name": "FXUSDCAD", "label": "x"}})
    _latest(httpx_mock, "FXUSDCAD", {"FXUSDCAD": "2026-11-06"})
    assert (await client.get_series("FXUSDCAD")).name == "FXUSDCAD"


async def test_get_series_details_without_name_raises_upstream_error(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}series/FXUSDCAD/json",
        json={"seriesDetails": {"label": "USD/CAD"}},
    )
    with pytest.raises(UpstreamError, match="seriesDetails.name"):
        await client.get_series("FXUSDCAD")


async def test_get_group_without_group_details_raises_upstream_error(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}groups/FX_RATES_DAILY/json", json={"terms": {}}
    )
    with pytest.raises(UpstreamError, match="groupDetail"):
        await client.get_group("FX_RATES_DAILY")


async def test_list_series_without_container_raises_upstream_error(httpx_mock):
    httpx_mock.add_response(url=f"{constants.BASE_URL}lists/series/json", json={"terms": {}})
    with pytest.raises(UpstreamError, match="'series'"):
        await client.list_series()


async def test_list_groups_with_non_object_container_raises_upstream_error(httpx_mock):
    httpx_mock.add_response(url=f"{constants.BASE_URL}lists/groups/json", json={"groups": []})
    with pytest.raises(UpstreamError, match="'groups'"):
        await client.list_groups()


async def test_get_observations_row_without_date_raises_upstream_error(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}observations/FXUSDCAD/json?recent=1",
        json={"observations": [{"FXUSDCAD": {"v": "1.39"}}]},
    )
    with pytest.raises(UpstreamError, match="'d'"):
        await client.get_observations(["FXUSDCAD"], recent=1)


async def test_get_group_observations_row_without_date_raises_upstream_error(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}observations/group/FX_RATES_DAILY/json?recent=1",
        json={"observations": ["2026-09-15"]},
    )
    with pytest.raises(UpstreamError, match="'d'"):
        await client.get_group_observations("FX_RATES_DAILY", recent=1)


def test_observations_from_json_names_the_missing_date_field_in_french():
    with pytest.raises(UpstreamError, match="La source amont a renvoy.*champ 'd' utilisable"):
        client._observations_from_json([{"FXUSDCAD": {"v": "1"}}], "observations/X/json", "fr")


async def test_get_series_missing_series_details_message_is_french(httpx_mock):
    httpx_mock.add_response(url=f"{constants.BASE_URL_FR}series/V39079/json", json={})
    with pytest.raises(UpstreamError, match="seriesDetails"):
        await client.get_series("V39079", lang="fr")


# Labels and descriptions as Valet gave them on 2026-11-09 (descriptions cut).
_CORE_INVENTORY = [
    ("CPI_TRIM", "CPI-trim", "The monthly value of the trim component of the Consumer Price Index"),
    ("CPI_MEDIAN", "CPI-median", "The monthly value of the median Consumer Price Index (CPI)."),
    ("STATIC_CPIXFET", "CPI-XFET, percentage change year-over-year (unadjusted)", ""),
    (
        "STATIC_TOTALCPICHANGE",
        "Total CPI, percentage change year-over-year (unadjusted)",
        "The unadjusted percentage change in the total Consumer Price Index (CPI).",
    ),
    ("CORRA_TRIMMED_VOLUME", "CORRA: trimmed dollar volume of trades eligible", ""),
    ("V39079", "Target for the overnight rate", "Policy interest rate"),
]


def _core_inventory():
    # Rarity decides a partial match, so pad with the common words, as the real
    # inventory of ~16,000 series is: "year-over-year" is everywhere, "trim" rare.
    filler = [
        SeriesSummary(name=f"FILLER_{i}", label=f"Series {i}", description=text)
        for i, text in enumerate(["Percentage change year-over-year"] * 20 + ["Rate"] * 20)
    ]
    return [
        SeriesSummary(name=n, label=lab, description=d) for n, lab, d in _CORE_INVENTORY
    ] + filler


@pytest.mark.parametrize(
    ("query", "first"),
    [
        ("CPI-trim", "CPI_TRIM"),
        ("cpitrim", "CPI_TRIM"),
        ("CPI-X", "STATIC_CPIXFET"),
        ("CPIXFET", "STATIC_CPIXFET"),
        ("CPI-median", "CPI_MEDIAN"),
    ],
)
def test_core_inflation_names_match_with_or_without_hyphens(query, first):
    matches, partial = client._filter_inventory(_core_inventory(), query)
    assert matches[0].name == first
    assert partial is False


@pytest.mark.parametrize(
    "query", ["CPI-trim inflation", "CPI-trim year-over-year", "core inflation CPI-trim"]
)
def test_extra_words_give_a_ranked_partial_match(query):
    # No entry holds "inflation" or "core": before 2026-11-09 these found nothing.
    matches, partial = client._filter_inventory(_core_inventory(), query)
    assert partial is True
    assert matches[0].name == "CPI_TRIM"
    assert "V39079" not in [m.name for m in matches]


def test_no_word_in_common_finds_nothing():
    assert client._filter_inventory(_core_inventory(), "zzzqqq") == ([], True)


async def test_partial_match_is_said_in_coverage(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}lists/groups/json",
        json={
            "groups": {
                "CPI_MONTHLY": {"label": "Consumer Price Index", "description": "CPI-trim"},
                "FX_RATES_DAILY": {"label": "Daily exchange rates", "description": ""},
            }
        },
    )
    result = await client.search_groups("CPI-trim core inflation")
    assert [g.name for g in result.groups] == ["CPI_MONTHLY"]
    assert "partial match" in (result.provenance.coverage or "")


async def test_banking_and_financial_statistics_searches_the_table_groups(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}lists/groups/json",
        json={
            "groups": {
                "A4_RATES_MONTHLY": {
                    "label": "Interest rates charged for new and existing lending by "
                    "chartered banks",
                    "description": "Month-end, rates in percentage",
                },
                "C1_MONTHLY": {"label": "Chartered bank selected assets: Month-end"},
                "E1_MONTHLY": {"label": "Selected monetary aggregates and their components"},
                "FSR_2023_C8": {
                    "label": "The cost of trading rose during recent banking stress",
                    "description": "Banking and financial statistics chart",
                },
            }
        },
    )
    everything = await client.search_groups("Bank of Canada Banking and Financial Statistics")
    assert [g.name for g in everything.groups] == ["A4_RATES_MONTHLY", "C1_MONTHLY", "E1_MONTHLY"]
    assets = await client.search_groups("BFS chartered bank assets")
    assert [g.name for g in assets.groups] == ["C1_MONTHLY"]
