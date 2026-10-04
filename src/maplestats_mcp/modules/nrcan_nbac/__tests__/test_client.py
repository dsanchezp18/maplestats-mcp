from __future__ import annotations

import pytest

from maplestats_mcp.modules.nrcan_nbac import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_REAL_LATEST_YEAR = client.latest_year


@pytest.fixture(autouse=True)
def _latest_year(monkeypatch):
    # Every query also looks up the latest fire year (one cached request),
    # tested on its own below through _REAL_LATEST_YEAR.
    async def fake() -> int:
        return 2024

    monkeypatch.setattr(client, "latest_year", fake)


_FEATURE = {
    "type": "Feature",
    "id": "nbac.6024",
    "geometry": None,
    "properties": {
        "year": 2021,
        "nfireid": 1233,
        "basrc": "MAFiMS",
        "firecaus": "Natural",
        "hs_sdate": "2021-07-10Z",
        "hs_edate": "2021-08-01Z",
        "ag_sdate": None,
        "ag_edate": None,
        "capdate": "2021-09-01Z",
        "poly_ha": 16628.434568,
        "adj_ha": 16628.434568,
        "adj_flag": None,
        "admin_area": "BC",
        "natpark": None,
        "prescribed": None,
        "version": "20220101",
    },
}

_FEATURE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [_FEATURE],
    "totalFeatures": 431,
    "numberMatched": 431,
    "numberReturned": 1,
}


async def test_query_fires_parses_records(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}?service=WFS&version=2.0.0&request=GetFeature"
            f"&typeName={constants.TYPE_NAME}&outputFormat=application%2Fjson"
            f"&count=20&startIndex=0&propertyName={constants.ATTRIBUTE_FIELDS}"
            f"&srsName={constants.DEFAULT_SRS}"
        ),
        json=_FEATURE_COLLECTION,
    )
    result = await client.query_fires()
    assert result.returned_count == 1
    assert result.total_matched == 431
    fire = result.fires[0]
    assert fire.year == 2021
    assert fire.fire_id == 1233
    assert fire.admin_area == "BC"
    assert fire.adjusted_area_ha == 16628.434568
    assert fire.hotspot_start_date is not None
    assert fire.hotspot_start_date.isoformat() == "2021-07-10"
    assert fire.agency_start_date is None
    assert fire.geometry is None


async def test_query_fires_with_cql_filter_passes_it_through(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}?service=WFS&version=2.0.0&request=GetFeature"
            f"&typeName={constants.TYPE_NAME}&outputFormat=application%2Fjson"
            "&count=20&startIndex=0"
            f"&propertyName={constants.ATTRIBUTE_FIELDS}&srsName={constants.DEFAULT_SRS}"
            "&CQL_FILTER=admin_area+%3D+%27BC%27+AND+year+%3E%3D+2017"
        ),
        json={"features": [], "totalFeatures": 0, "numberMatched": 0},
    )
    result = await client.query_fires(cql_filter="admin_area = 'BC' AND year >= 2017")
    assert result.returned_count == 0
    assert result.cql_filter == "admin_area = 'BC' AND year >= 2017"


async def test_query_fires_include_geometry_omits_property_name(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}?service=WFS&version=2.0.0&request=GetFeature"
            f"&typeName={constants.TYPE_NAME}&outputFormat=application%2Fjson"
            f"&count={constants.GEOMETRY_ROWS_MAX}&startIndex=0&srsName={constants.DEFAULT_SRS}"
        ),
        json=_FEATURE_COLLECTION,
    )
    # The default limit of 20 is clamped to the geometry row cap, with a note.
    result = await client.query_fires(include_geometry=True)
    assert result.returned_count == 1
    assert result.note is not None and "at most" in result.note


async def test_malformed_cql_filter_raises_invalid_input(httpx_mock):
    """Confirmed live: a malformed CQL_FILTER returns HTTP 400 with an
    OGC ows:ExceptionReport in XML, not JSON, regardless of the
    requested outputFormat."""
    httpx_mock.add_response(
        status_code=400,
        content=(
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1" version="2.0.0">'
            b'<ows:Exception exceptionCode="NoApplicableCode">'
            b"<ows:ExceptionText>Could not parse CQL filter list.</ows:ExceptionText>"
            b"</ows:Exception></ows:ExceptionReport>"
        ),
        headers={"Content-Type": "application/xml"},
    )
    with pytest.raises(InvalidInput, match="Could not parse CQL filter list"):
        await client.query_fires(cql_filter="garbage===")


