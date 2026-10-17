"""Tests for bcgw/client.py, shaped around real BCGW field shapes and
CQL-building confirmed live 2026-09-22 (see client.py's module
docstring for the GML-date "Z"-suffix quirk).
"""

from __future__ import annotations

import re

import httpx
import pytest

from maplestats_mcp.modules.bcgw import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_WILDFIRE_FEATURE = {
    "type": "Feature",
    "id": "prot.1",
    "geometry": None,
    "properties": {
        "FIRE_NUMBER": "C20851",
        "FIRE_YEAR": 2026,
        "FIRE_SIZE_HECTARES": 8.9,
        "SOURCE": "Non-corrected ground GPS",
        "TRACK_DATE": "2026-07-16Z",
        "LOAD_DATE": "2026-07-17Z",
        "FIRE_STATUS": "Out",
        "FIRE_URL": "https://wildfiresituation.nrs.gov.bc.ca/incidents?fireYear=2026&incidentNumber=C20851",
    },
}
_WILDFIRE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [_WILDFIRE_FEATURE],
    "totalFeatures": 304,
    "numberMatched": 304,
}

_TENURE_FEATURE = {
    "type": "Feature",
    "id": "mta.1",
    "geometry": None,
    "properties": {
        "TENURE_NUMBER_ID": 217457,
        "CLAIM_NAME": "NORSE #6",
        "TENURE_TYPE_CODE": "M",
        "TENURE_TYPE_DESCRIPTION": "Mineral",
        "TENURE_SUB_TYPE_DESCRIPTION": "CLAIM",
        "TITLE_TYPE_DESCRIPTION": "Four Post Claim",
        "ISSUE_DATE": "1985-06-27Z",
        "GOOD_TO_DATE": "2035-12-30Z",
        "AREA_IN_HECTARES": 300,
        "OWNER_NAME": "TECK HIGHLAND VALLEY COPPER CORPORATION",
        "PERCENT_OWNERSHIP": 100,
        "NUMBER_OF_OWNERS": 1,
        "STATEMENT_OF_WORK_EVENT_COUNT": 19,
        "TERMINATION_DATE": None,
    },
}
_TENURE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [_TENURE_FEATURE],
    "totalFeatures": 42282,
    "numberMatched": 42282,
}


async def test_get_active_wildfires_parses_records(httpx_mock):
    httpx_mock.add_response(json=_WILDFIRE_COLLECTION)
    result = await client.get_active_wildfires()
    assert result.returned_count == 1
    assert result.total_matched == 304
    fire = result.wildfires[0]
    assert fire.fire_number == "C20851"
    assert fire.fire_year == 2026
    assert fire.status == "Out"
    assert fire.track_date is not None
    assert fire.track_date.isoformat() == "2026-07-16"
    assert fire.geometry is None

    request = httpx_mock.get_requests()[0]
    assert request.url.params["typeName"] == constants.WILDFIRE_TYPE_NAME
    assert request.url.params["propertyName"] == constants.WILDFIRE_ATTRIBUTE_FIELDS
    # 250 of 312 live perimeters were "Out" on 2026-10-03 and came first by
    # OBJECTID: by default they are filtered out and the largest fires lead.
    assert request.url.params["CQL_FILTER"] == "(FIRE_STATUS IS NULL OR FIRE_STATUS<>'Out')"
    assert request.url.params["sortBy"] == "FIRE_SIZE_HECTARES D,OBJECTID A"


async def test_get_active_wildfires_include_out_sends_no_status_filter(httpx_mock):
    httpx_mock.add_response(json=_WILDFIRE_COLLECTION)
    await client.get_active_wildfires(include_out=True)
    assert "CQL_FILTER" not in httpx_mock.get_requests()[0].url.params


async def test_get_active_wildfires_builds_cql_from_filters(httpx_mock):
    httpx_mock.add_response(json=_WILDFIRE_COLLECTION)
    result = await client.get_active_wildfires(
        status="Out of Control", fire_year=2026, min_size_hectares=10
    )
    request = httpx_mock.get_requests()[0]
    cql = request.url.params["CQL_FILTER"]
    assert "FIRE_STATUS='Out of Control'" in cql
    assert "<>'Out'" not in cql  # an explicit status replaces the default
    assert "FIRE_YEAR=2026" in cql
    assert "FIRE_SIZE_HECTARES>=10" in cql
    # The provenance URL is the request actually sent, filters included.
    assert result.provenance.url == str(request.url)


