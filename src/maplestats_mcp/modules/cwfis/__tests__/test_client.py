from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import pytest

from maplestats_mcp.modules.cwfis import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable

WFS = re.compile(re.escape(constants.WFS_URL) + r"\?.*")
SITREP = re.compile(re.escape(constants.SITREP_URL) + r".*")


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _collection(*props: dict, total: int | None = None) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": None, "properties": p} for p in props],
        "numberMatched": total if total is not None else len(props),
    }


def _query(request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}


async def test_hotspots_current_filters_canada_and_parses(httpx_mock):
    httpx_mock.add_response(
        url=WFS,
        json=_collection(
            {
                "lat": 50.1,
                "lon": -120.2,
                "rep_date": "2026-09-28T23:56:00Z",
                "agency": "BC",
                "sensor": "VIIRS-I",
                "satellite": "NOAA-21",
                "frp": 4.5,
                "fwi": 3.2,
                "fuel": "C2",
            },
            total=3,
        ),
    )
    result = await client.get_hotspots(limit=1)
    assert result.total_matched == 3
    hot = result.hotspots[0]
    assert (hot.agency, hot.fuel_type, hot.frp_mw) == ("BC", "C2", 4.5)
    assert hot.reported_at is not None and hot.reported_at.year == 2026
    query = _query(httpx_mock.get_requests()[0])
    assert query["typeName"] == constants.HOTSPOTS_CURRENT
    assert "agency IN ('BC'" in query["CQL_FILTER"]


async def test_hotspots_archive_needs_both_dates_and_uses_archive_layer(httpx_mock):
    with pytest.raises(InvalidInput, match="both start_date and end_date"):
        await client.get_hotspots(start_date="2023-08-01")
    httpx_mock.add_response(url=WFS, json=_collection())
    result = await client.get_hotspots(
        agency="bc", start_date="2023-08-01", end_date="2023-08-02", sort_by="frp"
    )
    assert result.layer == constants.HOTSPOTS_ARCHIVE
    query = _query(httpx_mock.get_requests()[0])
    cql = query["CQL_FILTER"]
    assert "agency = 'BC'" in cql
    assert "rep_date < '2023-08-03T00:00:00Z'" in cql
    # Live quirk: DESC sort puts NULL FRP first, so NULLs must be excluded.
    assert "frp IS NOT NULL" in cql
    assert query["sortBy"] == "frp D"


async def test_bbox_uses_explicit_crs(httpx_mock):
    httpx_mock.add_response(url=WFS, json=_collection())
    await client.get_perimeters(bbox=[-125, 48, -110, 60])
    cql = _query(httpx_mock.get_requests()[0])["CQL_FILTER"]
    assert cql == "BBOX(geometry,-125,48,-110,60,'EPSG:4326')"
    with pytest.raises(InvalidInput):
        await client.get_perimeters(bbox=[1, 2, 3])


async def test_stations_by_point_sorts_by_distance_and_maps_province(httpx_mock):
    httpx_mock.add_response(
        url=WFS,
        json=_collection(
            {"name": "  FAR  ", "prov": "SA", "lat": 50.3, "lon": -119.4, "fwi": 1.0},
            {"name": "NEAR", "prov": "BC", "lat": 49.95, "lon": -119.39, "fwi": 2.8},
            {"name": "OUTSIDE", "prov": "BC", "lat": 55.0, "lon": -119.4},
        ),
    )
    result = await client.get_stations(latitude=49.95, longitude=-119.4, radius_km=60)
    assert [s.name for s in result.stations] == ["NEAR", "FAR"]
    assert result.stations[1].province == "SK"  # SA is the layer's code for Saskatchewan
    assert result.stations[0].distance_km is not None and result.stations[0].distance_km < 2
    assert result.total_matched == 2


async def test_stations_province_translates_to_layer_code(httpx_mock):
    httpx_mock.add_response(url=WFS, json=_collection({"name": "X", "prov": "NF"}))
    result = await client.get_stations(province="nl")
    assert "prov = 'NF'" in _query(httpx_mock.get_requests()[0])["CQL_FILTER"]
    assert result.stations[0].province == "NL"