async def test_invalid_input_rejects_bad_limit_and_offset():
    with pytest.raises(InvalidInput):
        await client.query_fires(limit=0)
    with pytest.raises(InvalidInput):
        await client.query_fires(offset=-1)


async def test_upstream_5xx_becomes_upstream_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(status_code=500, content=b"<html>Internal Server Error</html>")
    with pytest.raises(UpstreamError):
        await client.query_fires()


def _live_feature(fid: str, nfireid: int, **overrides: object) -> dict:
    props = {
        "year": 2023,
        "nfireid": nfireid,
        "basrc": "MAFiMS",
        "firemaps": "Sentinel-2",
        "firemapm": "Processed imagery",
        "firecaus": "Natural",
        "hs_sdate": "2023-05-29Z",
        "hs_edate": "2023-09-26Z",
        "ag_sdate": "2023-05-28Z",
        "ag_edate": None,
        "capdate": "2023-10-13Z",
        "poly_ha": 24608.9069782,
        "adj_ha": 24608.9069782,
        "adj_flag": None,
        "admin_area": "AB",
        "natpark": None,
        "prescribed": None,
        "version": "20250506",
        **overrides,
    }
    return {"type": "Feature", "id": fid, "geometry": None, "properties": props}


# Trimmed from a live GetFeature on 2026-10-03: BASE_URL with typeName=public:nbac,
# count=3, the ATTRIBUTE_FIELDS propertyName, srsName=EPSG:4326 and
# CQL_FILTER=admin_area = 'AB' AND year = 2023. Quirks kept: a GeoServer `links`
# "next page" entry, `crs: null`, a `timeStamp`, and `ag_edate` null even when
# `ag_sdate` is set.
_LIVE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [
        _live_feature(
            "nbac.2271",
            310,
            firemaps="Landsat",
            hs_sdate="2023-05-16Z",
            hs_edate="2023-12-06Z",
            ag_sdate="2023-05-11Z",
            capdate="2023-10-10Z",
            poly_ha=101336.906707,
            adj_ha=101336.906707,
        ),
        _live_feature("nbac.2280", 317),
        _live_feature(
            "nbac.2283",
            318,
            firecaus="Undetermined",
            hs_sdate="2023-06-30Z",
            hs_edate="2023-09-27Z",
            ag_sdate=None,
            poly_ha=114706.509308,
            adj_ha=114706.509308,
        ),
    ],
    "totalFeatures": 210,
    "numberMatched": 210,
    "numberReturned": 3,
    "timeStamp": "2026-10-03T17:26:55.538Z",
    "links": [
        {
            "title": "next page",
            "type": "application/json",
            "rel": "next",
            "href": "https://cwfis.cfs.nrcan.gc.ca/geoserver/wfs?TYPENAME=public%3Anbac&STARTINDEX=3",
        }
    ],
    "crs": None,
}


async def test_query_fires_parses_live_shaped_collection(httpx_mock):
    httpx_mock.add_response(json=_LIVE_COLLECTION)
    result = await client.query_fires(
        cql_filter="admin_area = 'AB' AND year = 2023", limit=3, sort_by="nfireid A"
    )
    assert [f.fire_id for f in result.fires] == [310, 317, 318]
    assert result.total_matched == 210
    first, _, third = result.fires
    assert first.agency_start_date is not None
    assert first.agency_start_date.isoformat() == "2023-05-11"
    assert first.agency_end_date is None
    assert first.hotspot_end_date is not None
    assert first.hotspot_end_date.isoformat() == "2023-12-06"
    assert third.fire_cause == "Undetermined"
    assert third.agency_start_date is None
    assert result.provenance.coverage == "3 of 210 total matching fires returned"
    params = httpx_mock.get_request().url.params
    assert params["sortBy"] == "nfireid A"
    assert params["count"] == "3"


async def test_query_fires_live_empty_result(httpx_mock):
    # Live answer to CQL_FILTER=year = 1800 on 2026-10-03.
    httpx_mock.add_response(
        json={
            "type": "FeatureCollection",
            "features": [],
            "totalFeatures": 0,
            "numberMatched": 0,
            "numberReturned": 0,
            "timeStamp": "2026-10-03T17:26:55.654Z",
            "crs": None,
        }
    )
    result = await client.query_fires(cql_filter="year = 1800")
    assert result.fires == []
    assert result.total_matched == 0
    assert result.returned_count == 0


