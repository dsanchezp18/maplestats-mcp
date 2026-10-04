"""Tests for the ECCC coverage client, shaped on live responses (2026-10-03).

The fixtures copy the real quirks: values stored time-major although
`axisNames` says ["y", "x", "t"]; CanDCS-U6/DCS/CanGRD rows running opposite
to the domain's y axis; SPEI giving only two timestamps for a monthly series;
DCS monthly naming `tm` "tmean" in its response; HTTP 204 with an empty body
for a bbox holding no cell centre; HTTP 500 for values outside an axis.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from urllib.parse import unquote

import httpx
import pytest

from maplestats_mcp.modules.eccc.coverages import client, constants
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

CANDCS = "climate:candcsu6:projected:annual:absolute"
SPEI = "climate:spei-3:projected"
DCS_MONTHLY = "climate:dcs:projected:monthly:absolute"
P30 = "climate:candcsu6:projected:annual:P30Y-Avg"
CANGRD = "climate:cangrd:historical:annual:anomaly"

_CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"


def _detail(cid: str, extent: dict[str, Any], res: float = 1 / 12) -> dict[str, Any]:
    return {
        "id": cid,
        "title": cid,
        "description": "CMIP6 downscaled projections of temperature and precipitation.",
        "links": [{"rel": "canonical", "href": "https://open.canada.ca/data/en/dataset/x"}],
        "extent": {
            "spatial": {
                "bbox": [[-141, 41, -52, 83.5]],
                "crs": _CRS84,
                "grid": [{"resolution": res}, {"resolution": res}],
            },
            **extent,
        },
    }


_SSP = {"scenario": {"interval": [["SSP126", "SSP245", "SSP585"]]}}
_PCT = {"percentile": {"interval": [[10, 50, 90]], "unit": "%"}}

DETAILS = {
    CANDCS: _detail(
        CANDCS,
        {
            "temporal": {"interval": [["2015", "2100"]], "grid": {"resolution": "P1Y"}},
            **_PCT,
            **_SSP,
        },
    ),
    SPEI: _detail(
        SPEI,
        {
            "temporal": {"interval": [["2006-01", "2100-02"]], "grid": {"resolution": "P1M"}},
            "percentile": {"interval": [[25, 50, 75]]},
            "scenario": {"interval": [["RCP2.6", "RCP4.5", "RCP8.5"]]},
        },
        res=1.0,
    ),
    DCS_MONTHLY: _detail(
        DCS_MONTHLY,
        {
            "temporal": {"interval": [["2006-01", "2100-12"]], "grid": {"resolution": "P1M"}},
            "percentile": {"interval": [[5, 25, 50, 75, 95]]},
            "scenario": {"interval": [["RCP2.6", "RCP4.5", "RCP8.5"]]},
        },
    ),
    P30: _detail(
        P30, {**_PCT, "P30Y-Avg": {"interval": [["2021-2050", "2041-2070", "2071-2100"]]}, **_SSP}
    ),
    CANGRD: {
        **_detail(
            CANGRD, {"temporal": {"interval": [[1900, 2018]], "grid": {"resolution": "P1Y"}}}
        ),
    },
}
DETAILS[CANGRD]["extent"]["spatial"]["grid"] = [{"resolution": 6890.6}, {"resolution": 10310.7}]

SCHEMAS = {
    CANDCS: {
        "properties": {
            "AirTemp": {"title": "Mean daily mean temperature", "x-ogc-unit": "°C"},
            "Precip": {"title": "Annual total precipitation on wet days", "x-ogc-unit": "mm"},
        }
    },
    SPEI: {"properties": {"spei": {"x-ogc-unit": "unitless"}}},
    DCS_MONTHLY: {"properties": {"pr": {"title": "Precipitation"}, "tm": {"title": "Mean temp"}}},
    P30: {"properties": {"AirTempAnomaly": {"title": "30 year mean", "x-ogc-unit": "degC"}}},
    CANGRD: {"properties": {"tmean": {"title": "Mean temperature [C]", "x-ogc-unit": "[C]"}}},
}


def _coverage(
    var: str,
    xs: dict[str, Any],
    ys: dict[str, Any],
    t: list[str] | None,
    values: Sequence[float | None],
    *,
    unit: str | None = "°C",
    crs: str = _CRS84,
) -> dict[str, Any]:
    axes: dict[str, Any] = {"x": xs, "y": ys}
    names = ["y", "x"]
    shape = [ys["num"], xs["num"]]
    if t is not None:
        axes["t"] = {"values": t}
        names.append("t")
        shape.append(len(values) // (ys["num"] * xs["num"]))
    return {
        "type": "Coverage",
        "domain": {
            "axes": axes,
            "referencing": [{"coordinates": ["x", "y"], "system": {"id": crs}}],
        },
        "parameters": {var: {"unit": {"symbol": unit}}},
        "ranges": {var: {"axisNames": names, "shape": shape, "values": list(values)}},
    }


class Router:
    """Answers the API by path; records every coverage request's query."""

    def __init__(self) -> None:
        self.coverage: dict[str, Any] = {}
        self.coverage_status: int | None = None
        self.calls: list[dict[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        if path == "/collections":
            ids = list(DETAILS) + ["climate-daily", "weather:rdpa:10km:24f"]
            return httpx.Response(200, json={"collections": [{"id": i, "title": i} for i in ids]})
        parts = path.split("/")
        cid = parts[2]
        if len(parts) == 3:
            return httpx.Response(200, json=DETAILS[cid])
        if parts[3] == "schema":
            return httpx.Response(200, json=SCHEMAS[cid])
        params = dict(request.url.params)
        self.calls.append(params)
        if self.coverage_status == 204:
            return httpx.Response(204)
        if self.coverage_status == 500:
            return httpx.Response(500, text="<title>500 Internal Server Error</title>")
        payload = self.coverage[cid]
        return httpx.Response(200, json=payload(params) if callable(payload) else payload)


@pytest.fixture
def router(httpx_mock) -> Router:
    r = Router()
    httpx_mock.add_callback(r, is_reusable=True, is_optional=True)
    return r


# CanDCS-U6, 2 x 2 cells, 2 years. Domain y runs north to south, but the data
# rows run south to north, and the values are time-major: as returned live.
_XS = {"start": -113.541667, "stop": -113.458334, "num": 2}
_YS = {"start": 53.541666, "stop": 53.458333, "num": 2}
# cell (north, west) = 5.0/6.0; (north, east) = 5.1/6.1; south row 4.x
_CANDCS_VALUES = [4.0, 4.1, 5.0, 5.1, 4.2, 4.3, 6.0, 6.1]


async def test_search_filters_by_scenario_variable_and_year(router):
    result = await client.search_coverages(scenario="ssp5-8.5")
    assert {c.id for c in result.collections} == {CANDCS, P30}
    result = await client.search_coverages(variable="spei")
    assert [c.id for c in result.collections] == [SPEI]
    result = await client.search_coverages(year=2085, timeframe="projected", frequency="monthly")
    assert {c.id for c in result.collections} == {SPEI, DCS_MONTHLY}
    result = await client.search_coverages("precipitation wet days")
    assert [c.id for c in result.collections] == [CANDCS]
    assert "Environment and Climate Change Canada" in (result.provenance.licence or "")


async def test_search_lists_only_climate_coverages(router):
    result = await client.search_coverages()
    assert result.total_count == len(DETAILS)
    p30 = next(c for c in result.collections if c.id == P30)
    assert p30.averaging_periods == ["2021-2050", "2041-2070", "2071-2100"]
    assert p30.time_range is None


async def test_describe_reports_axes_units_and_french_licence(router):
    result = await client.describe_coverage(CANDCS, lang="fr")
    assert result.scenarios == ["SSP126", "SSP245", "SSP585"]
    assert result.percentiles == [10.0, 50.0, 90.0]
    assert result.time_range is not None and result.time_range.end == "2100"
    assert [v.unit for v in result.variables] == ["°C", "mm"]
    assert result.canonical_url == "https://open.canada.ca/data/en/dataset/x"
    assert "Licence d'utilisation finale" in (result.provenance.licence or "")


async def test_describe_rejects_feature_and_unknown_ids(router):
    with pytest.raises(InvalidInput, match="climate:"):
        await client.describe_coverage("climate-daily")
    with pytest.raises(NotFound):
        await client.describe_coverage("climate:nothing")


async def test_point_reads_time_major_reversed_rows_and_names_every_axis(router):
    router.coverage[CANDCS] = _coverage("AirTemp", _XS, _YS, ["2050", "2051"], _CANDCS_VALUES)
    result = await client.get_coverage_data(
        CANDCS, lat=53.55, lon=-113.55, scenarios=["SSP585"], start="2050", end="2051"
    )
    assert [(r.time, r.value) for r in result.rows] == [("2050", 5.0), ("2051", 6.0)]
    row = result.rows[0]
    assert (row.lat, row.lon) == (53.541666, -113.541667)
    assert (row.scenario, row.percentile, row.unit) == ("SSP585", 50.0, "°C")
    assert result.point_distance_km is not None and result.point_distance_km < 2
    call = router.calls[0]
    assert call["subset"] == "scenario(SSP585),percentile(50)"
    assert call["datetime"] == "2050/2051"
    assert call["properties"] == "AirTemp"
    assert any("also has Precip" in n for n in result.notes)


async def test_bbox_rows_cover_every_cell_and_default_to_all_scenarios(router):
    router.coverage[CANDCS] = _coverage("AirTemp", _XS, _YS, ["2050", "2051"], _CANDCS_VALUES)
    result = await client.get_coverage_data(
        CANDCS, bbox=[-113.6, 53.4, -113.4, 53.6], start="2050", end="2051", max_rows=20
    )
    assert result.requests_made == 3
    assert {c["subset"].split(",")[0] for c in router.calls} == {
        "scenario(SSP126)",
        "scenario(SSP245)",
        "scenario(SSP585)",
    }
    assert result.total_rows == 24
    assert result.truncated is True and len(result.rows) == 20
    south_east = [r for r in result.rows if r.lat < 53.5 and r.lon > -113.5 and r.time == "2051"]
    assert south_east[0].value == 4.3


async def test_point_skips_null_cells_and_reports_missing(router):
    values: list[float | None] = [None, 4.1, None, None, None, 4.3, None, None]
    router.coverage[CANDCS] = _coverage("AirTemp", _XS, _YS, ["2050", "2051"], values)
    result = await client.get_coverage_data(
        CANDCS, lat=53.55, lon=-113.55, scenarios=["SSP245"], start="2050", end="2051"
    )
    assert [r.value for r in result.rows] == [4.1, 4.3]
    assert result.rows[0].lat == 53.458333


async def test_spei_two_timestamps_are_numbered_by_month(router):
    xs = {"start": -98.0, "stop": -98.0, "num": 1}
    ys = {"start": 50.0, "stop": 50.0, "num": 1}
    router.coverage[SPEI] = _coverage(
        "spei", xs, ys, ["2050-01-03", "2050-03-05"], [0.1, -0.2, 0.3], unit="unitless"
    )
    result = await client.get_coverage_data(
        SPEI, lat=50.0, lon=-97.6, scenarios=["RCP8.5"], start="2050-01", end="2050-03"
    )
    assert [r.time for r in result.rows] == ["2050-01", "2050-02", "2050-03"]
    assert any("first and last timestamps" in n for n in result.notes)
    assert router.calls[0]["subset"] == "scenario(RCP8.5),percentile(50)"


async def test_dcs_monthly_range_named_differently(router):
    xs = {"start": -135.04, "stop": -135.04, "num": 1}
    ys = {"start": 60.71, "stop": 60.71, "num": 1}
    router.coverage[DCS_MONTHLY] = _coverage("tmean", xs, ys, ["2030-01"], [-16.5], unit=None)
    result = await client.get_coverage_data(
        DCS_MONTHLY,
        lat=60.72,
        lon=-135.06,
        variables=["tm"],
        scenarios=["RCP2.6"],
        start="2030-01",
        end="2030-01",
    )
    assert result.rows[0].variable == "tm" and result.rows[0].value == -16.5
    assert any("'tmean'" in n for n in result.notes)


async def test_averaged_set_uses_window_axis_and_refuses_years(router):
    xs = {"start": -63.54, "stop": -63.54, "num": 1}
    ys = {"start": 44.625, "stop": 44.625, "num": 1}
    router.coverage[P30] = _coverage("AirTempAnomaly", xs, ys, ["2071"], [2.4], unit="degC")
    result = await client.get_coverage_data(
        P30, lat=44.65, lon=-63.57, scenarios=["SSP245"], averaging_periods=["2071-2100"]
    )
    assert result.rows[0].averaging_period == "2071-2100"
    assert "P30Y-Avg(2071-2100)" in router.calls[0]["subset"]
    assert "datetime" not in router.calls[0]
    with pytest.raises(InvalidInput, match="averaging_periods"):
        await client.get_coverage_data(P30, lat=44.65, lon=-63.57, start="2071")


async def test_cangrd_one_request_per_year_in_polar_stereographic(router):
    x, y = client.polar_stereo_forward(-105.0, 55.0)
    xs = {"start": x - 3000, "stop": x + 3000, "num": 2}
    ys = {"start": y - 4000, "stop": y + 4000, "num": 2}

    def payload(params: dict[str, str]) -> dict[str, Any]:
        base = int(params["datetime"]) - 2000
        # rows reversed: first data row is the domain's y stop
        values = [base + 0.1, base + 0.2, base + 0.3, base + 0.4]
        return _coverage(
            "tmean",
            xs,
            ys,
            None,
            values,
            unit="[C]",
            crs="http://www.opengis.net/def/crs/OGC/1.3/3995",
        )

    router.coverage[CANGRD] = payload
    result = await client.get_coverage_data(CANGRD, lat=55.0, lon=-105.0, start="2010", end="2012")
    assert [c["datetime"] for c in router.calls] == ["2010", "2011", "2012"]
    assert [r.time for r in result.rows] == ["2010", "2011", "2012"]
    lon, lat = client.polar_stereo_inverse(x - 3000, y - 4000)
    first = result.rows[0]
    assert abs(first.lat - lat) < 0.1 and abs(first.lon - lon) < 0.1
    assert result.rows[0].value == pytest.approx(10.3)


def test_polar_stereographic_round_trip_matches_live_grid():
    x, y = client.polar_stereo_forward(-113.475, 53.525)
    assert x == pytest.approx(-3758084, abs=5)
    assert y == pytest.approx(1632112, abs=5)
    lon, lat = client.polar_stereo_inverse(x, y)
    assert (lon, lat) == (pytest.approx(-113.475), pytest.approx(53.525))


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"lat": 53.5, "lon": -113.5, "start": "1990"}, "covers 2015 to 2100"),
        ({"lat": 53.5, "lon": -113.5, "scenarios": ["SSP999"]}, "SSP126"),
        ({"lat": 53.5, "lon": -113.5, "percentiles": [42]}, "percentiles"),
        ({"lat": 53.5, "lon": -113.5, "variables": ["tas"]}, "AirTemp"),
        ({"lat": 53.5, "lon": -113.5, "seasons": ["JJA"]}, "no seasons axis"),
        ({"lat": 53.5, "lon": -113.5, "start": "2050-06"}, "year"),
        ({"bbox": [-141, 41, -52, 83.5]}, "grid values"),
        ({"lat": 53.5}, "both lat and lon"),
        ({"lat": 53.5, "lon": -113.5, "bbox": [0, 0, 1, 1]}, "not both"),
        ({"lat": 30.0, "lon": -113.5}, "outside"),
        ({"bbox": [-113, 53, -114, 54]}, "west < east"),
        (
            {
                "lat": 53.5,
                "lon": -113.5,
                "variables": ["AirTemp", "Precip"],
                "percentiles": [10, 50, 90],
                "start": "2050",
            },
            None,
        ),
    ],
)
async def test_invalid_selections_are_refused_before_any_coverage_call(router, kwargs, match):
    if match is None:
        # 2 variables x 3 scenarios x 3 percentiles = 18 requests: allowed.
        router.coverage[CANDCS] = lambda params: _coverage(
            params["properties"], _XS, _YS, ["2050"], [1.0, 1.0, 1.0, 1.0]
        )
        result = await client.get_coverage_data(CANDCS, **kwargs)
        assert result.requests_made == 18
        return
    with pytest.raises(InvalidInput, match=match):
        await client.get_coverage_data(CANDCS, **kwargs)
    assert router.calls == []


