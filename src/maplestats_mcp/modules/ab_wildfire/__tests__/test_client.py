"""Tests for ab_wildfire/client.py, shaped around quirks confirmed live
2026-10-02 (see the package docstring): the "Assisstance Ended" typo in the
previous-five-years layer, string status dates, null causes on mutual-aid
fires, GeoJSON perimeters, repeated polygons per fire order, and HTTP 200
responses carrying an embedded error.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from maplestats_mcp.modules.ab_wildfire import client
from maplestats_mcp.modules.ab_wildfire import constants as c
from maplestats_mcp.modules.ab_wildfire.client import FireFilters
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable

# Handlers are keyed by a distinctive piece of the layer URL.
Handler = Callable[[dict[str, str]], dict[str, Any]]

LAYER_INFO = {"editingInfo": {"dataLastEditDate": 1790975349776}}


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


class Server:
    """A fake ArcGIS server: routes by layer URL, records every query."""

    def __init__(self) -> None:
        self.handlers: dict[str, Handler] = {}
        self.queries: list[tuple[str, dict[str, str]]] = []

    def on(self, layer_url: str, handler: Handler) -> None:
        self.handlers[layer_url] = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        params = dict(request.url.params)
        is_query = url.endswith("/query")
        layer = url.removesuffix("/query")
        handler = self.handlers.get(layer)
        if handler is None:
            return httpx.Response(404, json={"message": f"unrouted {url}"})
        if not is_query:
            return httpx.Response(200, json=LAYER_INFO)
        self.queries.append((layer, params))
        return httpx.Response(200, json=handler(params))


@pytest.fixture
def server(httpx_mock) -> Server:
    fake = Server()
    httpx_mock.add_callback(fake, is_reusable=True, is_optional=True)
    return fake


def _rows(rows: list[dict[str, Any]], total: int | None = None) -> Handler:
    """Answer a count query with the total and any other query with the rows."""

    def handler(params: dict[str, str]) -> dict[str, Any]:
        if params.get("returnCountOnly") == "true":
            return {"count": len(rows) if total is None else total}
        return {"features": [{"attributes": r} for r in rows]}

    return handler


def _fire(**overrides: Any) -> dict[str, Any]:
    row = {
        "LABEL": "CWF-001-2026",
        "FIRE_YEAR": 2026,
        "FIRE_TYPE": "Wildfire",
        "FIRE_STATUS": "Extinguished",
        "FIRE_STATUS_DATE": "2026/01/14 12:57:00",
        "ASSESSMENT_ASSISTANCE_DATE": 1767717060000,
        "AREA_ESTIMATE": 0.02,
        "SIZE_CLASS": "A",
        "GENERAL_CAUSE": "Human",
        "RESP_AREA": "Calgary Forest Area",
        "CO_FLAG": "N",
        "FIRE_COMPLEX_NUMBER": None,
        "FIRE_COMPLEX_NAME": None,
        "INCIDENT_TYPE": None,
        "RESPONSE_TYPE": None,
        "LATITUDE": 49.811033,
        "LONGITUDE": -113.937867,
    }
    row.update(overrides)
    return row


# ------------------------------------------------------------ where clauses


def test_where_is_all_rows_without_filters():
    assert client.build_fire_where(FireFilters()) == "1=1"


def test_where_status_matches_the_misspelled_variant_too():
    where = client.build_fire_where(FireFilters(status="assistance ended"))
    assert "'ASSISTANCE ENDED'" in where
    assert "'ASSISSTANCE ENDED'" in where


def test_where_quotes_and_case_folds_text_filters():
    where = client.build_fire_where(
        FireFilters(cause="Under Investigation", forest_area="O'Brien", fire_type="mutual aid")
    )
    assert "UPPER(GENERAL_CAUSE) = 'UNDER INVESTIGATION'" in where
    assert "UPPER(RESP_AREA) LIKE '%O''BRIEN%'" in where
    assert "FIRE_TYPE = 'Mutual Aid'" in where


def test_where_dates_are_inclusive_for_both_bases():
    assessed = client.build_fire_where(FireFilters(start_date="2026-07-01", end_date="2026-07-31"))
    assert "ASSESSMENT_ASSISTANCE_DATE >= DATE '2026-07-01'" in assessed
    assert "ASSESSMENT_ASSISTANCE_DATE < DATE '2026-08-01'" in assessed
    # The status date is text 'YYYY/MM/DD HH:MM:SS', so it is compared as text.
    status = client.build_fire_where(
        FireFilters(start_date="2026-07-01", end_date="2026-07-31", date_basis="status_changed")
    )
    assert "FIRE_STATUS_DATE >= '2026/07/01'" in status
    assert "FIRE_STATUS_DATE < '2026/08/01'" in status


def test_where_active_only_excludes_every_closed_status():
    where = client.build_fire_where(FireFilters(active_only=True))
    for closed in ("Extinguished", "Turned Over", "Assistance Ended", "Assisstance Ended"):
        assert f"'{closed}'" in where
    assert "NOT IN" in where


def test_where_size_class_list_and_bbox():
    where = client.build_fire_where(FireFilters(size_class="d, e", bbox=[-115, 53, -113, 55]))
    assert "SIZE_CLASS IN ('D', 'E')" in where
    assert "LONGITUDE >= -115 AND LATITUDE >= 53 AND LONGITUDE <= -113 AND LATITUDE <= 55" in where


@pytest.mark.parametrize(
    "filters, dataset",
    [
        (FireFilters(size_class="F"), "current"),
        (FireFilters(fire_type="Grass fire"), "current"),
        (FireFilters(start_date="2026/07/01"), "current"),
        (FireFilters(start_date="2026-08-01", end_date="2026-07-01"), "current"),
        (FireFilters(bbox=[-113, 53, -115, 55]), "current"),
        (FireFilters(carryover=True), "previous_5_years"),
    ],
)
def test_where_rejects_bad_filters(filters, dataset):
    with pytest.raises(InvalidInput):
        client.build_fire_where(filters, dataset=dataset)


# ------------------------------------------------------------------- fires


async def test_list_fires_parses_a_row_and_uses_layer_edit_time(server):
    server.on(c.FIRES_CURRENT, _rows([_fire()], total=823))
    result = await client.list_fires(limit=1)
    assert result.total_matches == 823
    fire = result.fires[0]
    assert fire.fire_number == "CWF-001-2026"
    assert fire.status_changed is not None
    # Alberta local text (MST in January, UTC-7) converted to UTC, like
    # assessed_at; it used to be a naive local time beside a UTC one.
    assert fire.status_changed.isoformat() == "2026-01-14T19:57:00+00:00"
    assert fire.assessed_at is not None
    assert fire.assessed_at.isoformat() == "2026-01-06T16:31:00+00:00"
    assert fire.carryover is False
    assert result.provenance.as_of is not None
    assert result.provenance.as_of.isoformat() == "2026-10-02T21:09:09.776000+00:00"
    assert "Open Government Licence - Alberta" in (result.provenance.licence or "")
    query = server.queries[-1][1]
    assert query["orderByFields"] == "FIRE_STATUS_DATE DESC, OBJECTID DESC"
    assert query["returnGeometry"] == "false"


async def test_french_provenance_licence_and_english_only_note(server):
    server.on(c.FIRES_CURRENT, _rows([_fire()], total=823))
    result = await client.list_fires(limit=1, lang="fr")
    prov = result.provenance
    assert (prov.licence or "").startswith("Licence du gouvernement ouvert – Alberta")
    assert (prov.freshness or "").startswith("mis à jour par Alberta Wildfire")
    assert "en anglais seulement" in (prov.limits or "")
    assert (prov.coverage or "").startswith("feux de l'année en cours")
    # The record values stay as Alberta Wildfire publishes them.
    assert result.fires[0].status == "Extinguished"


def test_french_errors():
    with pytest.raises(InvalidInput, match=r"^Entrée invalide\xa0: size_class doit être"):
        client.build_fire_where(FireFilters(size_class="F"), lang="fr")
    with pytest.raises(InvalidInput, match="carryover n'est consigné"):
        client.build_fire_where(FireFilters(carryover=True), dataset="previous_5_years", lang="fr")
    with pytest.raises(InvalidInput, match=r"^carryover is only recorded in the 'current'"):
        client.build_fire_where(FireFilters(carryover=True), dataset="previous_5_years")


async def test_mutual_aid_fire_has_no_cause_and_history_layer_has_no_carryover(server):
    row = _fire(FIRE_TYPE="Mutual Aid", GENERAL_CAUSE=None, FIRE_STATUS="Assisstance Ended")
    for key in ("CO_FLAG", "FIRE_COMPLEX_NUMBER", "FIRE_COMPLEX_NAME", "INCIDENT_TYPE"):
        del row[key]
    del row["RESPONSE_TYPE"]
    server.on(c.FIRES_HISTORY, _rows([row]))
    result = await client.list_fires("previous_5_years", limit=1)
    fire = result.fires[0]
    assert fire.cause is None
    assert fire.carryover is None
    assert fire.status == "Assistance Ended"
    requested = server.queries[-1][1]["outFields"]
    assert "CO_FLAG" not in requested


async def test_largest_sort_and_paging_reach_the_query(server):
    server.on(c.FIRES_CURRENT, _rows([_fire()]))
    await client.list_fires("current", FireFilters(), sort_by="largest", limit=7, offset=14)
    query = server.queries[-1][1]
    assert query["orderByFields"] == "AREA_ESTIMATE DESC, OBJECTID DESC"
    assert (query["resultRecordCount"], query["resultOffset"]) == ("7", "14")


async def test_list_fires_near_a_point_cuts_to_the_circle_nearest_first(server):
    rows = [
        _fire(LABEL="FAR", LATITUDE=56.9, LONGITUDE=-111.0),
        _fire(LABEL="NEAR", LATITUDE=56.73, LONGITUDE=-111.38),
        _fire(LABEL="MID", LATITUDE=56.8, LONGITUDE=-111.38),
        _fire(LABEL="NOPOINT", LATITUDE=None, LONGITUDE=None),
    ]
    server.on(c.FIRES_CURRENT, _rows(rows))
    result = await client.list_fires(
        "current", FireFilters(), latitude=56.7267, longitude=-111.38, radius_km=20
    )
    assert [f.fire_number for f in result.fires] == ["NEAR", "MID"]
    assert result.total_matches == 2
    assert result.fires[0].distance_km is not None
    assert result.fires[0].distance_km < result.fires[1].distance_km  # type: ignore[operator]
    assert "LATITUDE >=" in result.where


async def test_near_search_refuses_a_box_with_too_many_fires(server):
    server.on(c.FIRES_CURRENT, _rows([_fire()], total=5000))
    with pytest.raises(InvalidInput, match="narrow"):
        await client.list_fires(
            "current", FireFilters(), latitude=56.7, longitude=-111.4, radius_km=300
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 2001},
        {"offset": -1},
        {"latitude": 56.7},
        {"latitude": 56.7, "longitude": -111.4, "radius_km": 500},
        {"latitude": 156.7, "longitude": -111.4, "radius_km": 10},
        {"sort_by": "oldest"},
        {"dataset": "2019"},
    ],
)
async def test_list_fires_rejects_bad_arguments(kwargs):
    with pytest.raises(InvalidInput):
        await client.list_fires(**kwargs)


async def test_embedded_error_becomes_invalid_input(server):
    server.on(
        c.FIRES_CURRENT,
        lambda _p: {"error": {"code": 400, "message": "Cannot perform query.", "details": ["x"]}},
    )
    with pytest.raises(InvalidInput):
        await client.list_fires()


async def test_missing_layer_edit_time_only_drops_as_of(httpx_mock):
    # The data query works; the metadata call failing must not fail the tool.
    fake = Server()
    fake.on(c.FIRES_CURRENT, _rows([_fire()]))

    def flaky(request: httpx.Request) -> httpx.Response:
        if "/query" not in str(request.url):
            return httpx.Response(200, json={"error": {"code": 500, "message": "boom"}})
        return fake(request)

    httpx_mock.add_callback(flaky, is_reusable=True, is_optional=True)
    result = await client.list_fires(limit=1)
    assert result.provenance.as_of is None
    assert result.fires


# --------------------------------------------------------------- summaries


async def test_summary_merges_the_typo_status_and_sums_area(server):
    def handler(params: dict[str, str]) -> dict[str, Any]:
        stats = json.loads(params["outStatistics"])
        assert [s["outStatisticFieldName"] for s in stats] == ["n", "ha", "mx"]
        assert params["groupByFieldsForStatistics"] == "FIRE_STATUS"
        return {
            "features": [
                {"attributes": {"FIRE_STATUS": "Extinguished", "n": 6556, "ha": 100.5, "mx": 9.0}},
                {"attributes": {"FIRE_STATUS": "Assistance Ended", "n": 53, "ha": 10.0, "mx": 3.0}},
                {
                    "attributes": {
                        "FIRE_STATUS": "Assisstance Ended",
                        "n": 211,
                        "ha": 5.25,
                        "mx": 4.0,
                    }
                },
            ]
        }

    server.on(c.FIRES_HISTORY, handler)
    result = await client.summarize_fires("previous_5_years", "status")
    groups = {g.key: g for g in result.groups}
    assert set(groups) == {"Extinguished", "Assistance Ended"}
    assert groups["Assistance Ended"].fires == 264
    assert groups["Assistance Ended"].total_area_ha == 15.25
    assert groups["Assistance Ended"].largest_fire_ha == 4.0
    assert result.total_fires == 6820
    assert result.total_area_ha == 115.75
    assert next(g.key for g in result.groups) == "Extinguished"


async def test_summary_keeps_a_null_cause_group_and_years_in_order(server):
    server.on(
        c.FIRES_CURRENT,
        lambda p: {
            "features": [
                {"attributes": {"GENERAL_CAUSE": None, "n": 54, "ha": None, "mx": None}},
                {"attributes": {"GENERAL_CAUSE": "Lightning", "n": 273, "ha": 400.0, "mx": 90.0}},
            ]
        },
    )
    cause = await client.summarize_fires("current", "cause")
    assert [g.key for g in cause.groups] == ["Lightning", None]
    assert cause.groups[1].total_area_ha is None
    assert cause.total_area_ha == 400.0

    server.on(
        c.FIRES_HISTORY,
        lambda p: {
            "features": [
                {"attributes": {"FIRE_YEAR": 2025, "n": 5, "ha": 1.0, "mx": 1.0}},
                {"attributes": {"FIRE_YEAR": 2021, "n": 9, "ha": 2.0, "mx": 1.0}},
            ]
        },
    )
    years = await client.summarize_fires("previous_5_years", "fire_year")
    assert [g.key for g in years.groups] == [2021, 2025]


async def test_summary_rejects_unknown_grouping():
    with pytest.raises(InvalidInput):
        await client.summarize_fires("current", "county")  # type: ignore[arg-type]


# -------------------------------------------------------------- statistics


async def test_season_statistics_returns_whole_counts_and_nulls(server):
    server.on(
        c.STATISTICS,
        _rows(
            [
                {"statistic_name": "Wildfire_Active_Area", "statistic_value": 0.05},
                {"statistic_name": "Wildfire_Active_Count", "statistic_value": 1.0},
                {"statistic_name": "YTD_Wildfire_Total_Area", "statistic_value": 17771.48},
                {"statistic_name": "YTD_Wildfire_Total_Count", "statistic_value": 753.0},
                {"statistic_name": "New_Wildfire_24h", "statistic_value": 0.0},
            ]
        ),
    )
    server.on(
        c.THIS_DAY,
        _rows(
            [
                {
                    "FireStatusDate": "2021-10-02",
                    "FireStatusYear": 2021,
                    "TotalNumberOfWildfiresPerDay": 4,
                    "TotalNumberOfWildfiresToDate": 1263,
                    "FiveYearAvgCnt": 1099,
                    "TenYearAvgCnt": 1250.8,
                    "TwentyfiveYearAvgCnt": None,
                    "TotalDailyHaBurned": -0.23,
                    "TotalHaBurned": 52860.25,
                    "FiveYearAvgHa": 320639.05,
                    "TenYearAvgHa": 345839.43,
                    "TwentyfiveYearAvgHa": None,
                },
                {
                    "FireStatusDate": "2026-10-02",
                    "FireStatusYear": 2026,
                    "TotalNumberOfWildfiresPerDay": 0,
                    "TotalNumberOfWildfiresToDate": 753,
                    "FiveYearAvgCnt": None,
                    "TenYearAvgCnt": None,
                    "TwentyfiveYearAvgCnt": None,
                    "TotalDailyHaBurned": 0,
                    "TotalHaBurned": 17771.48,
                    "FiveYearAvgHa": None,
                    "TenYearAvgHa": None,
                    "TwentyfiveYearAvgHa": None,
                },
            ]
        ),
    )
    result = await client.get_season_statistics()
    assert result.headline.year_to_date_wildfires == 753
    assert isinstance(result.headline.year_to_date_wildfires, int)
    assert result.headline.active_wildfires == 1
    assert result.comparison_date is not None
    assert result.comparison_date.isoformat() == "2026-10-02"
    assert result.same_day_comparison[0].area_burned_that_day_ha == -0.23
    assert result.same_day_comparison[0].twentyfive_year_avg_wildfires is None
    assert result.same_day_comparison[1].five_year_avg_wildfires is None


async def test_season_statistics_with_an_empty_view_is_an_upstream_error(server):
    server.on(c.STATISTICS, _rows([]))
    server.on(c.THIS_DAY, _rows([]))
    with pytest.raises(UpstreamError):
        await client.get_season_statistics()


# -------------------------------------------------------------- perimeters


def _perimeter_handler(features: list[dict[str, Any]], total: int | None = None) -> Handler:
    def handler(params: dict[str, str]) -> dict[str, Any]:
        if params.get("returnCountOnly") == "true":
            return {"count": len(features) if total is None else total}
        assert params["f"] == "geojson"
        return {"type": "FeatureCollection", "features": features}

    return handler


_PERIMETER = {
    "type": "Feature",
    "geometry": {
        "type": "Polygon",
        "coordinates": [[[-115.4, 54.1], [-115.3, 54.1], [-115.3, 54.2], [-115.4, 54.1]]],
    },
    "properties": {
        "FireNumber": "WWF-012-2026",
        "FIRE_TYPE": "Wildfire",
        "FIRE_STATUS": "Extinguished",
        "FIRE_STATUS_DATE": "2026/05/25 14:05:00",
        "AREA_ESTIMATE": 66.22,
        "SumAreaHa": 66.22,
        "SIZE_CLASS": "D",
        "GENERAL_CAUSE": "Human",
        "RESP_AREA": "Whitecourt Forest Area",
        "CaptreDate": 1777848724000,
        "DataSource": "GPS",
        "SourceKeys": "Ground",
        "CreatMethd": "Direct from source",
        "GISFeatureLastUpdated": 1790302276000,
    },
}


async def test_perimeters_parse_geojson_properties_and_simplify_geometry(server):
    server.on(c.PERIMETERS["extinguished"], _perimeter_handler([_PERIMETER], total=118))
    result = await client.get_perimeters("extinguished", include_geometry=True, limit=1)
    assert result.total_matches == 118
    perimeter = result.perimeters[0]
    assert perimeter.fire_number == "WWF-012-2026"
    assert perimeter.geometry is not None
    assert perimeter.geometry["type"] == "Polygon"
    assert perimeter.captured_at is not None
    assert perimeter.captured_at.year == 2026
    query = server.queries[-1][1]
    assert query["returnGeometry"] == "true"
    assert query["outSR"] == "4326"
    assert query["maxAllowableOffset"] == "0.0005"


async def test_perimeters_without_geometry_do_not_ask_for_it(server):
    server.on(c.PERIMETERS["extinguished"], _perimeter_handler([{**_PERIMETER, "geometry": None}]))
    result = await client.get_perimeters("extinguished")
    assert result.perimeters[0].geometry is None
    query = server.queries[-1][1]
    assert query["returnGeometry"] == "false"
    assert "maxAllowableOffset" not in query


async def test_empty_active_perimeters_explain_the_off_season(server):
    server.on(c.PERIMETERS["active"], _perimeter_handler([]))
    result = await client.get_perimeters("active")
    assert result.total_matches == 0
    assert result.note is not None
    assert "outside the fire season" in result.note


async def test_perimeter_filters_and_limits(server):
    server.on(c.PERIMETERS["extinguished"], _perimeter_handler([_PERIMETER]))
    await client.get_perimeters(
        "extinguished", fire_number="wwf", size_class="D,E", forest_area="white", min_area_ha=50
    )
    where = server.queries[-1][1]["where"]
    assert "UPPER(FireNumber) LIKE '%WWF%'" in where
    assert "SIZE_CLASS IN ('D', 'E')" in where
    assert "AREA_ESTIMATE >= 50.0" in where
    with pytest.raises(InvalidInput):
        await client.get_perimeters("extinguished", include_geometry=True, limit=101)
    with pytest.raises(InvalidInput):
        await client.get_perimeters("pending")  # type: ignore[arg-type]


# ------------------------------------------------------------- fire danger


async def test_danger_at_a_point_takes_the_more_severe_polygon_on_an_edge(server):
    server.on(
        c.DANGER,
        lambda p: {
            "features": [
                {"attributes": {"Fire_Danger": "Moderate", "Last_Updated": 1790993128000}},
                {"attributes": {"Fire_Danger": "Very High", "Last_Updated": 1790993128000}},
            ]
        },
    )
    result = await client.get_fire_danger(53.5461, -113.4938)
    assert result.danger_class == "Very High"
    assert result.meaning is not None
    assert result.rating_timestamp is not None
    query = server.queries[-1][1]
    assert query["geometry"] == "-113.4938,53.5461"
    assert query["inSR"] == "4326"
    assert result.provenance.as_of is not None


async def test_danger_outside_alberta_is_a_null_class_with_a_note(server):
    server.on(c.DANGER, lambda p: {"features": []})
    result = await client.get_fire_danger(49.28, -123.12)
    assert result.danger_class is None
    assert result.note is not None
    assert "Alberta only" in result.note


async def test_danger_meaning_and_note_in_french(server):
    server.on(
        c.DANGER,
        lambda p: {
            "features": [{"attributes": {"Fire_Danger": "High", "Last_Updated": 1790993128000}}]
        },
    )
    result = await client.get_fire_danger(53.5461, -113.4938, lang="fr")
    assert result.danger_class == "High"
    assert (result.meaning or "").startswith("Les combustibles forestiers sont secs")
    assert (result.provenance.freshness or "").startswith("la cote est actualisée")


async def test_danger_summary_orders_classes_by_severity(server):
    server.on(
        c.DANGER,
        lambda p: {
            "features": [
                {"attributes": {"Fire_Danger": "Low", "n": 326, "updated": 1790993128000}},
                {"attributes": {"Fire_Danger": "Extreme", "n": 5, "updated": 1790993128000}},
                {"attributes": {"Fire_Danger": "High", "n": 179, "updated": 1790993128000}},
            ]
        },
    )
    result = await client.summarize_fire_danger([-118.0, 54.0, -116.0, 55.0])
    assert [d.danger_class for d in result.classes] == ["Extreme", "High", "Low"]
    assert result.most_severe_class == "Extreme"
    assert result.total_polygons == 510
    query = server.queries[-1][1]
    assert query["geometryType"] == "esriGeometryEnvelope"
    assert query["geometry"] == "-118.0,54.0,-116.0,55.0"


async def test_danger_arguments_are_validated():
    with pytest.raises(InvalidInput):
        await client.get_fire_danger(95.0, -113.0)
    with pytest.raises(InvalidInput):
        await client.summarize_fire_danger([-116.0, 54.0, -118.0, 55.0])


# -------------------------------------------------------- fire control orders


def _alert(alert_type: str, name: str, start: int, **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "order_number": None,
        "alert_type": alert_type,
        "contact_number": "4037793733",
        "jurisdictions": name,
        "start_date": start,
        **extra,
    }


def _orders_server(server: Server) -> None:
    advisory = c.FIRE_CONTROL_ORDERS["Fire Advisory"]
    restriction = c.FIRE_CONTROL_ORDERS["Fire Restriction"]
    server.on(
        advisory,
        _rows(
            [
                _alert("Fire Advisory", "Town of Banff", 1785391200000),
                _alert("Fire Advisory", "Innisfail", 1685448000000),
            ]
        ),
    )
    # One jurisdiction drawn as three polygons, as Special Areas Board is live.
    server.on(
        restriction,
        _rows(
            [
                _alert("Fire Restriction", "Special Areas Board", 1786687200000),
                _alert("Fire Restriction", "Special Areas Board", 1786687200000),
                _alert("Fire Restriction", "Special Areas Board", 1786687200000),
            ]
        ),
    )
    server.on(c.FIRE_CONTROL_ORDERS["Fire Ban"], _rows([]))
    server.on(c.FIRE_CONTROL_ORDERS["Forest Area Closure"], _rows([]))
    server.on(c.OHV_RESTRICTION, _rows([]))


async def test_orders_merge_repeated_polygons_and_sort_by_severity(server):
    _orders_server(server)
    result = await client.get_fire_control_orders()
    assert [o.alert_type for o in result.orders] == [
        "Fire Restriction",
        "Fire Advisory",
        "Fire Advisory",
    ]
    assert result.orders[0].polygons == 3
    assert result.counts_by_type == {"Fire Restriction": 1, "Fire Advisory": 2}
    assert result.orders[1].name == "Innisfail"
    assert result.orders[0].start_date is not None
    assert result.orders[0].start_date.isoformat() == "2026-08-14"


async def test_orders_warn_about_entries_older_than_a_year(server):
    _orders_server(server)
    result = await client.get_fire_control_orders()
    assert result.note is not None
    assert "more than a year ago" in result.note


async def test_orders_for_a_point_send_the_point_to_every_layer(server):
    _orders_server(server)
    await client.get_fire_control_orders(51.18, -115.57)
    sent = [params for _, params in server.queries]
    assert len(sent) == 5
    assert all(p["geometry"] == "-115.57,51.18" for p in sent)
    assert all(p["spatialRel"] == "esriSpatialRelIntersects" for p in sent)


async def test_orders_filter_by_type_and_name(server):
    _orders_server(server)
    result = await client.get_fire_control_orders(
        alert_type="fire advisory", name_contains="o'brien"
    )
    assert [layer for layer, _ in server.queries] == [c.FIRE_CONTROL_ORDERS["Fire Advisory"]]
    where = server.queries[0][1]["where"]
    assert "UPPER(name) LIKE '%O''BRIEN%'" in where
    assert "UPPER(jurisdictions) LIKE '%O''BRIEN%'" in where
    assert result.orders  # the fake does not filter; the where clause is what matters


async def test_ohv_restrictions_use_their_own_fields(server):
    _orders_server(server)
    server.on(
        c.OHV_RESTRICTION,
        _rows(
            [
                {
                    "Order_Number": "OHV-12",
                    "Effective": 1785391200000,
                    "Expiry": 1788156000000,
                    "Website_Name": "Kananaskis OHV restriction",
                    "Website_URL": "https://example.test/ohv",
                }
            ]
        ),
    )
    result = await client.get_fire_control_orders(alert_type="OHV Restriction")
    order = result.orders[0]
    assert order.alert_type == "OHV Restriction"
    assert order.name == "Kananaskis OHV restriction"
    assert order.expiry_date is not None
    assert order.expiry_date.isoformat() == "2026-08-31"
    assert order.website == "https://example.test/ohv"


async def test_orders_limit_trims_after_merging(server):
    _orders_server(server)
    result = await client.get_fire_control_orders(limit=1)
    assert result.returned_count == 1
    assert "1 of 3 distinct entries" in (result.provenance.limits or "")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"latitude": 51.0},
        {"longitude": -115.0},
        {"alert_type": "fire party"},
        {"limit": 0},
        {"latitude": 51.0, "longitude": -215.0},
    ],
)
async def test_orders_reject_bad_arguments(kwargs):
    with pytest.raises(InvalidInput):
        await client.get_fire_control_orders(**kwargs)


# ------------------------------------------------------- live-shaped bodies

# Trimmed from live responses captured 2026-10-03 (services.arcgis.com,
# org Eb8P5h4CJk8utIBz): the same query parameters the client sends, with the
# `fields` metadata list cut down and only the first features kept.

# GET .../Wildfire_year_to_date/FeatureServer/0/query?outFields=<_FIRE_FIELDS_CURRENT>
#     &orderByFields=FIRE_STATUS_DATE DESC, OBJECTID DESC&resultRecordCount=3&f=json
_LIVE_FIRES = {
    "objectIdFieldName": "OBJECTID",
    "geometryType": "esriGeometryPoint",
    "spatialReference": {"wkid": 102100, "latestWkid": 3857},
    "fields": [
        {"name": "FIRE_STATUS_DATE", "type": "esriFieldTypeString", "length": 19},
        {"name": "ASSESSMENT_ASSISTANCE_DATE", "type": "esriFieldTypeDate", "length": 8},
    ],
    "exceededTransferLimit": True,
    "features": [
        {
            "attributes": {
                "LABEL": "PWF-069-2026",
                "FIRE_YEAR": 2026,
                "FIRE_TYPE": "Wildfire",
                "FIRE_STATUS": "Extinguished",
                "FIRE_STATUS_DATE": "2026/10/01 14:00:00",
                "ASSESSMENT_ASSISTANCE_DATE": 1788465660000,
                "AREA_ESTIMATE": 0.99,
                "SIZE_CLASS": "B",
                "GENERAL_CAUSE": "Human",
                "RESP_AREA": "Peace River Forest Area",
                "CO_FLAG": "N",
                "FIRE_COMPLEX_NUMBER": None,
                "FIRE_COMPLEX_NAME": None,
                "INCIDENT_TYPE": None,
                "RESPONSE_TYPE": None,
                "LATITUDE": 57.9084,
                "LONGITUDE": -117.774717,
            }
        }
    ],
}

# GET .../Wildfire_Statistics_Prod_View/FeatureServer/0/query?outFields=*&f=json
# The field is esriFieldTypeDouble, yet whole values arrive as JSON integers
# (1, 753, 0), not 753.0 as the hand-written fixture above assumed.
_LIVE_STATISTICS = {
    "objectIdFieldName": "OBJECTID",
    "fields": [{"name": "statistic_value", "type": "esriFieldTypeDouble"}],
    "features": [
        {"attributes": {"OBJECTID": oid, "statistic_name": name, "statistic_value": value}}
        for oid, name, value in [
            (1, "Wildfire_Active_Area", 0.05),
            (2, "Wildfire_Active_Count", 1),
            (3, "YTD_Wildfire_Total_Area", 17771.48),
            (4, "YTD_Wildfire_Total_Count", 753),
            (5, "New_Wildfire_24h", 0),
        ]
    ],
}

# GET .../5_year_summary_on_this_day_prod_view/FeatureServer/2/query?outFields=*
#     &orderByFields=FireStatusYear&f=json (first two of six rows). OBJECTID is
# the date as a number and the layer's real id field is ESRI_OID.
_LIVE_THIS_DAY = {
    "objectIdFieldName": "ESRI_OID",
    "features": [
        {
            "attributes": {
                "OBJECTID": 20211003,
                "FireStatusDate": "2021-10-03",
                "FireStatusYear": 2021,
                "FireStatusMonth": 10,
                "FireStatusDay": 3,
                "TotalNumberOfWildfiresPerDay": 3,
                "TotalNumberOfWildfiresToDate": 1266,
                "FiveYearAvgCnt": 1100.6,
                "TenYearAvgCnt": 1252.1,
                "TwentyfiveYearAvgCnt": None,
                "TotalDailyHaBurned": 0.62,
                "TotalHaBurned": 52860.87,
                "FiveYearAvgHa": 320644.13,
                "TenYearAvgHa": 345842.03,
                "TwentyfiveYearAvgHa": None,
                "ESRI_OID": 1,
            }
        },
        {
            "attributes": {
                "OBJECTID": 20221003,
                "FireStatusDate": "2022-10-03",
                "FireStatusYear": 2022,
                "FireStatusMonth": 10,
                "FireStatusDay": 3,
                "TotalNumberOfWildfiresPerDay": 3,
                "TotalNumberOfWildfiresToDate": 1140,
                "FiveYearAvgCnt": 1072,
                "TenYearAvgCnt": 1267.9,
                "TwentyfiveYearAvgCnt": None,
                "TotalDailyHaBurned": 15.13,
                "TotalHaBurned": 144739.4,
                "FiveYearAvgHa": 208925.47,
                "TenYearAvgHa": 257078.51,
                "TwentyfiveYearAvgHa": None,
                "ESRI_OID": 2,
            }
        },
    ],
}

# GET .../Wildfire_Perimeter_Extinguished_(PROD)/FeatureServer/3/query
#     ?outFields=<_PERIMETER_FIELDS>&resultRecordCount=2&f=geojson&returnGeometry=false
# With f=geojson the transfer-limit flag moves under a top-level "properties",
# and a whole-number area arrives as an integer (1116).
_LIVE_PERIMETERS = {
    "type": "FeatureCollection",
    "properties": {"exceededTransferLimit": True},
    "features": [
        {
            "type": "Feature",
            "geometry": None,
            "properties": {
                "FireNumber": "LWF-060-2026",
                "FIRE_TYPE": "Wildfire",
                "FIRE_STATUS": "Extinguished",
                "FIRE_STATUS_DATE": "2026/07/10 13:47:00",
                "AREA_ESTIMATE": 1116,
                "SIZE_CLASS": "E",
                "GENERAL_CAUSE": "Lightning",
                "RESP_AREA": "Lac La Biche Forest Area",
                "CaptreDate": 1781023620000,
                "DataSource": "GPS",
                "SourceKeys": "Unknown",
                "CreatMethd": "Direct from source",
                "SumAreaHa": 1093.56,
                "GISFeatureLastUpdated": 1790302276000,
            },
        }
    ],
}

# GET .../Wildfire_year_to_date/FeatureServer/0/query?where=NO_SUCH_FIELD = 1&f=json
# answered HTTP 200 with this body.
_LIVE_BAD_FIELD_ERROR = {
    "error": {
        "code": 400,
        "message": "Cannot perform query. Invalid query parameters.",
        "details": ["'Invalid field: NO_SUCH_FIELD' parameter is invalid"],
    }
}


async def test_live_shaped_fire_row_parses_dates_and_nulls(server):
    def handler(params: dict[str, str]) -> dict[str, Any]:
        if params.get("returnCountOnly") == "true":
            return {"count": 823}
        return _LIVE_FIRES

    server.on(c.FIRES_CURRENT, handler)
    result = await client.list_fires(limit=1)
    fire = result.fires[0]
    assert fire.fire_number == "PWF-069-2026"
    # The status date is local text with no zone; the assessment date is UTC epoch ms.
    assert fire.status_changed is not None
    # MDT (UTC-6) on 2026-10-01.
    assert fire.status_changed.isoformat() == "2026-10-01T20:00:00+00:00"
    assert fire.assessed_at is not None
    assert fire.assessed_at.isoformat() == "2026-09-03T20:01:00+00:00"
    assert fire.carryover is False
    assert (fire.complex_number, fire.incident_type, fire.response_type) == (None, None, None)
    assert (fire.latitude, fire.longitude) == (57.9084, -117.774717)
    # exceededTransferLimit is true on any page shorter than the layer; without a
    # radius it must not trip the near-a-point "too many fires" refusal.
    assert result.total_matches == 823


async def test_live_shaped_statistics_with_integer_values(server):
    server.on(c.STATISTICS, lambda _p: _LIVE_STATISTICS)
    server.on(c.THIS_DAY, lambda _p: _LIVE_THIS_DAY)
    result = await client.get_season_statistics()
    headline = result.headline
    assert headline.active_wildfires == 1
    assert headline.year_to_date_wildfires == 753
    assert headline.new_wildfires_24h == 0  # a real zero, not a missing value
    assert headline.year_to_date_area_ha == 17771.48
    assert [r.year for r in result.same_day_comparison] == [2021, 2022]
    assert result.same_day_comparison[1].five_year_avg_wildfires == 1072
    assert result.same_day_comparison[0].twentyfive_year_avg_area_ha is None
    assert result.comparison_date is not None
    assert result.comparison_date.isoformat() == "2022-10-03"


async def test_live_shaped_geojson_perimeter_with_integer_area(server):
    def handler(params: dict[str, str]) -> dict[str, Any]:
        if params.get("returnCountOnly") == "true":
            return {"count": 118}
        return _LIVE_PERIMETERS

    server.on(c.PERIMETERS["extinguished"], handler)
    result = await client.get_perimeters("extinguished", limit=1)
    perimeter = result.perimeters[0]
    assert perimeter.area_ha == 1116.0
    assert perimeter.mapped_area_ha == 1093.56
    assert perimeter.geometry is None
    assert perimeter.captured_at is not None
    assert perimeter.captured_at.isoformat() == "2026-06-09T16:47:00+00:00"
    assert result.note is None  # 118 rows exist, so no off-season note


# ------------------------------------------------------------ error paths

_ANY_QUERY = re.compile(re.escape(c.SERVICES_ROOT) + r"/.+/query\?.*")


@pytest.mark.parametrize(
    "body, error",
    [
        (_LIVE_BAD_FIELD_ERROR, InvalidInput),
        ({"error": {"code": 404, "message": "Layer not found", "details": []}}, NotFound),
        ({"error": {"code": 499, "message": "Token Required", "details": []}}, UpstreamError),
        ({"error": {"code": 500, "message": "Unable to complete operation."}}, UpstreamError),
    ],
)
async def test_embedded_error_codes_map_to_typed_errors(httpx_mock, body, error):
    # ArcGIS answers HTTP 200 and puts the failure in the body, so the HTTP
    # status layer never sees it.
    httpx_mock.add_response(url=_ANY_QUERY, json=body)
    with pytest.raises(error) as caught:
        await client.list_fires()
    if body is _LIVE_BAD_FIELD_ERROR:
        assert "Invalid field: NO_SUCH_FIELD" in str(caught.value)
    assert len(httpx_mock.get_requests()) == 1  # an embedded error is not retried


@pytest.mark.parametrize(
    "status, error",
    [
        # A rate limit that outlasts the retries is the service being
        # unavailable, not the caller's InvalidInput.
        (429, UpstreamUnavailable),
        (500, UpstreamError),
        (502, UpstreamError),
        (503, UpstreamError),
        (504, UpstreamError),
    ],
)
async def test_transient_status_is_retried_three_times_then_typed(httpx_mock, status, error):
    httpx_mock.add_response(
        url=_ANY_QUERY, status_code=status, text="Service Unavailable", is_reusable=True
    )
    with pytest.raises(error, match=f"HTTP {status}"):
        await client.summarize_fires()
    assert len(httpx_mock.get_requests()) == 3


async def test_database_pool_failure_with_4xx_is_unavailable(httpx_mock):
    httpx_mock.add_response(
        url=_ANY_QUERY,
        status_code=400,
        json={"message": "Unable to obtain connection from database HikariPool-1"},
    )
    with pytest.raises(UpstreamUnavailable, match="temporarily unavailable"):
        await client.get_fire_danger(53.5, -113.5)


@pytest.mark.parametrize(
    "status, error", [(404, NotFound), (400, InvalidInput), (403, InvalidInput)]
)
async def test_client_error_status_is_typed_and_not_retried(httpx_mock, status, error):
    httpx_mock.add_response(
        url=_ANY_QUERY, status_code=status, json={"message": "nope", "statusCode": status}
    )
    with pytest.raises(error, match="nope"):
        await client.get_fire_danger(53.5, -113.5)
    assert len(httpx_mock.get_requests()) == 1


@pytest.mark.parametrize(
    "content_type, text",
    [
        ("text/html", "<!DOCTYPE html><html><body><h1>502 Bad Gateway</h1></body></html>"),
        ("application/json", '{"features": [{"attributes": '),
    ],
)
async def test_non_json_body_with_http_200_is_a_typed_error(httpx_mock, content_type, text):
    httpx_mock.add_response(url=_ANY_QUERY, headers={"Content-Type": content_type}, text=text)
    # Not a timeout: an UpstreamError naming the problem and the start of the body.
    with pytest.raises(UpstreamError, match="did not return JSON .*it starts: ") as caught:
        await client.get_perimeters("extinguished")
    assert "did not respond in time" not in str(caught.value)


async def test_null_count_features_and_attributes_are_empty_not_errors(server):
    # `"features": null` and `"attributes": null` instead of absent keys.
    server.on(c.FIRES_CURRENT, lambda p: {"count": None, "features": None})
    fires = await client.list_fires()
    assert (fires.total_matches, fires.fires) == (0, [])

    server.on(c.DANGER, lambda p: {"features": [{"attributes": None}]})
    danger = await client.get_fire_danger(53.5, -113.5)
    assert danger.danger_class is None
    assert danger.rating_timestamp is None

    server.on(c.FIRES_HISTORY, lambda p: {"features": None})
    summary = await client.summarize_fires("previous_5_years", "cause")
    assert (summary.total_fires, summary.groups) == (0, [])


@pytest.mark.parametrize(
    "status, body",
    [
        (404, {"message": "Not Found", "statusCode": 404}),
        (200, {"error": {"code": 400, "message": "Invalid URL"}}),
        (429, {"message": "Too Many Requests"}),
    ],
)
async def test_layer_info_failure_only_drops_as_of(httpx_mock, status, body):
    # The layer document is only a freshness hint: any typed failure there
    # (404 -> NotFound, embedded 400 -> InvalidInput, 429 -> UpstreamUnavailable
    # after retries) must leave an already-successful data query intact.
    fake = Server()
    fake.on(c.DANGER, lambda p: {"features": [{"attributes": {"Fire_Danger": "Low"}}]})

    def route(request: httpx.Request) -> httpx.Response:
        if "/query" in str(request.url):
            return fake(request)
        return httpx.Response(status, json=body)

    httpx_mock.add_callback(route, is_reusable=True)
    result = await client.get_fire_danger(53.5, -113.5)
    assert result.danger_class == "Low"
    assert result.provenance.as_of is None


async def test_one_failing_order_layer_fails_the_whole_listing_with_a_typed_error(server):
    # The five layers are queried together; a half-empty list would read as
    # "no fire ban here", so one failed layer must fail the call.
    _orders_server(server)
    server.on(c.FIRE_CONTROL_ORDERS["Fire Ban"], lambda p: _LIVE_BAD_FIELD_ERROR)
    with pytest.raises(InvalidInput):
        await client.get_fire_control_orders()