async def test_stations_requires_a_filter_and_valid_radius():
    with pytest.raises(InvalidInput):
        await client.get_stations()
    with pytest.raises(InvalidInput):
        await client.get_stations(latitude=50.0)
    with pytest.raises(InvalidInput):
        await client.get_stations(latitude=50.0, longitude=-119.0, radius_km=500)


async def test_forecast_not_found_when_empty(httpx_mock):
    httpx_mock.add_response(url=WFS, json=_collection())
    with pytest.raises(NotFound):
        await client.get_forecast(station_name="nowhere")


async def test_forecast_parses_rows(httpx_mock):
    httpx_mock.add_response(
        url=WFS,
        json=_collection(
            {"wmo": 71203, "name": "KELOWNA", "rep_date": "2026-09-29T12:00:00Z", "fwi": 2.2}
        ),
    )
    result = await client.get_forecast(station_name="kelow")
    assert result.forecasts[0].station_name == "KELOWNA"
    assert result.forecasts[0].fwi == 2.2


async def test_fire_danger_maps_gridcode_and_raises_off_grid(httpx_mock):
    httpx_mock.add_response(url=WFS, json=_collection({"GRIDCODE": 2}))
    result = await client.get_fire_danger(latitude=49.9, longitude=-119.4)
    assert result.danger_class == "High"
    cql = _query(httpx_mock.get_requests()[0])["CQL_FILTER"]
    assert cql == "INTERSECTS(the_geom, SRID=4326;POINT(-119.4 49.9))"
    httpx_mock.add_response(url=WFS, json=_collection())
    with pytest.raises(NotFound):
        await client.get_fire_danger(latitude=0.0, longitude=-30.0)


@pytest.mark.parametrize("props", [{"GRIDCODE": None}, {}])
async def test_fire_danger_null_or_missing_gridcode_is_unknown(httpx_mock, props):
    # GeoServer writes an absent attribute as "GRIDCODE": null in GeoJSON.
    httpx_mock.add_response(url=WFS, json=_collection(props))
    result = await client.get_fire_danger(latitude=49.9, longitude=-119.4)
    assert result.gridcode is None
    assert result.danger_class.startswith("Unknown")


async def test_large_fires_parse_and_filter(httpx_mock):
    httpx_mock.add_response(
        url=WFS,
        json=_collection(
            {
                "NFDBFIREID": "BC-2023-2023-G80280",
                "FIRE_ID": "2023-G80280",
                "FIRENAME": "2023 Holdover DONNIE CREEK",
                "SRC_AGENCY": "BC",
                "YEAR": 2023,
                "REP_DATE": "2023-05-12T00:00:00Z",
                "OUT_DATE": None,
                "SIZE_HA": 619072.5,
                "CAUSE": "N",
                "FIRE_TYPE": "",
            },
            total=7,
        ),
    )
    result = await client.search_large_fires(agency="bc", year_from=2023, min_size_ha=50000)
    fire = result.fires[0]
    assert (fire.cause, fire.size_ha, fire.fire_type) == ("Natural", 619072.5, None)
    assert fire.reported_date is not None and fire.reported_date.isoformat() == "2023-05-12"
    assert fire.out_date is None
    cql = _query(httpx_mock.get_requests()[0])["CQL_FILTER"]
    assert cql == "YEAR >= 2023 AND SRC_AGENCY = 'BC' AND SIZE_HA >= 50000.0"
    with pytest.raises(InvalidInput):
        await client.search_large_fires(cause="X")  # type: ignore[arg-type]


async def test_malformed_filter_becomes_invalid_input(httpx_mock):
    httpx_mock.add_response(
        url=WFS,
        status_code=400,
        content=(
            b'<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1" version="2.0.0">'
            b"<ows:Exception><ows:ExceptionText>bad filter</ows:ExceptionText>"
            b"</ows:Exception></ows:ExceptionReport>"
        ),
    )
    with pytest.raises(InvalidInput, match="bad filter"):
        await client.get_perimeters()


