"""Tests for modules/tc_recalls/client.py, shaped on live 2026-09-23 responses."""

from __future__ import annotations

import re
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


def _row(number: str, day: str) -> list[dict[str, object]]:
    return [
        _field("Recall number", number),
        _field("Manufacturer Name", "FORD"),
        _field("Model name", "F-150"),
        _field("Make name", "FORD"),
        _field("Year", "2020"),
        _field("Recall date", day),
    ]


async def test_search_builds_path_and_reads_positional_columns(httpx_mock):
    httpx_mock.add_response(url=re.compile(r".*2019-2020\?.*"), json={"ResultSet": [_SEARCH_ROW]})
    result = await client.search(
        make="Land Rover", model="Civic", year_from=2019, year_to=2020, limit=5, lang="fr"
    )
    row = result.recalls[0]
    assert (row.recall_number, row.model, row.model_year) == ("2020236", "CIVIC", 2019)
    assert row.recall_date == date(2020, 5, 28)
    assert (result.total_matched, result.has_more) == (1, False)
    url = urlparse(str(httpx_mock.get_requests()[-1].url))
    assert url.path.endswith(
        "/fra/vehicle-recall-database/recall/make-name/land%20rover/model-name/civic/year-range/2019-2020"
    )
    # Every matching row is read (pages of 5000) so the result can be sorted.
    assert parse_qs(url.query) == {"limit": ["5000"], "page": ["1"]}


async def test_search_is_newest_first_with_a_total(httpx_mock):
    # Live 2026-10-03: a make-only Ford search came back oldest first (1975)
    # with no total, so recent recalls were out of reach.
    rows = [_row("1975001", "1/2/1975 12:00:00 AM"), _row("2026100", "9/1/2026 12:00:00 AM")]
    rows.append(_row("2010050", "3/3/2010 12:00:00 AM"))
    httpx_mock.add_response(json={"ResultSet": rows})
    result = await client.search(make="Ford", limit=2)
    assert [r.recall_number for r in result.recalls] == ["2026100", "2010050"]
    assert (result.total_matched, result.has_more, result.order) == (3, True, "newest")
    assert "recalls 1 to 2 of 3" in (result.provenance.limits or "")
    oldest = await client.search(make="Ford", limit=2, order="oldest", page=2)
    assert [r.recall_number for r in oldest.recalls] == ["2026100"]
    assert oldest.has_more is False


async def test_unknown_make_is_invalid_input(httpx_mock):
    httpx_mock.add_response(json={"ResultSet": []})
    with pytest.raises(InvalidInput, match="check the spelling"):
        await client.search(make="Hondaa")


async def test_known_make_without_a_matching_model_gets_a_note(httpx_mock):
    httpx_mock.add_response(url=re.compile(r".*/model-name/.*"), json={"ResultSet": []})
    httpx_mock.add_response(
        url=re.compile(r".*/make-name/ford\?.*"), json={"ResultSet": [_row("1", "1/1/2020")]}
    )
    result = await client.search(make="Ford", model="NoSuchModel")
    assert result.total_matched == 0
    assert result.note is not None and "model spelling" in result.note


async def test_description_line_breaks_are_lf(httpx_mock):
    summary = _summary("PILOT")
    summary[7] = _field("COMMENT_ETXT", "Issue: label ink.\r\nRisk: none.\r\n")
    httpx_mock.add_response(json={"ResultSet": [summary]})
    detail = await client.get_recall("2020041")
    assert detail.description == "Issue: label ink.\nRisk: none."


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
    httpx_mock.add_response(url=re.compile(r".*page=1.*"), json={"ResultSet": [_SEARCH_ROW]})
    first = await client.search(make="Honda", year_from=2019, year_to=2019)
    second = await client.search(make="Honda", year_from=2019, year_to=2019)
    assert (first.provenance.cached, second.provenance.cached) == (False, True)


async def test_french_note_errors_and_provenance(httpx_mock):
    httpx_mock.add_response(json={"ResultSet": [_SEARCH_ROW]})
    result = await client.search(make="Honda", lang="fr")
    assert result.recalls[0].make == "HONDA"
    assert result.note is not None and "sans traduction" in result.note
    assert "identiques en français et en anglais\xa0:" in result.note
    assert (result.provenance.limits or "").startswith("Requête\xa0: GET")
    assert "Licence du gouvernement ouvert – Canada" in (result.provenance.licence or "")
    with pytest.raises(InvalidInput, match=r"Entrée invalide\xa0: indiquez au moins"):
        await client.search(lang="fr")
    with pytest.raises(InvalidInput, match="inversez-les"):
        await client.search(year_from=2020, year_to=2010, lang="fr")
    with pytest.raises(InvalidInput, match="composé de chiffres"):
        await client.get_recall("abc", lang="fr")


async def test_french_not_found(httpx_mock):
    httpx_mock.add_response(json={"ResultSet": []})
    with pytest.raises(NotFound, match="aucun rappel 1 chez Transports Canada"):
        await client.get_recall("1", lang="fr")


async def test_english_messages_are_unchanged(httpx_mock):
    httpx_mock.add_response(json={"ResultSet": [_SEARCH_ROW]})
    result = await client.search(make="Honda")
    assert result.note is None
    assert (result.provenance.limits or "").startswith("Request: GET")
    assert (result.provenance.licence or "").startswith("Open Government Licence")
    with pytest.raises(InvalidInput) as info:
        await client.search(year_from=2020, year_to=2010)
    assert str(info.value) == (
        "year_from (2020) is after year_to (2010); swap them or widen the range."
    )
    with pytest.raises(InvalidInput) as info:
        await client.search()
    assert str(info.value) == "Give at least a make, a model, or a model-year range."
