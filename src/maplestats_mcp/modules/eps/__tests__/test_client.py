"""Tests for eps/client.py, shaped around quirks confirmed live
2026-09-22 (see the module docstring): 12:00 UTC calendar dates, the
DD/MM/YYYY load date, and HTTP 200 responses carrying an embedded error.
"""

from __future__ import annotations

import json
import re
from datetime import date

import httpx
import pytest

from maplestats_mcp.modules.eps import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable

_CURRENT_QUERY = re.compile(re.escape(constants.DATASETS["current"]) + r"/query.*")


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


def test_build_where_quotes_and_makes_end_date_inclusive():
    where = client.build_where(
        category="Violent",
        group="O'Brien",
        start_date="2026-09-01",
        end_date="2026-09-01",
        intersection_contains=" jasper av ",
    )
    assert "Occurrence_Category = 'Violent'" in where
    assert "Occurrence_Group = 'O''Brien'" in where
    assert "Reported_Date >= DATE '2026-09-01'" in where
    assert "Reported_Date < DATE '2026-09-02'" in where
    assert "UPPER(Intersection) LIKE '%JASPER AV%'" in where


def test_build_where_defaults_to_all_rows():
    assert client.build_where() == "1=1"


def test_build_where_rejects_bad_dates():
    with pytest.raises(InvalidInput):
        client.build_where(start_date="2026/09/01")
    with pytest.raises(InvalidInput):
        client.build_where(start_date="2026-09-02", end_date="2026-09-01")


async def test_list_occurrences_parses_rows(httpx_mock):
    httpx_mock.add_response(url=_CURRENT_QUERY, json={"count": 17})
    httpx_mock.add_response(
        url=_CURRENT_QUERY,
        json={
            "features": [
                {
                    "attributes": {
                        "Reported_Date": 1769342400000,
                        "Occurrence_Category": "Non-Violent",
                        "Occurrence_Group": "Property",
                        "Occurrence_Type_Group": "Theft From Vehicle",
                        "Intersection": "82 ST/123 AV",
                    },
                    "geometry": {"x": -113.45, "y": 53.57},
                }
            ]
        },
    )
    result = await client.list_occurrences(limit=1)
    assert result.total_matches == 17
    occurrence = result.occurrences[0]
    assert occurrence.reported_date is not None
    assert occurrence.reported_date.isoformat() == "2026-01-25"
    assert occurrence.intersection == "82 ST/123 AV"
    assert occurrence.latitude == 53.57


async def test_embedded_error_becomes_invalid_input(httpx_mock):
    httpx_mock.add_response(
        url=_CURRENT_QUERY,
        json={"error": {"code": 400, "message": "Invalid query", "details": ["bad where"]}},
    )
    with pytest.raises(InvalidInput):
        await client.list_occurrences(category="Violent")


async def test_summarize_occurrences_by_month(httpx_mock):
    httpx_mock.add_response(url=_CURRENT_QUERY, json={"count": 3})
    httpx_mock.add_response(
        url=_CURRENT_QUERY,
        json={
            "features": [
                {
                    "attributes": {
                        "Reported_Year": "2026",
                        "Reported_Month": 8,
                        "occurrence_count": 2,
                    }
                },
                {
                    "attributes": {
                        "Reported_Year": "2026",
                        "Reported_Month": 9,
                        "occurrence_count": 1,
                    }
                },
            ]
        },
    )
    result = await client.summarize_occurrences(group_by="month")
    assert result.total_matches == 3
    assert [group.count for group in result.groups] == [2, 1]
    assert result.groups[0].keys == {"Reported_Year": "2026", "Reported_Month": 8}


async def test_invalid_arguments_raise():
    with pytest.raises(InvalidInput):
        await client.list_occurrences(limit=0)
    with pytest.raises(InvalidInput):
        await client.summarize_occurrences(group_by="neighbourhood")  # type: ignore[arg-type]
    with pytest.raises(InvalidInput):
        await client.list_occurrences("2024")  # type: ignore[arg-type]


