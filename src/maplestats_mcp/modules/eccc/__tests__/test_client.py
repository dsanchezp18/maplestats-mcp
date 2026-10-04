"""Tests for the eccc module's client.py, shaped around the real MSC
GeoMet-OGC-API quirks confirmed live this session (see client.py's
module docstring): the silent-zero-results behavior for an unknown
property filter, per-collection-inconsistent datetime support (500 on
weather-alerts, working fine elsewhere), no server-side limit cap, and
404s for an unknown collection id.
"""

from __future__ import annotations

import httpx
import pytest

from maplestats_mcp.modules.eccc import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable


@pytest.fixture(autouse=True)
def _reset_shared_cache():
    """shared/cache.py's TTLCache is a process-local singleton keyed only
    by (ttl, cache_key) - not per-test. Without clearing it, a prior
    test's successful fetch would silently serve its cached result to a
    later test reusing the same cache key instead of exercising that
    test's own httpx_mock registration, making the suite order-dependent.
    """
    cache_module._caches.clear()
    yield


def _collections_payload():
    return {
        "collections": [
            {
                "id": "weather-alerts",
                "title": "Weather Alerts",
                "description": "Environment Canada issues weather alerts...",
                "keywords": ["Weather warnings", "Snow"],
                "itemType": "feature",
            },
            {
                "id": "aqhi-observations-realtime",
                "title": "AQHI - Observations",
                "description": "Air Quality Health Index observations.",
                "keywords": ["air quality"],
                "itemType": "feature",
            },
        ]
    }


def _collections_payload_fr():
    # Titles as /collections?f=json&lang=fr returns them (live 2026-10-03).
    payload = _collections_payload()
    payload["collections"][0]["title"] = "Alertes météo"
    payload["collections"][0]["description"] = "Environnement Canada publie des alertes météo."
    payload["collections"][0]["keywords"] = ["Avertissements météorologiques"]
    payload["collections"][1]["title"] = "Cote air santé - Observations"
    return payload


async def test_list_collections_parses_collections_list(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections?f=json&lang=en", json=_collections_payload()
    )
    result = await client.list_collections()
    assert result.total_count == 2
    assert result.collections[0].id == "weather-alerts"
    assert result.collections[0].item_type == "feature"
    assert result.provenance.cached is False


async def test_search_collections_filters_client_side(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections?f=json&lang=en", json=_collections_payload()
    )
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections?f=json&lang=fr", json=_collections_payload_fr()
    )
    result = await client.search_collections("air quality", limit=10)
    assert result.total_count == 1
    assert result.collections[0].id == "aqhi-observations-realtime"


async def test_search_collections_matches_french_text(httpx_mock):
    # Live 2026-10-03: "alerte" with lang="fr" found 0 of 104 collections
    # because only the English titles were searched.
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections?f=json&lang=fr", json=_collections_payload_fr()
    )
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections?f=json&lang=en", json=_collections_payload()
    )
    result = await client.search_collections("alerte", lang="fr")
    assert [c.id for c in result.collections] == ["weather-alerts"]
    assert result.collections[0].title == "Alertes météo"


async def test_get_collection_parses_detail_bbox_and_queryables(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections/weather-alerts?f=json&lang=en",
        json={
            "id": "weather-alerts",
            "title": "Weather Alerts",
            "description": "...",
            "keywords": ["Snow"],
            "itemType": "feature",
            "extent": {"spatial": {"bbox": [[-145.27, 37.3, -48.11, 87.61]]}},
            "links": [
                {
                    "rel": "canonical",
                    "href": "https://eccc-msc.github.io/open-data/msc-data/readme_en",
                },
                {"rel": "download", "href": "https://example.invalid/download.zip"},
            ],
        },
    )
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections/weather-alerts/queryables?f=json",
        json={
            "properties": {
                "province": {"title": "province", "type": "string"},
                "alert_type": {"title": "alert_type", "type": "string"},
            }
        },
    )
    result = await client.get_collection("weather-alerts")
    assert result.bbox == [-145.27, 37.3, -48.11, 87.61]
    assert {q.name for q in result.queryables} == {"province", "alert_type"}
    assert result.canonical_url == "https://eccc-msc.github.io/open-data/msc-data/readme_en"
    assert result.download_url == "https://example.invalid/download.zip"