_STATS_ITEM = {
    "date": "2010-07-14",
    "type": "in_season",
    "uncontrolled": 24,
    "number_2004_to_date": 4237,
    "area_2004_to_date": 1637682,
    "synopsis_e": "English synopsis.",
    "synopsis_f": "Synopsis en français.",
    "wildfires_e": "",
}


async def test_list_situation_reports_parses_stats(httpx_mock):
    httpx_mock.add_response(
        url=SITREP, json={"items": [_STATS_ITEM], "total": 573, "limit": 1, "offset": 0}
    )
    result = await client.list_situation_reports(limit=1)
    assert result.total_matched == 573
    assert result.reports[0].stats.area_to_date_ha == 1637682
    assert result.reports[0].stats.fires_10yr_avg is None
    query = _query(httpx_mock.get_requests()[0])
    assert query["limit"] == "1"


async def test_situation_report_limit_capped_at_100():
    with pytest.raises(InvalidInput, match="between 1 and 100"):
        await client.list_situation_reports(limit=101)


async def test_get_situation_report_language_and_empty_sections(httpx_mock):
    httpx_mock.add_response(url=SITREP, json=_STATS_ITEM)
    result = await client.get_situation_report(date_on_or_before="2010-07-14", lang="fr")
    assert [s.heading for s in result.sections] == ["Synopsis"]
    assert result.sections[0].text == "Synopsis en français."
    assert result.language == "fr"
    assert "/by-date" in str(httpx_mock.get_requests()[0].url)
    assert _query(httpx_mock.get_requests()[0])["date"] == "2010-07-14"


async def test_situation_report_before_1998_is_not_found(httpx_mock):
    httpx_mock.add_response(url=SITREP, status_code=404, json={"detail": "Item not found"})
    with pytest.raises(NotFound, match="1998"):
        await client.get_situation_report(date_on_or_before="1990-01-01")


async def test_end_of_season_report_uses_its_own_sections(httpx_mock):
    item = {
        "date": "2025-11-19",
        "type": "end_of_season",
        "human_impacts_e": "Seasonal Summary: text",
        "weather_in_review_e": "Weather text",
    }
    httpx_mock.add_response(url=SITREP, json={"items": [item], "total": 28})
    result = await client.get_situation_report(report_type="end_of_season")
    assert [s.heading for s in result.sections] == ["Human impacts", "Weather in review"]
    assert result.stats.area_to_date_ha is None


async def test_sitrep_server_error_is_upstream_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(url=SITREP, status_code=500, content=b"boom")
    with pytest.raises(UpstreamError):
        await client.list_situation_reports()


# ------------------------------------------------------- live-shaped bodies

# Trimmed from live responses captured 2026-10-03 with the client's own query
# parameters (service=WFS, version=2.0.0, outputFormat=application/json,
# srsName=EPSG:4326, count=2): only the first features are kept.

# GET https://cwfis.cfs.nrcan.gc.ca/geoserver/ows?typeName=public:hotspots_last24hrs
#     &propertyName=<_HOTSPOT_FIELDS>&sortBy=rep_date D
# Notes: features carry an `id`; geometry is null because propertyName leaves it
# out; `estarea` is null; `fuel` can be a non-FBP code ("farm"); `hfi` is an
# integer; `crs` is null and a `links` next-page entry is present.
_LIVE_HOTSPOTS = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "id": "hotspots_last24hrs.32380094",
            "geometry": None,
            "properties": {
                "lat": 56.50446,
                "lon": -117.18266,
                "rep_date": "2026-10-03T12:02:00Z",
                "source": "NASA_w",
                "sensor": "VIIRS-I",
                "satellite": "NOAA-20",
                "agency": "AB",
                "ffmc": 86.201,
                "isi": 3.663,
                "bui": 27.88,
                "fwi": 7.28,
                "fuel": "farm",
                "hfi": 331,
                "frp": 6.63,
                "estarea": None,
            },
        }
    ],
    "totalFeatures": 1213,
    "numberMatched": 1213,
    "numberReturned": 1,
    "timeStamp": "2026-10-03T17:26:51.724Z",
    "links": [{"title": "next page", "type": "application/json", "rel": "next", "href": "x"}],
    "crs": None,
}