async def test_get_active_wildfires_include_geometry_omits_property_name(httpx_mock):
    httpx_mock.add_response(json=_WILDFIRE_COLLECTION)
    await client.get_active_wildfires(include_geometry=True)
    request = httpx_mock.get_requests()[0]
    assert "propertyName" not in request.url.params
    assert request.url.params["srsName"] == constants.DEFAULT_SRS


async def test_get_active_wildfires_invalid_limit_raises():
    with pytest.raises(InvalidInput):
        await client.get_active_wildfires(limit=0)
    with pytest.raises(InvalidInput):
        await client.get_active_wildfires(offset=-1)


async def test_get_mining_tenure_parses_records(httpx_mock):
    httpx_mock.add_response(json=_TENURE_COLLECTION)
    result = await client.get_mining_tenure()
    assert result.returned_count == 1
    assert result.total_matched == 42282
    tenure = result.tenures[0]
    assert tenure.tenure_number_id == 217457
    assert tenure.claim_name == "NORSE #6"
    assert tenure.owner_name == "TECK HIGHLAND VALLEY COPPER CORPORATION"
    assert tenure.issue_date is not None
    assert tenure.issue_date.isoformat() == "1985-06-27"
    assert tenure.termination_date is None


async def test_get_mining_tenure_builds_cql_and_uppercases_owner(httpx_mock):
    httpx_mock.add_response(json=_TENURE_COLLECTION)
    await client.get_mining_tenure(tenure_type="mineral", owner_name="teck", min_area_hectares=100)
    request = httpx_mock.get_requests()[0]
    cql = request.url.params["CQL_FILTER"]
    assert "TENURE_TYPE_CODE='M'" in cql
    # Word starts only: '%TECK%' also matched individuals like "BIATECKI, ...".
    assert (
        "(OWNER_NAME LIKE 'TECK%' OR OWNER_NAME LIKE '% TECK%' OR OWNER_NAME LIKE '%(TECK%')" in cql
    )
    assert "'%TECK%'" not in cql
    assert "AREA_IN_HECTARES>=100" in cql


async def test_get_mining_tenure_invalid_tenure_type_raises():
    with pytest.raises(InvalidInput):
        await client.get_mining_tenure(tenure_type="not-a-type")


async def test_get_mining_tenure_escapes_single_quotes_in_owner_name(httpx_mock):
    httpx_mock.add_response(json=_TENURE_COLLECTION)
    await client.get_mining_tenure(owner_name="o'brien")
    request = httpx_mock.get_requests()[0]
    cql = request.url.params["CQL_FILTER"]
    assert "O''BRIEN" in cql


# Shape of BCGW's DescribeFeatureType JSON answer, live 2026-10-03 (abridged).
_TENURE_DESCRIBE = {
    "elementFormDefault": "qualified",
    "targetPrefix": "pub",
    "featureTypes": [
        {
            "typeName": "WHSE_MINERAL_TENURE.MTA_ACQUIRED_TENURE_SVW",
            "properties": [
                {"name": "TENURE_NUMBER_ID", "type": "xsd:number", "localType": "number"},
                {"name": "CLAIM_NAME", "type": "xsd:string", "localType": "string"},
                {"name": "ISSUE_DATE", "type": "xsd:date", "localType": "date"},
                {"name": "GEOMETRY", "type": "gml:Geometry", "localType": "Geometry"},
                {"name": "OBJECTID", "type": "xsd:number", "localType": "number"},
            ],
        }
    ],
}


def _is_describe(request) -> bool:
    return request.url.params.get("request") == "DescribeFeatureType"


async def test_query_layer_generic_layer_asks_only_for_attribute_fields(httpx_mock):
    httpx_mock.add_response(
        url=constants.BASE_URL,
        match_params={
            "service": "WFS",
            "version": "2.0.0",
            "request": "DescribeFeatureType",
            "typeName": constants.MINING_TENURE_TYPE_NAME,
            "outputFormat": "application/json",
        },
        json=_TENURE_DESCRIBE,
    )
    httpx_mock.add_response(json=_TENURE_COLLECTION, is_reusable=True)
    result = await client.query_layer(constants.MINING_TENURE_TYPE_NAME)
    assert result.type_name == constants.MINING_TENURE_TYPE_NAME
    assert result.returned_count == 1
    assert result.records[0]["TENURE_NUMBER_ID"] == 217457
    get_feature = next(r for r in httpx_mock.get_requests() if not _is_describe(r))
    # No geometry field asked for, so the server sends no polygons.
    assert get_feature.url.params["propertyName"] == (
        "TENURE_NUMBER_ID,CLAIM_NAME,ISSUE_DATE,OBJECTID"
    )
    assert "srsName" not in get_feature.url.params
    # The field list is cached: a second page asks DescribeFeatureType no more.
    await client.query_layer(constants.MINING_TENURE_TYPE_NAME, offset=20)
    assert sum(_is_describe(r) for r in httpx_mock.get_requests()) == 1