async def test_get_collection_raises_not_found_on_404(httpx_mock):
    """Confirmed live: an unknown collection id returns HTTP 404 with a
    JSON body {"code": "NotFound", "description": "Collection not found"}."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections/not-a-real-collection?f=json&lang=en",
        status_code=404,
        json={"code": "NotFound", "description": "Collection not found"},
    )
    with pytest.raises(NotFound, match="Collection not found"):
        await client.get_collection("not-a-real-collection")


def _alert_feature():
    return {
        "id": "51729435807927362202609190501_fea1-1692",
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[-102.4, 51.9]]]},
        "properties": {
            "alert_code": "FGA",
            "alert_type": "advisory",
            "province": "SK",
            "status_en": "ended",
        },
    }


async def test_query_items_applies_property_filters(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections/weather-alerts/queryables?f=json",
        json={"properties": {"province": {"type": "string"}, "alert_type": {"type": "string"}}},
    )
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/collections/weather-alerts/items"
            "?f=json&lang=en&limit=10&offset=0&province=SK"
        ),
        json={
            "type": "FeatureCollection",
            "features": [_alert_feature()],
            "numberMatched": 1,
            "numberReturned": 1,
        },
    )
    result = await client.query_items("weather-alerts", filters={"province": "SK"})
    assert result.number_matched == 1
    assert result.items[0].properties["province"] == "SK"
    assert result.items[0].geometry is not None


async def test_query_items_rejects_unknown_filter_key_before_request(httpx_mock):
    """Confirmed live: an unknown property filter is silently ignored
    upstream and returns zero rows rather than an error - checked
    against /queryables client-side first instead."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections/weather-alerts/queryables?f=json",
        json={"properties": {"province": {"type": "string"}}},
    )
    with pytest.raises(InvalidInput, match="unknown"):
        await client.query_items("weather-alerts", filters={"not_a_real_property": "xyz"})


async def test_query_items_maps_datetime_500_to_invalid_input(httpx_mock):
    """Confirmed live: weather-alerts returns HTTP 500 "query error" for
    any datetime value, unlike hydrometric-realtime which filters fine."""
    # shared/http.py's api_get retries a 500 up to 3 times before
    # re-raising - all 3 attempts hit this same (permanently failing,
    # not transient) response.
    for _ in range(3):
        httpx_mock.add_response(
            url=(
                f"{constants.BASE_URL}/collections/weather-alerts/items"
                "?f=json&lang=en&limit=10&offset=0&datetime=2026-09-19"
            ),
            status_code=500,
            json={"code": "NoApplicableCode", "description": "query error (check logs)"},
        )
    with pytest.raises(InvalidInput, match="does not appear to support datetime filtering"):
        await client.query_items("weather-alerts", datetime_filter="2026-09-19")


async def test_malformed_datetime_is_refused_before_sending():
    # Live 2026-10-03: "notadate" on hydrometric-realtime reached the server
    # and its HTTP 500 read as "does not support datetime filtering".
    for bad in ("notadate", "2026-13-01", "2026-09-19T00:00:00", "a/b/c"):
        with pytest.raises(InvalidInput, match="RFC 3339"):
            await client.query_items("hydrometric-realtime", datetime_filter=bad)


async def test_items_stop_at_the_byte_budget(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "ITEMS_BYTES_MAX", 500)
    feature = _alert_feature()
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections/swob-realtime/items?f=json&lang=en&limit=5&offset=0",
        json={"type": "FeatureCollection", "features": [feature] * 5, "numberMatched": 900},
    )
    result = await client.query_items("swob-realtime", limit=5)
    assert 1 <= result.number_returned < 5
    assert result.note is not None and f"offset={result.number_returned}" in result.note


async def test_query_items_rejects_limit_above_max():
    with pytest.raises(InvalidInput, match="limit"):
        await client.query_items("weather-alerts", limit=constants.ITEMS_LIMIT_MAX + 1)


async def test_query_items_rejects_negative_offset():
    with pytest.raises(InvalidInput, match="offset"):
        await client.query_items("weather-alerts", offset=-1)


