from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import pytest

from maplestats_mcp.modules.cwfis import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

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