async def test_query_layer_include_geometry_reprojects(httpx_mock):
    httpx_mock.add_response(json=_TENURE_COLLECTION)
    await client.query_layer(constants.MINING_TENURE_TYPE_NAME, include_geometry=True)
    request = httpx_mock.get_requests()[0]
    assert request.url.params["srsName"] == constants.DEFAULT_SRS
    assert "propertyName" not in request.url.params
    assert len(httpx_mock.get_requests()) == 1  # no DescribeFeatureType needed


# DescribeFeatureType (outputFormat=application/json) for the fire points
# layer, trimmed from the live answer of 2026-10-03.
_FIRE_POINTS = "WHSE_LAND_AND_NATURAL_RESOURCE.PROT_CURRENT_FIRE_PNTS_SP"
_DESCRIBE = {
    "elementFormDefault": "qualified",
    "targetNamespace": "http://delivery.openmaps.gov.bc.ca/pub",
    "targetPrefix": "pub",
    "featureTypes": [
        {
            "typeName": _FIRE_POINTS,
            "properties": [
                {"name": "FIRE_NUMBER", "nillable": False, "type": "xsd:string"},
                {"name": "FIRE_YEAR", "nillable": False, "type": "xsd:number"},
                {
                    "name": "SHAPE",
                    "nillable": True,
                    "type": "gml:Geometry",
                    "localType": "Geometry",
                },
                {"name": "OBJECTID", "nillable": False, "type": "xsd:number"},
            ],
        }
    ],
}
_FIRE_POINT = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "id": f"{_FIRE_POINTS}.G80405",
            "geometry": {"type": "Point", "coordinates": [-121.752716, 57.3919]},
            "geometry_name": "SHAPE",
            "properties": {"FIRE_NUMBER": "G80405", "FIRE_YEAR": 2026, "OBJECTID": 87211955},
        }
    ],
    "totalFeatures": 1441,
    "numberMatched": 1441,
}


async def test_query_layer_geometry_survives_property_names(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r".*request=DescribeFeatureType.*"), json=_DESCRIBE, is_reusable=True
    )
    httpx_mock.add_response(url=re.compile(r".*request=GetFeature.*"), json=_FIRE_POINT)
    result = await client.query_layer(
        _FIRE_POINTS, include_geometry=True, property_names="FIRE_NUMBER"
    )
    get_feature = httpx_mock.get_requests()[-1]
    # Without SHAPE in propertyName every record came back "geometry": null.
    assert get_feature.url.params["propertyName"] == "FIRE_NUMBER,SHAPE"
    assert result.records[0]["geometry"] == {"type": "Point", "coordinates": [-121.752716, 57.3919]}


async def test_query_layer_geometry_column_already_listed(httpx_mock):
    httpx_mock.add_response(url=re.compile(r".*request=DescribeFeatureType.*"), json=_DESCRIBE)
    httpx_mock.add_response(url=re.compile(r".*request=GetFeature.*"), json=_FIRE_POINT)
    await client.query_layer(_FIRE_POINTS, include_geometry=True, property_names="shape,FIRE_YEAR")
    assert httpx_mock.get_requests()[-1].url.params["propertyName"] == "shape,FIRE_YEAR"


async def test_query_layer_geometry_on_unknown_layer_raises(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r".*request=DescribeFeatureType.*"),
        status_code=400,
        text="<ows:ExceptionReport/>",
    )
    with pytest.raises(InvalidInput, match="NOPE.NOPE: rejected the request"):
        await client.query_layer("NOPE.NOPE", include_geometry=True, property_names="X")


async def test_query_layer_empty_type_name_raises():
    with pytest.raises(InvalidInput):
        await client.query_layer("  ")