async def test_query_items_rejects_malformed_bbox():
    with pytest.raises(InvalidInput, match="bbox"):
        await client.query_items("weather-alerts", bbox=[1.0, 2.0, 3.0])


async def test_query_items_treats_null_features_as_empty(httpx_mock):
    """Defensive parsing for a response with no matching rows - mirrors
    the null-vs-absent-list handling this project already relies on for
    other government JSON APIs (see shared/json_utils.py)."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections/weather-alerts/items?f=json&lang=en&limit=10&offset=0",
        json={"type": "FeatureCollection", "features": None, "numberMatched": 0},
    )
    result = await client.query_items("weather-alerts")
    assert result.items == []


async def test_get_collection_rejects_empty_id():
    with pytest.raises(InvalidInput):
        await client.get_collection("   ")


async def test_timeout_raises_upstream_unavailable(httpx_mock):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
    with pytest.raises(UpstreamUnavailable):
        await client.get_collection("hydrometric-realtime")


# --- French ------------------------------------------------------------------

NBSP = " "


async def test_french_errors_use_the_typed_templates(httpx_mock):
    with pytest.raises(InvalidInput, match=f"^Entrée invalide{NBSP}: limit doit"):
        await client.query_items("weather-alerts", limit=0, lang="fr")
    with pytest.raises(InvalidInput, match="ouest, sud, est, nord"):
        await client.query_items("weather-alerts", bbox=[1.0, 2.0], lang="fr")
    with pytest.raises(InvalidInput, match="date-heure RFC 3339"):
        await client.query_items("hydrometric-realtime", datetime_filter="notadate", lang="fr")
    with pytest.raises(InvalidInput, match="ne doit pas être vide"):
        await client.get_collection("  ", lang="fr")
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections/weather-alerts/queryables?f=json",
        json={"properties": {"province": {"type": "string"}}},
    )
    with pytest.raises(InvalidInput, match="propriété inconnue"):
        await client.query_items("weather-alerts", filters={"provinc": "ON"}, lang="fr")


async def test_french_not_found_keeps_the_source_message(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections/nope?f=json&lang=fr",
        status_code=404,
        json={"code": "NotFound", "description": "Collection not found"},
    )
    with pytest.raises(NotFound) as err:
        await client.get_collection("nope", lang="fr")
    message = str(err.value)
    assert message.startswith(f"Aucune correspondance trouvée{NBSP}:")
    assert "en anglais" in message and "Collection not found" in message


async def test_french_items_note_names_the_french_properties(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "ITEMS_BYTES_MAX", 500)
    feature = _alert_feature()
    feature["properties"]["status_fr"] = "terminé"
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections/weather-alerts/items?f=json&lang=fr&limit=5&offset=0",
        json={"type": "FeatureCollection", "features": [feature] * 5, "numberMatched": 900},
    )
    result = await client.query_items("weather-alerts", limit=5, lang="fr")
    assert result.note is not None
    assert f"en français{NBSP}: status_fr" in result.note
    assert f"offset={result.number_returned}" in result.note
    assert (
        result.provenance.coverage
        == f"{result.number_returned} entités renvoyées sur 900 correspondantes"
    )
    assert result.provenance.limits is not None
    assert result.provenance.limits.startswith("limit plafonné à 1000 par requête.")
    assert "Environnement et Changement climatique Canada" in (result.provenance.licence or "")


async def test_english_items_have_no_note_when_nothing_is_cut(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections/weather-alerts/items?f=json&lang=en&limit=10&offset=0",
        json={"type": "FeatureCollection", "features": [_alert_feature()], "numberMatched": 1},
    )
    result = await client.query_items("weather-alerts")
    assert result.note is None
    assert result.provenance.coverage == "1 of 1 matching items returned"


async def test_french_search_coverage_text(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections?f=json&lang=fr", json=_collections_payload_fr()
    )
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/collections?f=json&lang=en", json=_collections_payload()
    )
    result = await client.search_collections("qualité", lang="fr")
    assert result.provenance.coverage is not None
    assert "collections examinées" in result.provenance.coverage
