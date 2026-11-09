"""open.canada.ca's own dataset fields in ckan_get_dataset.

The fixtures are two package_show responses recorded live from
open.canada.ca on 2026-11-09, cut to their first two resources and
otherwise unchanged: a CRA charities list that is no longer updated
(frequency "not_planned") and a weekly lobbying report with modification
and coverage dates. They hold the portal's real quirks: bilingual fields
as bare {"en", "fr"} dicts with no `_translated` twin, empty-string
translations, dates written "YYYY-MM-DD 00:00:00", and ISO 8601
frequency codes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maplestats_mcp.modules.ckan import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.brief import shape

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _recorded(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


async def test_federal_dataset_carries_portal_fields(httpx_mock):
    httpx_mock.add_response(json=_recorded("federal_package_show_lobbying.json"))
    detail = await client.get_dataset("federal", "a34eb330-7136-4f5e-9f5f-3ba41df58b06")
    extras = detail.extras
    assert extras["frequency"] == "P1W"
    assert extras["frequency_label"] == "Weekly"
    assert extras["date_published"] == "2026-11-09"
    assert extras["date_modified"] == "2026-11-09"
    assert extras["portal_release_date"] == "2014-03-12"
    assert extras["time_period_coverage_start"] == "2008-07-02"
    assert extras["time_period_coverage_end"] == "2026-11-09"
    assert extras["org_title_at_publication"] == "Office of the Commissioner of Lobbying of Canada"
    assert extras["jurisdiction"] == "federal"
    assert extras["subject"] == ["government_and_politics", "processes"]
    assert extras["collection"] == "primary"
    assert extras["data_series_name"] == "The Registry of Lobbyists"
    # Empty upstream values are left out, not sent as {"en": "", "fr": ""} or [].
    assert "program_page_url" not in extras
    assert "data_series_issue_identification" not in extras
    assert "audience" not in extras
    assert detail.resources[0].extras == {"date_published": "2022-09-26"}


async def test_federal_fields_follow_the_language(httpx_mock):
    httpx_mock.add_response(json=_recorded("federal_package_show_charities.json"))
    detail = await client.get_dataset("federal", "7ddc811f-aa0e-41b2-acd9-ff1dcc86d807", "fr")
    extras = detail.extras
    assert extras["frequency"] == "not_planned"
    assert extras["frequency_label"] == "Non planifié (aucune mise à jour prévue)"
    assert extras["org_title_at_publication"] == "Agence du revenu du Canada"
    assert extras["program_page_url"].startswith("https://www.canada.ca/fr/")
    assert extras["time_period_coverage_start"] == "1997-01-01"
    assert extras["time_period_coverage_end"] == "1997-12-31"


async def test_federal_fields_survive_brief_results(httpx_mock):
    httpx_mock.add_response(json=_recorded("federal_package_show_charities.json"))
    detail = await client.get_dataset("federal", "7ddc811f-aa0e-41b2-acd9-ff1dcc86d807")
    brief = shape(detail.model_dump(mode="json"), "brief")
    assert brief is not None
    assert brief["extras"]["frequency"] == "not_planned"
    assert brief["extras"]["frequency_label"] == "Not planned (no further updates)"
    assert brief["extras"]["date_published"] == "2017-09-07"
    assert brief["extras"]["time_period_coverage_end"] == "1997-12-31"
    assert brief["extras"]["subject"] == ["economics_and_industry"]


@pytest.mark.parametrize(
    ("code", "en", "fr"),
    [
        ("P1D", "Daily", "Quotidien"),
        ("P1M", "Monthly", "Mensuel"),
        ("P3M", "Quarterly", "Trimestriel"),
        ("P1Y", "Annually", "Annuel"),
        ("as_needed", "As needed", "Au besoin"),
        ("irregular", "Irregular", "Irrégulier"),
    ],
)
async def test_frequency_codes_are_decoded(httpx_mock, code, en, fr):
    package = {"id": "f1", "name": "f1", "title": "T", "frequency": code, "resources": []}
    httpx_mock.add_response(json={"success": True, "result": package}, is_reusable=True)
    english = await client.get_dataset("federal", "f1")
    assert english.extras == {"frequency": code, "frequency_label": en}
    cache_module._caches.clear()
    french = await client.get_dataset("federal", "f1", "fr")
    assert french.extras["frequency_label"] == fr


async def test_unknown_frequency_code_keeps_the_code_alone(httpx_mock):
    package = {"id": "f2", "name": "f2", "title": "T", "frequency": "P7Y", "resources": []}
    httpx_mock.add_response(json={"success": True, "result": package})
    detail = await client.get_dataset("federal", "f2")
    assert detail.extras == {"frequency": "P7Y"}


async def test_year_one_placeholder_date_is_dropped(httpx_mock):
    # A federated dataset (New Brunswick) sends year 1 for an unset coverage start.
    package = {
        "id": "f3",
        "name": "f3",
        "title": "T",
        "time_period_coverage_start": "0001-01-01 00:00:00",
        "date_published": "2019-04-02 13:45:00",
        "resources": [],
    }
    httpx_mock.add_response(json={"success": True, "result": package})
    detail = await client.get_dataset("federal", "f3")
    assert detail.extras == {"date_published": "2019-04-02 13:45:00"}


def test_every_schema_frequency_has_both_labels():
    for code, labels in constants.FREQUENCY_LABELS.items():
        assert len(labels) == 2 and all(labels), code