async def test_get_last_load_date_parses_day_first(httpx_mock):
    httpx_mock.add_response(json={"features": [{"attributes": {"Last_Load_Date": "20/09/2026"}}]})
    result = await client.get_last_load_date()
    assert result.last_load_date is not None
    assert result.last_load_date.isoformat() == "2026-09-20"
    assert result.raw_value == "20/09/2026"


async def test_empty_load_date_table_means_a_reload_in_progress(httpx_mock):
    # EPS rebuilds this table on reload; it was empty on 2026-09-28.
    httpx_mock.add_response(json={"features": []})
    with pytest.raises(UpstreamUnavailable, match="reloads"):
        await client.get_last_load_date()


# Trimmed from a live GET of EPS_OCC_30DAY/FeatureServer/0/query (where=1=1,
# resultRecordCount=4, outSR=4326, orderByFields="Reported_Date DESC, OBJECTID DESC")
# on 2026-10-03; 2 of 4 features kept. Real quirks: a `fields` schema block and
# `exceededTransferLimit: true` sit beside `features`, coordinates carry full double
# precision, and an intersection can repeat one street ("104 AV/104 AV").
_LIVE_LIST = {
    "objectIdFieldName": "OBJECTID",
    "uniqueIdField": {"name": "OBJECTID", "isSystemMaintained": True},
    "globalIdFieldName": "",
    "geometryType": "esriGeometryPoint",
    "spatialReference": {"wkid": 4326, "latestWkid": 4326},
    "fields": [
        {"name": "Reported_Date", "type": "esriFieldTypeDate", "alias": "Reported_Date"},
        {"name": "Intersection", "type": "esriFieldTypeString", "alias": "Intersection"},
    ],
    "exceededTransferLimit": True,
    "features": [
        {
            "attributes": {
                "Reported_Date": 1790510400000,
                "Occurrence_Category": "Non-Violent",
                "Occurrence_Group": "Property",
                "Occurrence_Type_Group": "Theft Under $5000",
                "Intersection": "104 AV/104 AV",
            },
            "geometry": {"x": -113.52028256889207, "y": 53.546222068842177},
        },
        {
            "attributes": {
                "Reported_Date": 1790510400000,
                "Occurrence_Category": "Disorder",
                "Occurrence_Group": "Mischief/Graffiti",
                "Occurrence_Type_Group": "Mischief - Property",
                "Intersection": "116 ST/JASPER AV",
            },
            "geometry": {"x": -113.52133686268476, "y": 53.540883283420627},
        },
    ],
}

# Trimmed from the same layer's outStatistics query grouped by
# Reported_Year,Reported_Month on 2026-10-03. Reported_Year is a string and
# Reported_Month an integer (the layer's own field types), the response's
# spatialReference is Web Mercator although no geometry is returned, and the first
# month is partial (the rolling window starts mid-September 2025).
_LIVE_MONTHS = {
    "objectIdFieldName": "OBJECTID",
    "spatialReference": {"wkid": 102100, "latestWkid": 3857},
    "fields": [
        {"name": "occurrence_count", "type": "esriFieldTypeInteger"},
        {"name": "Reported_Year", "type": "esriFieldTypeString", "length": 10},
        {"name": "Reported_Month", "type": "esriFieldTypeInteger"},
    ],
    "exceededTransferLimit": True,
    "features": [
        {"attributes": {"occurrence_count": 422, "Reported_Year": "2025", "Reported_Month": 9}},
        {"attributes": {"occurrence_count": 6926, "Reported_Year": "2025", "Reported_Month": 10}},
    ],
}


def _params(request: httpx.Request) -> dict[str, str]:
    return dict(request.url.params)


