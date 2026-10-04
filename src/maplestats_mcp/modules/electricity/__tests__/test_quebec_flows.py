"""quebec_flows.py against a file shaped like the live one (2026-10-03)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maplestats_mcp.modules.electricity import constants, quebec_flows
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError


def _site(ident: str, name: str, region: str, series: list[dict]) -> dict:
    return {
        "CodeRegionQC": "10",
        "Composition": series,
        "RegionQC": region,
        "date debut": "1994/01/01",  # the key has a space
        "date fin": None,
        "identifiant": ident,
        "nom": name,
        "xcoord": "-78.57",  # longitude, as a string
        "ycoord": "53.7339",
        "zcoord": None,
    }


def _series(measure: str, step: str, values: dict[str, str]) -> dict:
    return {
        "Donnees": values,
        "nom_unite_mesure": "m³/s",
        "pas_temps": step,
        "type_mesure": "Moyenne",
        "type_point_donnee": measure,
    }


FILE = {
    "Site": [
        _site(
            "3-130",
            "La Grande-1",
            "Nord-du-Québec",
            [
                _series(
                    "Apport filtré",
                    "Journalier",
                    {"2026/09/24T00:00:00Z": "30.00", "2026/09/23T00:00:00Z": "30.70"},
                ),
                _series(
                    "Débit total",
                    "Horaire",
                    {"2026/09/29T22:00:00Z": "3087.29", "2026/09/29T23:00:00Z": "3084.81"},
                ),
                _series(
                    "Débit turbiné - La Grande-1",
                    "Horaire",
                    {"2026/09/29T22:00:00Z": "3087.29", "2026/09/29T23:00:00Z": "3084.81"},
                ),
                _series(
                    "Débit déversé - La Grande-1",
                    "Horaire",
                    {"2026/09/29T22:00:00Z": "0.00", "2026/09/29T23:00:00Z": ""},
                ),
            ],
        ),
        _site(
            "3-91",
            "La Gabelle",
            "Mauricie",
            [_series("Débit total", "Horaire", {"2026/10/03T19:00:00Z": "512.5"})],
        ),
        _site(
            "3-109",
            "Manic-2",
            "Côte-Nord",
            [_series("Débit déversé - Manic-2", "Horaire", {"2026/09/29T23:00:00Z": "15"})],
        ),
    ]
}


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


def _serve(httpx_mock, body=FILE) -> None:
    httpx_mock.add_response(url=constants.QUEBEC_FLOWS_URL, json=body, is_reusable=True)


async def test_facilities_carry_series_kinds_and_latest_values(httpx_mock):
    _serve(httpx_mock)
    result = await quebec_flows.list_facilities()
    assert result.total_facilities == 3
    lg1 = next(f for f in result.facilities if f.facility_id == "3-130")
    assert (lg1.latitude, lg1.longitude) == (53.7339, -78.57)
    assert lg1.records_since == "1994/01/01"
    kinds = {s.measure: (s.kind, s.time_step) for s in lg1.series}
    assert kinds["Apport filtré"] == ("inflow", "daily")
    assert kinds["Débit turbiné - La Grande-1"] == ("turbined", "hourly")
    inflow = next(s for s in lg1.series if s.kind == "inflow")
    # Values arrive unsorted; the latest is by time, not by position.
    assert inflow.latest_value == 30.0
    assert inflow.last == datetime(2026, 9, 24, tzinfo=UTC)
    spilled = next(s for s in lg1.series if s.kind == "spilled")
    assert spilled.points == 1  # the empty string is dropped, not read as 0
    assert "CC BY-NC 4.0" in (result.provenance.licence or "")


async def test_filters_fold_accents(httpx_mock):
    _serve(httpx_mock)
    assert [f.name for f in (await quebec_flows.list_facilities("gabelle")).facilities] == [
        "La Gabelle"
    ]
    north = await quebec_flows.list_facilities(region="cote-nord")
    assert [f.facility_id for f in north.facilities] == ["3-109"]
    spill = await quebec_flows.list_facilities(kind="spilled")
    assert {f.facility_id for f in spill.facilities} == {"3-130", "3-109"}
    with pytest.raises(InvalidInput, match="kind"):
        await quebec_flows.list_facilities(kind="level")


async def test_facility_flows_by_id_name_kind_and_window(httpx_mock):
    _serve(httpx_mock)
    by_id = await quebec_flows.get_facility_flows("3-130")
    assert len(by_id.series) == 4
    by_name = await quebec_flows.get_facility_flows("la grande-1", kind="total")
    assert [s.info.measure for s in by_name.series] == ["Débit total"]
    windowed = await quebec_flows.get_facility_flows("3-130", start="2026-09-29T23:00:00Z")
    total = next(s for s in windowed.series if s.info.kind == "total")
    assert [p.value for p in total.values] == [3084.81]
    with pytest.raises(NotFound):
        await quebec_flows.get_facility_flows("nowhere")
    with pytest.raises(InvalidInput, match="several"):
        await quebec_flows.get_facility_flows("la g")
    with pytest.raises(InvalidInput, match="start"):
        await quebec_flows.get_facility_flows("3-130", start="yesterday")


async def test_french_provenance_and_errors(httpx_mock):
    _serve(httpx_mock)
    result = await quebec_flows.list_facilities(lang="fr")
    assert (result.provenance.coverage or "").startswith("3 sites sur 3 correspondent ;")
    assert (result.provenance.licence or "").startswith("Données ouvertes d'Hydro-Québec")
    assert (result.provenance.limits or "").startswith("Fiche :")
    with pytest.raises(NotFound, match="aucun site d'Hydro-Québec 'nowhere'"):
        await quebec_flows.get_facility_flows("nowhere", lang="fr")
    with pytest.raises(InvalidInput, match="correspond à plusieurs sites"):
        await quebec_flows.get_facility_flows("la g", lang="fr")


async def test_file_without_sites_is_an_upstream_error(httpx_mock):
    _serve(httpx_mock, {"Sites": []})
    with pytest.raises(UpstreamError, match="Site"):
        await quebec_flows.list_facilities()
