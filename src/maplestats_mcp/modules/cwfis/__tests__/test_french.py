"""lang="fr" for the CWFIS module: French errors, labels and provenance; English unchanged."""

from __future__ import annotations

import re

import pytest

from maplestats_mcp.modules.cwfis import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

WFS = re.compile(re.escape(constants.WFS_URL) + r"\?.*")
SITREP = re.compile(re.escape(constants.SITREP_URL) + r".*")


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _collection(*props: dict) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": None, "properties": p} for p in props],
        "numberMatched": len(props),
    }


async def test_fire_danger_class_and_provenance_in_french(httpx_mock):
    httpx_mock.add_response(url=WFS, json=_collection({"GRIDCODE": 3}))
    danger = await client.get_fire_danger(latitude=50.0, longitude=-120.0, lang="fr")
    assert danger.danger_class == "Très élevé"
    assert "SCIFV" in (danger.provenance.limits or "")
    assert "Licence du gouvernement ouvert – Canada" in (danger.provenance.licence or "")


async def test_fire_danger_english_is_unchanged(httpx_mock):
    httpx_mock.add_response(url=WFS, json=_collection({"GRIDCODE": 3}))
    danger = await client.get_fire_danger(latitude=50.0, longitude=-120.0)
    assert danger.danger_class == "Very High"
    assert danger.provenance.freshness == "current-day fire danger rating grid"


async def test_large_fire_cause_in_french(httpx_mock):
    httpx_mock.add_response(
        url=WFS, json=_collection({"NFDBFIREID": "1", "CAUSE": "H-PB", "SIZE_HA": 300})
    )
    result = await client.search_large_fires(lang="fr")
    assert result.fires[0].cause == "Humaine (brûlage dirigé)"
    assert "feux renvoyés" in (result.provenance.coverage or "")


async def test_french_errors():
    with pytest.raises(InvalidInput, match=r"^Entrée invalide\xa0: une requête dans les archives"):
        await client.get_hotspots(start_date="2025-07-01", lang="fr")
    with pytest.raises(InvalidInput, match="est postérieur à"):
        await client.search_large_fires(year_from=2020, year_to=2010, lang="fr")
    with pytest.raises(InvalidInput, match="report_type doit être"):
        await client.get_situation_report(report_type="x", lang="fr")
    # English text is still the plain message.
    with pytest.raises(InvalidInput, match=r"^sort_by must be 'size' or 'date'\.$"):
        await client.search_large_fires(sort_by="x")


async def test_sitrep_not_found_in_french(httpx_mock):
    httpx_mock.add_response(url=SITREP, status_code=404, json={"detail": "Item not found"})
    with pytest.raises(NotFound, match="aucun rapport de situation"):
        await client.get_situation_report(date_on_or_before="1990-01-01", lang="fr")


async def test_empty_station_note_in_french(httpx_mock):
    httpx_mock.add_response(url=WFS, json=_collection())
    httpx_mock.add_response(url=WFS, json=_collection({"prov": "NF"}))
    result = await client.get_stations(name="nowhere", lang="fr")
    assert (result.note or "").startswith("Aucune station ne correspond.")