async def test_list_occurrences_live_shape_and_request(httpx_mock):
    httpx_mock.add_response(url=_CURRENT_QUERY, json={"count": 79018})
    httpx_mock.add_response(url=_CURRENT_QUERY, json=_LIVE_LIST)
    result = await client.list_occurrences(category="Disorder", limit=2, offset=50)
    assert result.total_matches == 79018
    assert result.offset == 50
    assert [o.reported_date for o in result.occurrences] == [date(2026, 9, 27)] * 2
    assert result.occurrences[0].type_group == "Theft Under $5000"
    assert result.occurrences[1].longitude == -113.52133686268476
    count_request, page_request = httpx_mock.get_requests()
    assert _params(count_request)["returnCountOnly"] == "true"
    page = _params(page_request)
    assert page["where"] == "Occurrence_Category = 'Disorder'"
    assert page["resultOffset"] == "50"
    assert page["resultRecordCount"] == "2"
    assert page["outSR"] == "4326"
    assert page["returnGeometry"] == "true"
    assert page["orderByFields"] == "Reported_Date DESC, OBJECTID DESC"


async def test_summarize_by_month_live_shape_and_request(httpx_mock):
    httpx_mock.add_response(url=_CURRENT_QUERY, json={"count": 7348})
    httpx_mock.add_response(url=_CURRENT_QUERY, json=_LIVE_MONTHS)
    result = await client.summarize_occurrences(group_by="month", top=2)
    assert [group.keys for group in result.groups] == [
        {"Reported_Year": "2025", "Reported_Month": 9},
        {"Reported_Year": "2025", "Reported_Month": 10},
    ]
    assert [group.count for group in result.groups] == [422, 6926]
    query = _params(httpx_mock.get_requests()[1])
    assert query["groupByFieldsForStatistics"] == "Reported_Year,Reported_Month"
    # Months must come back in calendar order, not by size.
    assert query["orderByFields"] == "Reported_Year, Reported_Month"
    assert json.loads(query["outStatistics"])[0]["outStatisticFieldName"] == "occurrence_count"


async def test_embedded_invalid_field_error_live_shape(httpx_mock):
    # Live 2026-10-03 for where=Bogus_Field = 'x': HTTP 200, an empty `message`,
    # and the real reason only in `details`. It must surface in the error text.
    httpx_mock.add_response(
        url=_CURRENT_QUERY,
        json={
            "error": {
                "code": 400,
                "message": "",
                "details": ["'Invalid field: Bogus_Field' parameter is invalid"],
            }
        },
    )
    with pytest.raises(InvalidInput, match="Invalid field: Bogus_Field"):
        await client.summarize_occurrences(group_by="type")


async def test_upstream_5xx_is_retried_then_raises_typed_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(url=_CURRENT_QUERY, status_code=503)
    # shared/arcgis.py maps a 5xx left after retries to UpstreamError today; either
    # typed error is acceptable here, a raw httpx.HTTPStatusError is not.
    with pytest.raises((UpstreamError, UpstreamUnavailable), match="503"):
        await client.list_occurrences()
    assert len(httpx_mock.get_requests()) == 3


async def test_html_body_is_a_typed_error(httpx_mock):
    # An ArcGIS outage page answers with HTML where JSON is expected.
    httpx_mock.add_response(
        url=_CURRENT_QUERY,
        text="<html><body>Service Unavailable</body></html>",
        headers={"Content-Type": "text/html"},
    )
    with pytest.raises((UpstreamError, UpstreamUnavailable)):
        await client.list_occurrences()


async def test_null_lists_and_fields_are_tolerated(httpx_mock):
    # ArcGIS can send `"features": null` and null attributes/geometry; none of
    # them may crash parsing (null-instead-of-absent, see shared/json_utils).
    httpx_mock.add_response(url=_CURRENT_QUERY, json={"count": None})
    httpx_mock.add_response(
        url=_CURRENT_QUERY,
        json={
            "features": [
                {
                    "attributes": {
                        "Reported_Date": None,
                        "Occurrence_Category": "Traffic",
                        "Occurrence_Group": None,
                        "Occurrence_Type_Group": None,
                        "Intersection": None,
                    },
                    "geometry": None,
                },
                {"attributes": None},
            ]
        },
    )
    result = await client.list_occurrences()
    assert result.total_matches == 0
    first, second = result.occurrences
    assert first.reported_date is None
    assert first.category == "Traffic"
    assert first.latitude is None and first.longitude is None
    assert second.category is None

    cache_module._caches.clear()
    httpx_mock.add_response(url=_CURRENT_QUERY, json={"count": 0})
    httpx_mock.add_response(url=_CURRENT_QUERY, json={"features": None})
    summary = await client.summarize_occurrences(intersection_contains="NOWHERE ST")
    assert summary.total_matches == 0
    assert summary.groups == []