# GET ...?typeName=public:firewx_stns_current&CQL_FILTER=prov = 'AB'
#     &propertyName=<_STATION_FIELDS>&sortBy=name
# `name` is padded with 36 trailing spaces and `agency` with 3; `aes` is a
# string while `wmo` is an integer; zero FWI values are real zeros.
_LIVE_STATION = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "id": "firewx_stns_current.fid-74596f82_1a102cd3d4d_-6fad",
            "geometry": None,
            "properties": {
                "aes": "8200604",
                "wmo": 71988,
                "name": "Duck Lake AGCM" + " " * 36,
                "rep_date": "2026-10-03T12:00:00Z",
                "agency": "MSC   ",
                "prov": "AB",
                "lat": 54.6864,
                "lon": -113.9389,
                "elev": 650,
                "temp": 13.4,
                "rh": 84,
                "ws": 21.7,
                "wdir": 320,
                "precip": 4.7,
                "ffmc": 39.4,
                "dmc": 0.4,
                "dc": 167.4,
                "bui": 0.7,
                "isi": 0.1,
                "fwi": 0,
                "dsr": 0,
            },
        }
    ],
    "totalFeatures": 1,
    "numberMatched": 1,
    "numberReturned": 1,
    "timeStamp": "2026-10-03T17:26:52.805Z",
    "crs": None,
}

# GET ...?typeName=public:NFDB_point&CQL_FILTER=YEAR >= 2023 AND SRC_AGENCY = 'AB'
#     &propertyName=<_NFDB_FIELDS>&sortBy=SIZE_HA D
# Blank text fields are "" (not null), OUT_DATE is null and SIZE_HA an integer.
_LIVE_NFDB = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "id": "NFDB_point.15178",
            "geometry": None,
            "properties": {
                "NFDBFIREID": "AB-2023-HWF058",
                "SRC_AGENCY": "AB",
                "NAT_PARK": "",
                "FIRE_ID": "HWF058",
                "FIRENAME": "Basset Fire",
                "LATITUDE": 58.16715,
                "LONGITUDE": -118.41965,
                "YEAR": 2023,
                "REP_DATE": "2023-06-04T00:00:00Z",
                "OUT_DATE": None,
                "SIZE_HA": 234061,
                "CAUSE": "N",
                "FIRE_TYPE": "Crown",
                "RESPONSE": "",
            },
        }
    ],
    "totalFeatures": 71,
    "numberMatched": 71,
    "numberReturned": 1,
    "crs": None,
}

# GET https://api.cwfif.nrcan.gc.ca/situationreports/situationreport
#     ?limit=2&offset=0&start_date=2010-07-01 (first item, French text cut short).
# From 2024 every numeric total is null; the narrative carries them instead. The
# item also has fields the client does not map (id, date_insert, being_held_fires).
_LIVE_SITREP_2026 = {
    "id": 583,
    "date": "2026-09-16",
    "date_insert": "2026-09-18",
    "date_day": 16,
    "date_month": 9,
    "date_year": 2026,
    "uncontrolled": None,
    "controlled": None,
    "being_held_fires": None,
    "modified_response": None,
    "number_2004_to_date": None,
    "number_10yr_avg": None,
    "number_p100_normal": None,
    "number_prescribed": None,
    "number_us": None,
    "area_2004_to_date": None,
    "area_10yr_avg": None,
    "area_p100_normal": None,
    "area_prescribed": None,
    "area_us": None,
    "type": "in_season",
    "synopsis_e": "This will be the last national situation report for 2026. ",
    "prognosis_e": "Weekly national situation reporting will resume in the spring of 2027. ",
    "priority_fires_e": "There are currently no priority fires.  ",
    "interagency_mobilization_e": "Canada is at National Preparedness Level 2.\n\n \n\nThe end.",
    "wildfires_e": "",
    "synopsis_f": "Il s’agit du dernier rapport sur la situation nationale pour 2026. ",
    "wildfires_f": "",
}

