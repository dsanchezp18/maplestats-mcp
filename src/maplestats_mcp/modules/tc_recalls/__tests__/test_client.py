"""Tests for modules/tc_recalls/client.py, shaped on live 2026-09-23 responses."""

from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from maplestats_mcp.modules.tc_recalls import client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _field(name: str, value: object) -> dict[str, object]:
    return {"Name": name, "Value": {"Type": "System.String", "Literal": value}}


_SEARCH_ROW = [
    _field("Numéro de rappel", "2020236"),
    _field("Nom du manufacturier", "HONDA"),
    _field("Nom de modèle", "CIVIC"),
    _field("Nom de marque", "HONDA"),
    _field("Année", "2019"),
    _field("Date du rappel", "5/28/2020 12:00:00 AM"),
]


def _summary(model: str) -> list[dict[str, object]]:
    return [
        _field("RECALL_NUMBER_NUM", "2020041"),
        _field("CATEGORY_ETXT", "SUV"),
        _field("CATEGORY_FTXT", "Véhicule utilitaire-sport"),
        _field("MAKE_NAME_NM", "HONDA"),
        _field("MODEL_NAME_NM", model),
        _field("DATE_YEAR_CD", "2020"),
        _field("UNIT_AFFECTED_NBR", "596"),
        _field("COMMENT_ETXT", "Issue: label ink."),
        _field("COMMENT_FTXT", "Problème : encre."),
        _field("RECALL_DATE_DTE", "2/6/2020 12:00:00 AM"),
    ]


async def test_search_builds_path_and_reads_positional_columns(httpx_mock):
    httpx_mock.add_response(json={"ResultSet": [_SEARCH_ROW]})
    result = await client.search(
        make="Land Rover", model="Civic", year_from=2019, year_to=2020, limit=5, page=2, lang="fr"
    )
    row = result.recalls[0]
    assert (row.recall_number, row.model, row.model_year) == ("2020236", "CIVIC", 2019)
    assert row.recall_date == date(2020, 5, 28)
    url = urlparse(str(httpx_mock.get_request().url))
    assert url.path.endswith(
        "/fra/vehicle-recall-database/recall/make-name/land%20rover/model-name/civic/year-range/2019-2020"
    )
    assert parse_qs(url.query) == {"limit": ["5"], "page": ["2"]}


async def test_get_recall_merges_vehicles_and_picks_language(httpx_mock):
    httpx_mock.add_response(json={"ResultSet": [_summary("PILOT"), _summary("PASSPORT")]})
    detail = await client.get_recall("2020041", lang="fr")
    assert detail.category == "Véhicule utilitaire-sport"
    assert detail.description == "Problème : encre."
    assert detail.units_affected == 596
    assert [v.model for v in detail.affected_vehicles] == ["PASSPORT", "PILOT"]


async def test_empty_result_set_and_validation(httpx_mock):
    httpx_mock.add_response(json={"ResultSet": []})
    with pytest.raises(NotFound):
        await client.get_recall("1")
    with pytest.raises(InvalidInput):
        await client.get_recall("abc")
    with pytest.raises(InvalidInput, match="at least"):
        await client.search()
    with pytest.raises(InvalidInput):
        await client.search(make="../etc")
    with pytest.raises(InvalidInput):
        await client.search(year_from=2020, year_to=2010)


async def test_provenance_reports_cache_hits(httpx_mock):
    httpx_mock.add_response(json={"ResultSet": [_SEARCH_ROW]})
    first = await client.search(make="Honda", year_from=2019, year_to=2019)
    second = await client.search(make="Honda", year_from=2019, year_to=2019)
    assert (first.provenance.cached, second.provenance.cached) == (False, True)