async def test_query_layer_passes_through_cql_and_sort(httpx_mock):
    httpx_mock.add_response(json={"features": [], "totalFeatures": 0, "numberMatched": 0})
    await client.query_layer("WHSE_FOO.BAR", cql_filter="X > 1", property_names="X,Y", sort_by="X")
    request = httpx_mock.get_requests()[0]
    assert request.url.params["CQL_FILTER"] == "X > 1"
    assert request.url.params["propertyName"] == "X,Y"
    assert request.url.params["sortBy"] == "X"


# French (lang="fr"): errors, provenance text and licence; English unchanged.


async def test_french_wildfire_provenance_and_licence(httpx_mock):
    httpx_mock.add_response(json=_WILDFIRE_COLLECTION)
    result = await client.get_active_wildfires(lang="fr")
    assert result.provenance.coverage == "1 feux renvoyés sur 304 correspondants"
    assert "saison des feux" in (result.provenance.freshness or "")
    assert "Licence du gouvernement ouvert – Colombie-Britannique" in (
        result.provenance.licence or ""
    )


async def test_english_wildfire_provenance_unchanged(httpx_mock):
    httpx_mock.add_response(json=_WILDFIRE_COLLECTION)
    result = await client.get_active_wildfires()
    assert result.provenance.coverage == "1 of 304 total matching fires returned"
    assert (result.provenance.licence or "").startswith("Open Government Licence - British")


async def test_french_invalid_limit_and_tenure_type():
    with pytest.raises(InvalidInput, match="Entrée invalide : limit doit être compris"):
        await client.get_active_wildfires(limit=0, lang="fr")
    with pytest.raises(InvalidInput, match="tenure_type doit valoir"):
        await client.get_mining_tenure(tenure_type="coal", lang="fr")
    with pytest.raises(InvalidInput, match="type_name ne doit pas être vide"):
        await client.query_layer("  ", lang="fr")


# query_layer with geometry: fewer rows per call, a byte budget on the returned
# polygons (trimmed before the result is cached), and a cap on what is read.
# The geometry request is the one asking for GEOMETRY_ROWS_MAX rows; the
# attribute-only probe that follows a failure asks for one row of OBJECTID.

_GEOMETRY_REQUEST = re.compile(rf".*count={constants.GEOMETRY_ROWS_MAX}&.*")
_PROBE_REQUEST = re.compile(r".*propertyName=OBJECTID.*")


class _EndlessBody(httpx.AsyncByteStream):
    """A body with no Content-Length that never ends: only a capped reader returns."""

    def __init__(self, chunk: int = 1024) -> None:
        self.chunk = chunk
        self.sent = 0

    async def __aiter__(self):
        while True:
            self.sent += self.chunk
            yield b"x" * self.chunk


async def test_query_layer_geometry_requests_fewer_rows(httpx_mock):
    httpx_mock.add_response(json=_TENURE_COLLECTION)
    result = await client.query_layer(
        constants.MINING_TENURE_TYPE_NAME, include_geometry=True, limit=1000
    )
    request = httpx_mock.get_requests()[0]
    assert request.url.params["count"] == str(constants.GEOMETRY_ROWS_MAX)
    assert result.limit == constants.GEOMETRY_ROWS_MAX
    assert result.note is not None and "at most 25 features" in result.note
    assert f"offset={result.returned_count}" in result.note


async def test_query_layer_without_geometry_keeps_the_full_row_limit(httpx_mock):
    httpx_mock.add_response(json={"features": [], "numberMatched": 0})
    result = await client.query_layer("WHSE_FOO.BAR", property_names="X", limit=1000)
    assert httpx_mock.get_requests()[0].url.params["count"] == "1000"
    assert result.limit == 1000 and result.note is None and result.geometry_omitted == 0