# GET ...?typeName=public:no_such_layer answered HTTP 400 with this XML.
_LIVE_UNKNOWN_TYPE = (
    b'<?xml version="1.0" encoding="UTF-8"?><ows:ExceptionReport '
    b'xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:ows="http://www.opengis.net/ows/1.1" '
    b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.0.0">\n'
    b'  <ows:Exception exceptionCode="InvalidParameterValue" locator="typeName">\n'
    b"    <ows:ExceptionText>Feature type public:no_such_layer unknown</ows:ExceptionText>\n"
    b"  </ows:Exception>\n</ows:ExceptionReport>\n"
)


async def test_live_shaped_hotspots_parse_nulls_and_counts(httpx_mock):
    httpx_mock.add_response(url=WFS, json=_LIVE_HOTSPOTS)
    result = await client.get_hotspots(limit=1)
    hot = result.hotspots[0]
    assert (hot.latitude, hot.longitude) == (56.50446, -117.18266)
    assert hot.reported_at is not None
    assert hot.reported_at.isoformat() == "2026-10-03T12:02:00+00:00"
    assert hot.estimated_area is None
    assert hot.fuel_type == "farm"
    assert hot.head_fire_intensity == 331.0
    assert result.total_matched == 1213


async def test_live_shaped_station_strips_padding_and_keeps_zeros(httpx_mock):
    httpx_mock.add_response(url=WFS, json=_LIVE_STATION)
    result = await client.get_stations(province="ab")
    station = result.stations[0]
    assert station.name == "Duck Lake AGCM"
    assert station.agency == "MSC"
    assert (station.province, station.wmo, station.aes) == ("AB", 71988, "8200604")
    assert (station.fwi, station.dsr) == (0.0, 0.0)  # real zeros, not missing values
    assert station.observed_at is not None
    assert station.observed_at.isoformat() == "2026-10-03T12:00:00+00:00"


async def test_live_shaped_nfdb_blank_strings_become_none(httpx_mock):
    httpx_mock.add_response(url=WFS, json=_LIVE_NFDB)
    result = await client.search_large_fires(agency="ab", year_from=2023)
    fire = result.fires[0]
    assert (fire.national_park, fire.response, fire.out_date) == (None, None, None)
    assert (fire.cause, fire.fire_type, fire.size_ha) == ("Natural", "Crown", 234061.0)
    assert fire.reported_date is not None
    assert fire.reported_date.isoformat() == "2023-06-04"
    assert result.total_matched == 71


async def test_live_shaped_2026_sitrep_has_null_totals_and_trimmed_text(httpx_mock):
    httpx_mock.add_response(
        url=SITREP, json={"items": [_LIVE_SITREP_2026], "total": 583, "limit": 1, "offset": 0}
    )
    listed = await client.list_situation_reports(limit=1, start_date="2010-07-01")
    summary = listed.reports[0]
    assert summary.report_date.isoformat() == "2026-09-16"
    assert all(value is None for value in summary.stats.model_dump().values())

    httpx_mock.add_response(url=SITREP, json=_LIVE_SITREP_2026)
    report = await client.get_situation_report()
    # wildfires_e is "", so it is dropped; trailing spaces are trimmed.
    assert [s.heading for s in report.sections] == [
        "Synopsis",
        "Prognosis",
        "Priority fires",
        "Interagency mobilization",
    ]
    assert report.sections[2].text == "There are currently no priority fires."


# ------------------------------------------------------------ error paths


async def test_unknown_layer_exception_report_is_invalid_input(httpx_mock):
    httpx_mock.add_response(
        url=WFS,
        status_code=400,
        headers={"Content-Type": "application/xml"},
        content=_LIVE_UNKNOWN_TYPE,
    )
    with pytest.raises(InvalidInput, match="Feature type public:no_such_layer unknown"):
        await client.get_perimeters()
    assert len(httpx_mock.get_requests()) == 1  # a 400 is not retried