async def test_load_date_live_shape_and_unexpected_formats(httpx_mock):
    # Live 2026-10-03 (FME_Load_Date/FeatureServer/0/query): an OBJECTID beside
    # Last_Load_Date, still DD/MM/YYYY.
    httpx_mock.add_response(
        json={
            "objectIdFieldName": "OBJECTID",
            "fields": [{"name": "Last_Load_Date", "alias": "Data as of:"}],
            "features": [{"attributes": {"OBJECTID": 1, "Last_Load_Date": "28/09/2026"}}],
        }
    )
    assert (await client.get_last_load_date()).last_load_date == date(2026, 9, 28)

    # If EPS switched to ISO the raw text must survive with no guessed date, and a
    # null value must not crash.
    for raw in ("2026-09-28", None):
        cache_module._caches.clear()
        httpx_mock.add_response(json={"features": [{"attributes": {"Last_Load_Date": raw}}]})
        result = await client.get_last_load_date()
        assert result.last_load_date is None
        assert result.raw_value == raw


async def test_out_of_range_paging_is_rejected_before_any_request():
    # No httpx_mock responses are registered: any request would fail the test.
    with pytest.raises(InvalidInput, match="offset"):
        await client.list_occurrences(offset=-1)
    with pytest.raises(InvalidInput, match="limit"):
        await client.list_occurrences(limit=constants.LIMIT_MAX + 1)
    with pytest.raises(InvalidInput, match="top"):
        await client.summarize_occurrences(top=0)
    with pytest.raises(InvalidInput, match="end_date"):
        await client.summarize_occurrences(end_date="28/09/2026")


def test_build_where_bad_date_in_french():
    with pytest.raises(InvalidInput, match="Entrée invalide") as excinfo:
        client.build_where(start_date="2026/09/01", lang="fr")
    assert "date ISO (AAAA-MM-JJ)" in str(excinfo.value)


async def test_invalid_limit_in_french():
    with pytest.raises(InvalidInput, match="limit doit être compris entre 1 et 500"):
        await client.list_occurrences(limit=0, lang="fr")


async def test_summary_provenance_in_french(httpx_mock):
    httpx_mock.add_response(url=_CURRENT_QUERY, json={"count": 0})
    httpx_mock.add_response(url=_CURRENT_QUERY, json={"features": []})
    result = await client.summarize_occurrences(top=5, lang="fr")
    assert result.provenance.freshness is not None
    assert "mis à jour chaque jour par le Service de police" in result.provenance.freshness
    assert result.provenance.coverage is not None
    assert "12 mois glissants" in result.provenance.coverage
    assert result.provenance.limits == "au plus 5 groupes renvoyés"
    assert result.provenance.licence is not None
    assert "Service de police d'Edmonton" in result.provenance.licence


async def test_summary_provenance_english_unchanged(httpx_mock):
    httpx_mock.add_response(url=_CURRENT_QUERY, json={"count": 0})
    httpx_mock.add_response(url=_CURRENT_QUERY, json={"features": []})
    result = await client.summarize_occurrences(top=5)
    assert result.provenance.freshness == (
        "refreshed daily by EPS with a 24-48 hour publication delay"
    )
    assert result.provenance.coverage == "rolling ~12 months to the last refresh"
    assert result.provenance.limits == "at most 5 groups returned"
