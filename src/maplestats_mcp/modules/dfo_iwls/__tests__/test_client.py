"""Tests for modules/dfo_iwls/client.py, shaped on live 2026-09-23 responses."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from maplestats_mcp.modules.dfo_iwls import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_STATIONS_URL = re.compile(re.escape(constants.BASE_URL) + r"/stations$")
_VICTORIA = {
    "code": "07120",
    "id": "5cebf1df3d0f4a073c4bbd1e",
    "latitude": 48.424363,
    "longitude": -123.370828,
    "officialName": "Victoria Harbour",
    "operating": True,
    "type": "PERMANENT",
    "timeSeries": [
        {
            "code": "wlo",
            "nameEn": "Water level official value",
            "nameFr": "Niveau d'eau, valeur officielle",
        },
        {
            "code": "wlp",
            "nameEn": "Water level predictions",
            "nameFr": "Prédictions de niveaux d'eau",
        },
        {
            "code": "wlp-hilo",
            "nameEn": "High and Low Tide Predictions",
            "nameFr": "Prédictions de pleines et basses mers",
        },
    ],
}
_CLOSED = {
    "code": "04315",
    "id": "5cebf1dd3d0f4a073c4bb8c3",
    "officialName": "Tasiujaq",
    "alternativeName": "Leaf Basin",
    "operating": False,
    "timeSeries": [{"code": "wlo", "nameEn": "Water level official value"}],
}


async def test_search_filters_operating_and_matches_alternative_name(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA, _CLOSED])
    result = await client.search_stations("victoria")
    assert [s.code for s in result.stations] == ["07120"]
    assert (await client.search_stations("leaf")).total_matches == 0
    closed = await client.search_stations("leaf", operating_only=False, lang="fr")
    assert closed.stations[0].time_series[0].name == "Water level official value"


async def test_get_water_levels_hilo_omits_resolution(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(
        json=[
            {
                "eventDate": "2026-09-23T02:40:00Z",
                "qcFlagCode": "1",
                "reviewed": False,
                "value": 2.181,
            },
            {
                "eventDate": "2026-09-23T14:52:00Z",
                "qcFlagCode": "1",
                "reviewed": False,
                "value": 0.922,
            },
            {"eventDate": "2026-09-23T20:00:00Z", "qcFlagCode": "1", "value": None},
        ]
    )
    result = await client.get_water_levels(
        "7120",
        "wlp-hilo",
        start="2026-09-23",
        end="2026-09-24",
        resolution="SIXTY_MINUTES",
        lang="fr",
    )
    assert result.series_name == "Prédictions de pleines et basses mers"
    assert [p.value for p in result.points] == [2.181, 0.922]
    assert "pas de temps sans valeur dans la source, omis\u00a0: 1" in (
        result.provenance.limits or ""
    )
    assert result.resolution is None
    params = parse_qs(urlparse(str(httpx_mock.get_requests()[-1].url)).query)
    assert "resolution" not in params
    assert params["from"] == ["2026-09-23T00:00:00Z"]


async def test_get_water_levels_sends_resolution_for_regular_series(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(json=[])
    await client.get_water_levels(
        "07120", "wlp", start="2026-09-23", end="2026-09-24", resolution="SIXTY_MINUTES"
    )
    params = parse_qs(urlparse(str(httpx_mock.get_requests()[-1].url)).query)
    assert params["resolution"] == ["SIXTY_MINUTES"]


async def test_date_only_end_covers_that_whole_day(httpx_mock):
    # Live 2026-10-03: start=end="2026-10-03" was refused ("end must be after
    # start") because a date-only end meant midnight at its start.
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(json=[])
    result = await client.get_water_levels(
        "07120", "wlp", start="2026-10-03", end="2026-10-03", resolution="ONE_MINUTE"
    )
    params = parse_qs(urlparse(str(httpx_mock.get_requests()[-1].url)).query)
    assert params["from"] == ["2026-10-03T00:00:00Z"]
    assert params["to"] == ["2026-10-04T00:00:00Z"]
    assert result.resolution == "ONE_MINUTE"


async def test_long_minute_series_default_to_hourly(httpx_mock):
    # Live: wlo over 2026-09-25..2026-10-02 at the default one-minute step was 767 KB.
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(json=[])
    result = await client.get_water_levels("07120", "wlo", start="2026-09-25", end="2026-10-01")
    params = parse_qs(urlparse(str(httpx_mock.get_requests()[-1].url)).query)
    assert params["resolution"] == ["SIXTY_MINUTES"]
    assert result.resolution == "SIXTY_MINUTES"


async def test_date_only_end_one_day_past_the_cap_is_clamped(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(json=[])
    result = await client.get_water_levels("07120", "wlp", start="2026-09-01", end="2026-09-08")
    params = parse_qs(urlparse(str(httpx_mock.get_requests()[-1].url)).query)
    assert params["to"] == ["2026-09-08T00:00:00Z"]
    # The hours of 2026-09-08 that were not fetched are named in limits.
    assert "were not fetched" in (result.provenance.limits or "")


async def test_window_over_seven_days_is_rejected_before_calling(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    with pytest.raises(InvalidInput, match="7 days"):
        await client.get_water_levels("07120", "wlp", start="2026-09-01", end="2026-09-30")


async def test_end_alone_returns_the_24_hours_up_to_it(httpx_mock):
    # An `end` in the past with no `start` used to fall back to a start of "now",
    # so the call was refused with "end must be after start".
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(json=[])
    result = await client.get_water_levels("07120", "wlo", end="2026-10-03T12:00:00Z")
    params = parse_qs(urlparse(str(httpx_mock.get_requests()[-1].url)).query)
    assert params["from"] == ["2026-10-02T12:00:00Z"]
    assert params["to"] == ["2026-10-03T12:00:00Z"]
    assert result.start.isoformat() == "2026-10-02T12:00:00+00:00"


async def test_date_only_end_alone_returns_that_whole_day(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(json=[])
    await client.get_water_levels("07120", "wlp", end="2026-10-03", resolution="SIXTY_MINUTES")
    params = parse_qs(urlparse(str(httpx_mock.get_requests()[-1].url)).query)
    assert params["from"] == ["2026-10-03T00:00:00Z"]
    assert params["to"] == ["2026-10-04T00:00:00Z"]


async def test_observed_series_default_to_the_last_24_hours(httpx_mock, monkeypatch):
    # Observed levels (wlo) do not exist yet for "now to +24 h": that window came
    # back with no points and no note.
    monkeypatch.setattr(client, "_now", lambda: datetime(2026, 10, 3, 15, 47, 30, tzinfo=UTC))
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(json=[])
    await client.get_water_levels("07120", "wlo", resolution="SIXTY_MINUTES")
    params = parse_qs(urlparse(str(httpx_mock.get_requests()[-1].url)).query)
    # The end is floored to the 10-minute cache step (see the next test).
    assert params["from"] == ["2026-10-02T15:40:00Z"]
    assert params["to"] == ["2026-10-03T15:40:00Z"]


async def test_observed_default_window_is_stable_within_the_cache_step(httpx_mock, monkeypatch):
    # An end at the current minute changed the cache key (it holds from and to) every
    # minute, so each default call stored a new day-long series for its 10 minutes.
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(json=[])
    for minute in (41, 49):
        monkeypatch.setattr(
            client, "_now", lambda minute=minute: datetime(2026, 10, 3, 15, minute, tzinfo=UTC)
        )
        await client.get_water_levels("07120", "wlo", resolution="SIXTY_MINUTES")
    data_requests = [r for r in httpx_mock.get_requests() if "/data" in str(r.url)]
    assert len(data_requests) == 1


async def test_predicted_series_keep_now_to_plus_24_hours(httpx_mock, monkeypatch):
    monkeypatch.setattr(client, "_now", lambda: datetime(2026, 10, 3, 15, 42, 30, tzinfo=UTC))
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(json=[])
    httpx_mock.add_response(json=[])
    await client.get_water_levels("07120", "wlp-hilo")
    await client.get_water_levels("07120", "wlp", resolution="SIXTY_MINUTES")
    for request in httpx_mock.get_requests()[-2:]:
        params = parse_qs(urlparse(str(request.url)).query)
        assert params["from"] == ["2026-10-03T15:00:00Z"]
        assert params["to"] == ["2026-10-04T15:00:00Z"]


async def test_series_not_known_to_be_observed_keep_now_to_plus_24_hours(httpx_mock, monkeypatch):
    # Only "wlo" is confirmed as an observed series; any other series (a forecast, a
    # predicted current) must not get the past window, which for it is zero points
    # and no note. "wcsp1" stands for a code this module has never listed.
    monkeypatch.setattr(client, "_now", lambda: datetime(2026, 10, 3, 15, 42, 30, tzinfo=UTC))
    other = {**_VICTORIA, "timeSeries": [{"code": "wcsp1", "nameEn": "Predicted current"}]}
    httpx_mock.add_response(url=_STATIONS_URL, json=[other])
    httpx_mock.add_response(json=[])
    await client.get_water_levels("07120", "wcsp1", resolution="SIXTY_MINUTES")
    params = parse_qs(urlparse(str(httpx_mock.get_requests()[-1].url)).query)
    assert params["from"] == ["2026-10-03T15:00:00Z"]
    assert params["to"] == ["2026-10-04T15:00:00Z"]


async def test_search_folds_accents_and_pads_codes(httpx_mock):
    # "pointe-au-pere" missed "Pointe-au-Père", and "7120" missed "07120" although
    # get_station pads the same code.
    pointe = {
        "code": "03360",
        "id": "5cebf1df3d0f4a073c4bbd99",
        "officialName": "Pointe-au-Père",
        "operating": True,
        "timeSeries": [],
    }
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA, pointe])
    assert [s.code for s in (await client.search_stations("pointe-au-pere")).stations] == ["03360"]
    assert [s.code for s in (await client.search_stations("POINTE-AU-PÈRE")).stations] == ["03360"]
    assert [s.code for s in (await client.search_stations("7120")).stations] == ["07120"]
    assert [s.code for s in (await client.search_stations(" 07120 ")).stations] == ["07120"]


async def test_unknown_series_and_station(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    with pytest.raises(InvalidInput, match="available"):
        await client.get_water_levels("07120", "wlf")
    with pytest.raises(NotFound):
        await client.get_station("99999")
    with pytest.raises(InvalidInput):
        await client.get_station("victoria")


async def test_upstream_400_maps_to_invalid_input(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(
        status_code=400,
        json={
            "status": "400 BAD_REQUEST",
            "message": "Wrong parameter format",
            "errors": ["from is improperly formatted"],
        },
    )
    with pytest.raises(InvalidInput, match="improperly formatted"):
        await client.get_water_levels("07120", "wlo", start="2026-09-23", end="2026-09-24")


async def test_get_station_reads_datums(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    httpx_mock.add_response(
        json={
            "chsRegionCode": "PAC",
            "isTidal": True,
            "isTideTableReferencePort": True,
            "establishedYear": 1905,
            "datums": [{"code": "CGVD2013", "offset": -1.71}],
        }
    )
    detail = await client.get_station("07120")
    assert detail.region_code == "PAC"
    assert detail.datums[0].offset == -1.71


async def test_french_errors_and_provenance(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    result = await client.search_stations("victoria", lang="fr")
    prov = result.provenance
    assert "mise en cache 24" in (prov.freshness or "")
    assert (prov.limits or "").startswith("Requête\xa0: GET")
    assert "Conditions non précisées" in (prov.licence or "")
    assert result.stations[0].time_series[0].name == "Niveau d'eau, valeur officielle"
    with pytest.raises(InvalidInput, match=r"^Entrée invalide\xa0: la période doit"):
        await client.get_water_levels(
            "07120", "wlp", start="2026-09-01", end="2026-09-30", lang="fr"
        )
    with pytest.raises(InvalidInput, match="séries disponibles"):
        await client.get_water_levels("07120", "wlf", lang="fr")
    with pytest.raises(NotFound, match="aucune station marégraphique"):
        await client.get_station("99999", lang="fr")


async def test_english_provenance_is_unchanged(httpx_mock):
    httpx_mock.add_response(url=_STATIONS_URL, json=[_VICTORIA])
    prov = (await client.search_stations("victoria")).provenance
    assert prov.freshness == "station list cached 24h"
    assert (prov.licence or "").startswith("Terms not stated by the publisher")
    with pytest.raises(InvalidInput, match=r"^The window must be 7 days or less\.$"):
        await client.get_water_levels("07120", "wlp", start="2026-09-01", end="2026-09-30")