@pytest.mark.parametrize(
    "content_type, body",
    [
        # GeoServer's WFS 1.x-style error: HTTP 200 with an XML exception report.
        (
            "application/vnd.ogc.se_xml",
            (
                b'<?xml version="1.0" ?><ServiceExceptionReport version="1.2.0" '
                b'xmlns="http://www.opengis.net/ogc"><ServiceException code="InvalidParameterValue">'
                b"Illegal property name: nope</ServiceException></ServiceExceptionReport>"
            ),
        ),
        ("text/html", b"<html><body><h1>503 Service Temporarily Unavailable</h1></body></html>"),
        ("application/json", b'{"type": "FeatureCollection", "features": ['),
    ],
)
async def test_non_json_body_with_http_200_is_a_typed_error(httpx_mock, content_type, body):
    httpx_mock.add_response(url=WFS, headers={"Content-Type": content_type}, content=body)
    # shared/wfs.py reports an undecodable body as UpstreamUnavailable; what
    # matters here is that no raw httpx/JSON/XML exception reaches the tool layer.
    with pytest.raises((UpstreamError, UpstreamUnavailable)):
        await client.get_hotspots()


@pytest.mark.parametrize(
    "status",
    [
        500,
        502,
        503,
    ],
)
async def test_wfs_transient_status_is_retried_three_times_then_upstream_error(httpx_mock, status):
    httpx_mock.add_response(url=WFS, status_code=status, content=b"busy", is_reusable=True)
    with pytest.raises(UpstreamError, match=f"HTTP {status}"):
        await client.search_large_fires()
    assert len(httpx_mock.get_requests()) == 3


async def test_wfs_429_after_retries_is_unavailable_not_a_caller_error(httpx_mock):
    httpx_mock.add_response(url=WFS, status_code=429, content=b"busy", is_reusable=True)
    with pytest.raises(UpstreamUnavailable):
        await client.search_large_fires()


async def test_null_features_properties_and_counts_are_empty_not_errors(httpx_mock):
    # `"features": null` with no count at all: an empty page, total 0.
    httpx_mock.add_response(url=WFS, json={"type": "FeatureCollection", "features": None})
    empty = await client.get_perimeters()
    assert (empty.perimeters, empty.total_matched) == ([], 0)

    # `"properties": null`, and numberMatched absent so totalFeatures is used.
    httpx_mock.add_response(
        url=WFS,
        json={"features": [{"type": "Feature", "properties": None}], "totalFeatures": 9},
    )
    result = await client.get_perimeters(min_area_ha=10)
    assert result.perimeters[0].area is None
    assert result.total_matched == 9


async def test_sitrep_rejection_and_garbled_body_are_typed(httpx_mock):
    # The API is FastAPI: a rejected parameter is HTTP 422 with a `detail` list.
    httpx_mock.add_response(
        url=SITREP,
        status_code=422,
        json={"detail": [{"loc": ["query", "start_date"], "msg": "Input should be a valid date"}]},
    )
    with pytest.raises(InvalidInput, match="valid date"):
        await client.list_situation_reports(start_date="2010-07-01")

    httpx_mock.add_response(url=SITREP, headers={"Content-Type": "text/html"}, text="<html>")
    with pytest.raises((UpstreamError, UpstreamUnavailable)):
        await client.list_situation_reports(start_date="2011-07-01")


@pytest.mark.parametrize(
    "call",
    [
        lambda: client.get_hotspots(sort_by="hottest"),
        lambda: client.get_hotspots(start_date="2023-08-01", end_date="2023/08/02"),
        lambda: client.get_hotspots(bbox=[10, 50, -10, 60]),
        lambda: client.get_hotspots(limit=1001),
        lambda: client.get_forecast(station_name="   "),
        lambda: client.get_fire_danger(latitude=91.0, longitude=0.0),
        lambda: client.search_large_fires(sort_by="name"),
        lambda: client.list_situation_reports(report_type="weekly"),
        lambda: client.get_situation_report(report_type="weekly"),
    ],
)
async def test_invalid_arguments_fail_before_any_request(httpx_mock, call):
    with pytest.raises(InvalidInput):
        await call()
    assert httpx_mock.get_requests() == []