async def test_query_layer_geometry_is_trimmed_before_it_is_cached(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "GEOMETRY_BYTES_MAX", 200)
    ring = [[-120.0 + i / 100, 55.0] for i in range(8)]
    small = {"type": "Polygon", "coordinates": [ring]}
    large = {"type": "Polygon", "coordinates": [ring * 3]}
    properties = {"OBJECTID": 1}
    httpx_mock.add_response(
        json={
            "features": [
                {"type": "Feature", "geometry": small, "properties": properties},
                {"type": "Feature", "geometry": large, "properties": properties},
            ],
            "numberMatched": 2,
        }
    )
    result = await client.query_layer("WHSE_FOO.BAR", include_geometry=True, limit=2)
    assert [r["geometry"] for r in result.records] == [small, None]
    assert result.geometry_omitted == 1
    assert result.note is not None and "1 geometry(ies) left out" in result.note
    # What the cache holds is the trimmed body, not the polygon that was dropped.
    key = "bcgw:layer:WHSE_FOO.BAR:None:None:True:None:2:0"

    async def not_called():
        raise AssertionError("the query should have been cached")

    stored, was_cached = await cached_fetch(key, constants.CACHE_TTL_GENERIC_SECONDS, not_called)
    assert was_cached
    assert [f["geometry"] for f in stored["features"]] == [small, None]
    again = await client.query_layer("WHSE_FOO.BAR", include_geometry=True, limit=2)
    assert again.geometry_omitted == 1 and again.provenance.cached
    assert len(httpx_mock.get_requests()) == 1


async def test_query_layer_geometry_note_in_french(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "GEOMETRY_BYTES_MAX", 10)
    feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-121.752716, 57.3919]},
        "properties": {"OBJECTID": 1},
    }
    httpx_mock.add_response(json={"features": [feature], "numberMatched": 1})
    result = await client.query_layer("WHSE_FOO.BAR", include_geometry=True, lang="fr")
    assert result.geometry_omitted == 1
    assert result.note is not None and "géométrie(s) omise(s)" in result.note


async def test_query_layer_geometry_response_over_the_cap_stops_the_read(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "GEOMETRY_RESPONSE_BYTES_MAX", 2 * 1024 * 1024)
    body = _EndlessBody()
    httpx_mock.add_response(url=_GEOMETRY_REQUEST, stream=body)
    httpx_mock.add_response(url=_PROBE_REQUEST, json={"features": [], "numberMatched": 0})
    with pytest.raises(UpstreamError, match=r"over the 2 MB response limit.*limit=1"):
        await client.query_layer(
            "WHSE_FOO.BAR", include_geometry=True, limit=constants.GEOMETRY_ROWS_MAX
        )
    assert body.sent < 2 * 1024 * 1024 + 4 * body.chunk


async def test_query_layer_geometry_response_declared_over_the_cap_is_refused(
    httpx_mock, monkeypatch
):
    monkeypatch.setattr(constants, "GEOMETRY_RESPONSE_BYTES_MAX", 1024 * 1024)
    httpx_mock.add_response(url=_GEOMETRY_REQUEST, content=b"x" * (2 * 1024 * 1024))
    httpx_mock.add_response(url=_PROBE_REQUEST, json={"features": [], "numberMatched": 0})
    with pytest.raises(UpstreamError, match="response limit"):
        await client.query_layer(
            "WHSE_FOO.BAR", include_geometry=True, limit=constants.GEOMETRY_ROWS_MAX, lang="en"
        )


async def test_query_layer_geometry_over_the_cap_in_french(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "GEOMETRY_RESPONSE_BYTES_MAX", 1024 * 1024)
    httpx_mock.add_response(url=_GEOMETRY_REQUEST, stream=_EndlessBody())
    httpx_mock.add_response(url=_PROBE_REQUEST, json={"features": [], "numberMatched": 0})
    with pytest.raises(UpstreamError, match="dépasse la limite de 1 Mo"):
        await client.query_layer(
            "WHSE_FOO.BAR", include_geometry=True, limit=constants.GEOMETRY_ROWS_MAX, lang="fr"
        )


async def test_query_layer_geometry_request_the_service_rejects_is_invalid_input(httpx_mock):
    # The streaming reader reports a 400 as an upstream error; the follow-up
    # attribute-only probe recovers the service's own reason for the caller.
    report = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1" version="2.0.0">'
        b'<ows:Exception exceptionCode="NoApplicableCode">'
        b"<ows:ExceptionText>Could not parse CQL filter list.</ows:ExceptionText>"
        b"</ows:Exception></ows:ExceptionReport>"
    )
    headers = {"Content-Type": "application/xml"}
    httpx_mock.add_response(url=_GEOMETRY_REQUEST, status_code=400, content=report, headers=headers)
    httpx_mock.add_response(url=_PROBE_REQUEST, status_code=400, content=report, headers=headers)
    with pytest.raises(InvalidInput, match="Could not parse CQL filter list"):
        await client.query_layer(
            "WHSE_FOO.BAR",
            cql_filter="garbage===",
            include_geometry=True,
            limit=constants.GEOMETRY_ROWS_MAX,
        )