async def test_too_many_requests_is_refused(router, monkeypatch):
    monkeypatch.setattr(constants, "MAX_REQUESTS", 5)
    with pytest.raises(InvalidInput, match="upstream requests"):
        await client.get_coverage_data(
            CANDCS, lat=53.5, lon=-113.5, variables=["AirTemp", "Precip"], start="2050"
        )


async def test_http_204_means_no_cell_with_data(router):
    router.coverage_status = 204
    with pytest.raises(NotFound, match="no data"):
        await client.get_coverage_data(CANDCS, lat=50.0, lon=-135.0, scenarios=["SSP245"])


async def test_http_500_html_becomes_upstream_error(router):
    router.coverage_status = 500
    with pytest.raises(UpstreamError, match="HTTP 500"):
        await client.get_coverage_data(CANDCS, lat=53.5, lon=-113.5, scenarios=["SSP245"])


async def test_http_400_description_becomes_invalid_input(httpx_mock, router):
    router.coverage[CANDCS] = None
    httpx_mock.reset()

    def bad(request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        if path.endswith("/coverage"):
            body = {"code": "InvalidParameterValue", "description": "Invalid field specified"}
            return httpx.Response(400, content=json.dumps(body))
        return router(request)

    httpx_mock.add_callback(bad, is_reusable=True)
    with pytest.raises(InvalidInput, match="Invalid field specified"):
        await client.get_coverage_data(CANDCS, lat=53.5, lon=-113.5, scenarios=["SSP245"])


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"lat": 53.5, "lon": -113.5, "start": "1990"}, "couvre 2015 à 2100"),
        ({"lat": 53.5}, "à la fois lat et lon"),
        ({"bbox": [-113, 53, -114, 54]}, "ouest < est"),
        ({"lat": 53.5, "lon": -113.5, "seasons": ["JJA"]}, "pas d'axe seasons"),
    ],
)
async def test_french_selection_errors_are_french(router, kwargs, match):
    with pytest.raises(InvalidInput, match=match) as excinfo:
        await client.get_coverage_data(CANDCS, lang="fr", **kwargs)
    assert str(excinfo.value).startswith("Entrée invalide :")
    assert router.calls == []


async def test_french_data_has_french_notes_and_provenance(router):
    router.coverage[CANDCS] = _coverage("AirTemp", _XS, _YS, ["2050", "2051"], _CANDCS_VALUES)
    result = await client.get_coverage_data(
        CANDCS, lat=53.55, lon=-113.55, scenarios=["SSP585"], start="2050", end="2051", lang="fr"
    )
    assert any(n.startswith("Aucune variable précisée :") for n in result.notes)
    assert any("qu'en anglais" in n for n in result.notes)
    assert (result.provenance.coverage or "").startswith("2 valeurs sur 2")
    assert (result.provenance.limits or "").startswith("max_rows plafonné")


async def test_french_no_data_is_french(router):
    router.coverage_status = 204
    with pytest.raises(NotFound, match="n'a pas de données au point"):
        await client.get_coverage_data(
            CANDCS, lat=50.0, lon=-135.0, scenarios=["SSP245"], lang="fr"
        )