async def test_null_features_and_missing_number_matched_fall_back(httpx_mock):
    # `features: null` must read as no rows; without numberMatched the total comes
    # from totalFeatures, and without either from the rows actually returned.
    httpx_mock.add_response(json={"features": None, "totalFeatures": 12})
    result = await client.query_fires(offset=40)
    assert result.fires == []
    assert result.total_matched == 12
    assert httpx_mock.get_request().url.params["startIndex"] == "40"

    cache_module._caches.clear()
    httpx_mock.add_response(json={"features": [_live_feature("nbac.1", 1)]})
    result = await client.query_fires(offset=40)
    assert result.total_matched == 1


async def test_unknown_field_exception_report_is_invalid_input(httpx_mock):
    # ExceptionReport served live on 2026-10-03 (HTTP 400, application/xml) for
    # propertyName=year,nosuchfield; an unknown sortBy field is rejected the same way.
    httpx_mock.add_response(
        status_code=400,
        headers={"Content-Type": "application/xml"},
        content=(
            b'<?xml version="1.0" encoding="UTF-8"?><ows:ExceptionReport '
            b'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
            b'xmlns:ows="http://www.opengis.net/ows/1.1" '
            b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.0.0">\n'
            b'  <ows:Exception exceptionCode="InvalidParameterValue" locator="GetFeature">\n'
            b"    <ows:ExceptionText>Requested property: nosuchfield is not available for "
            b"public:nbac.  The possible propertyName values are: [year, nfireid, basrc, "
            b"geometry]</ows:ExceptionText>\n"
            b"  </ows:Exception>\n</ows:ExceptionReport>\n"
        ),
    )
    with pytest.raises(InvalidInput, match="nosuchfield is not available"):
        await client.query_fires(sort_by="nosuchfield")


async def test_404_is_not_found(httpx_mock):
    httpx_mock.add_response(status_code=404, text="<html>HTTP Status 404 - Not Found</html>")
    with pytest.raises(NotFound):
        await client.query_fires()


async def test_latest_year_reads_the_newest_feature(httpx_mock):
    httpx_mock.add_response(
        json={"type": "FeatureCollection", "features": [{"properties": {"year": 2024}}]}
    )
    assert await _REAL_LATEST_YEAR() == 2024
    request = httpx_mock.get_requests()[0]
    assert "sortBy=year+D" in str(request.url) or "sortBy=year%20D" in str(request.url)


async def test_empty_result_names_the_latest_year(httpx_mock):
    httpx_mock.add_response(json={"type": "FeatureCollection", "features": [], "numberMatched": 0})
    result = await client.query_fires(cql_filter="year = 2025")
    assert result.latest_year == 2024
    assert result.note is not None and "2024" in result.note


async def test_french_notes_provenance_and_errors(httpx_mock):
    httpx_mock.add_response(json={"type": "FeatureCollection", "features": [], "numberMatched": 0})
    result = await client.query_fires(cql_filter="year = 2025", lang="fr")
    assert result.note is not None
    assert result.note.startswith("Aucun feu ne correspond ; le CNZB va actuellement")
    assert (result.provenance.coverage or "") == "0 feux renvoyés sur 0 correspondants"
    assert "dernière saison des feux : 2024" in (result.provenance.freshness or "")
    assert "Licence du gouvernement ouvert" in (result.provenance.licence or "")
    with pytest.raises(InvalidInput, match="^Entrée invalide : limit doit être compris"):
        await client.query_fires(limit=0, lang="fr")


async def test_geometry_limit_and_byte_budget(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "GEOMETRY_BYTES_MAX", 200)
    ring = [[-120.0 + i / 100, 55.0] for i in range(8)]
    small = {"type": "Polygon", "coordinates": [ring]}
    large = {"type": "Polygon", "coordinates": [ring * 3]}
    features = [
        {**_FEATURE, "geometry": small},
        {**_FEATURE, "geometry": large},
    ]
    httpx_mock.add_response(
        json={"type": "FeatureCollection", "features": features, "numberMatched": 2}
    )
    result = await client.query_fires(include_geometry=True, limit=2)
    assert result.fires[0].geometry == small
    assert result.fires[1].geometry is None
    assert result.geometry_omitted == 1
    assert result.note is not None
