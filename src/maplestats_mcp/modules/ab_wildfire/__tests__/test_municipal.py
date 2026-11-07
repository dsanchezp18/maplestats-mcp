"""Tests for the municipal-reported wildfire layers, with rows shaped like the
live extinguished layer of 2026-11-07 (package docstring, point 9)."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from maplestats_mcp.modules.ab_wildfire import client
from maplestats_mcp.modules.ab_wildfire import constants as c
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput


def _feature(number: str, government: str, ha: float, start_ms: int, x: float, y: float):
    return {
        "attributes": {
            "MRFireNumber": number,
            "MutualAidNumber": None,
            "FireIncidentStatus": "Extinguished",
            "Hectares": ha,
            "EstimatedStartDate": start_ms,
            "FireInactiveDate": start_ms + 61_500_000,
            "FireExtinguishedDate": start_ms + 61_500_000,
            "LocalGovernment": government,
            "Fire_Info_Website": "",
            "Fire_Info_Phone_Num": "(780) 623-1747",
            "MutualAidContactZone": "Lac La Biche MACZ",
            "GISFeatureLastUpdated": 1794005065000,
            "OBJECTID": 98,
        },
        "geometry": {"x": x, "y": y},
    }


INACTIVE = [
    # 2026-10-17 06:00Z is Alberta midnight on 2026-10-17.
    _feature("LMR-0076-2026", "Lac La Biche County", 4, 1792216800000, -111.7946, 54.4594),
    _feature("LMR-0007-2026", "Strathcona County", 0.5, 1777010400000, -113.40, 53.55),
    _feature("CMR-0054-2026", "M.D. of Willow Creek No. 26", 3.28, 1788933600000, -113.22, 49.78),
]


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def layers(httpx_mock) -> list[dict[str, str]]:
    seen: list[dict[str, str]] = []

    def route(request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        params = dict(request.url.params)
        if not url.endswith("/query"):
            return httpx.Response(200, json={"editingInfo": {"dataLastEditDate": 1794088267950}})
        seen.append(params)
        rows: list[dict[str, Any]] = INACTIVE if "Extinguished" in url else []
        return httpx.Response(200, json={"features": rows})

    httpx_mock.add_callback(route, is_reusable=True)
    return seen


async def test_all_latest_first_with_wgs84_geometry(layers):
    result = await client.list_municipal_fires()
    assert result.total_matches == 3 and result.total_area_ha == 7.78
    first = result.fires[0]
    assert first.fire_number == "LMR-0076-2026" and first.start_date == date(2026, 10, 17)
    assert (first.latitude, first.longitude) == (54.4594, -111.7946)
    assert first.info_website is None and first.layer == "inactive"
    assert all(q["outSR"] == "4326" for q in layers)
    assert "Open Government Licence - Alberta" in (result.provenance.licence or "")


async def test_near_a_point_and_filters(layers):
    near = await client.list_municipal_fires(latitude=53.5461, longitude=-113.4938, radius_km=50)
    assert [f.fire_number for f in near.fires] == ["LMR-0007-2026"]
    assert near.fires[0].distance_km is not None and near.fires[0].distance_km < 10
    again = await client.list_municipal_fires()
    assert all(f.distance_km is None for f in again.fires)  # cached rows untouched
    county = await client.list_municipal_fires(local_government="willow creek")
    assert [f.fire_number for f in county.fires] == ["CMR-0054-2026"]
    dated = await client.list_municipal_fires(start_date="2026-09-01", sort_by="largest")
    assert [f.fire_number for f in dated.fires] == ["LMR-0076-2026", "CMR-0054-2026"]


async def test_active_only_is_empty_off_season(layers):
    result = await client.list_municipal_fires("active")
    assert result.total_matches == 0 and result.total_area_ha == 0
    assert len(layers) == 1  # only the active layer was read


async def test_bad_arguments():
    with pytest.raises(InvalidInput):
        await client.list_municipal_fires(latitude=53.0)
    with pytest.raises(InvalidInput):
        await client.list_municipal_fires(start_date="2026/10/01")
    with pytest.raises(InvalidInput, match="state doit"):
        await client.list_municipal_fires("burning", lang="fr")  # type: ignore[arg-type]


def test_layers_are_the_prod_services():
    assert all("_Prod/FeatureServer/4" in url for url in c.MUNICIPAL_FIRES.values())
