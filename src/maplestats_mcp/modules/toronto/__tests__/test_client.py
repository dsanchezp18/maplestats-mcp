"""Tests for toronto/client.py against rows recorded live on 2026-11-08.

`recorded.json` holds trimmed `datastore_search` results from
ckan0.cf.opendata.inter.prod-toronto.ca (real field lists and types, a few
real rows of each table): the 2016 profile's text values with thousands
separators and indented labels, the 2011 profile's "Attribute" column and
numeric values, RentSafeTO's text scores ("81.1") and repeat evaluations of
one building, and DineSafe's "None" inside addresses. A small fake
DataStore answers the client's requests from those rows, applying the
`filters`, `q`, `fields`, `sort` and paging it sends, so paging and the
per-column full-text query are exercised as the portal runs them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from maplestats_mcp.modules.toronto import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

RECORDED = json.loads((Path(__file__).parent / "recorded.json").read_text(encoding="utf-8"))
TABLES = {table["resource_id"]: table for table in RECORDED.values()}


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def datastore(httpx_mock):
    """Answer datastore_search from the recorded rows; returns the requests seen."""
    seen: list[dict[str, str]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        params = {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}
        seen.append(params)
        table = TABLES[params["resource_id"]]
        rows: list[dict[str, Any]] = list(table["records"])
        for column, value in json.loads(params.get("filters", "{}")).items():
            rows = [r for r in rows if str(r.get(column)) == str(value)]
        if "q" in params:
            words = json.loads(params["q"])
            rows = [
                r
                for r in rows
                if all(
                    all(w.casefold() in str(r.get(col) or "").casefold() for w in text.split())
                    for col, text in words.items()
                )
            ]
        if params.get("sort", "").startswith("inspectionDate desc"):
            rows.sort(key=lambda r: r.get("inspectionDate") or "", reverse=True)
        fields = table["fields"]
        if "fields" in params:
            wanted = params["fields"].split(",")
            fields = [f for f in fields if f["id"] in wanted]
            rows = [{k: r.get(k) for k in wanted} for r in rows]
        offset, limit = int(params.get("offset", 0)), int(params.get("limit", 100))
        result = {"records": rows[offset : offset + limit], "fields": fields, "total": len(rows)}
        return httpx.Response(200, json={"success": True, "result": result})

    httpx_mock.add_callback(answer, is_reusable=True)
    return seen


@pytest.fixture
def small_pages(monkeypatch):
    # Two rows a page, so every whole-table read crosses several pages.
    monkeypatch.setattr(constants, "PAGE_ROWS", 2)


# --- Neighbourhood Profiles -------------------------------------------------


async def test_profile_by_name_parses_values_and_levels(datastore, small_pages):
    result = await client.get_neighbourhood_profile("annex", characteristic="renter")
    assert result.neighbourhood == "Annex"
    assert result.neighbourhood_number == "95"
    renter = next(r for r in result.rows if r.characteristic == "Renter")
    assert renter.level == 1
    assert renter.value == "9,870" and renter.value_number == 9870.0
    assert renter.city_value_number == 525835.0
    assert renter.data_source == "Census Profile 98-316-X2016001"
    assert "Household characteristics" in result.topics
    assert result.source.resource_id == constants.PROFILE_TABLES[2016].resource_id
    assert "Open Government Licence - Toronto" in result.source.citation
    assert result.provenance.commercial_use == "allowed"
    # Only the neighbourhood's own column and the city's were asked for.
    paged = [p for p in datastore if p.get("sort") == "_id"]
    assert len(paged) > 1
    assert all("Regent Park" not in p["fields"] for p in paged)


async def test_profile_by_number_and_boundary_label(datastore):
    by_number = await client.get_neighbourhood_profile("72")
    by_label = await client.get_neighbourhood_profile("Regent Park (72)")
    assert by_number.neighbourhood == by_label.neighbourhood == "Regent Park"


async def test_profile_matches_names_without_punctuation(datastore):
    result = await client.get_neighbourhood_profile("mimico includes humber bay shores")
    assert result.neighbourhood == "Mimico (includes Humber Bay Shores)"


async def test_profile_topic_filter_and_city_column(datastore):
    result = await client.get_neighbourhood_profile("City of Toronto", topic="population")
    assert result.neighbourhood == "City of Toronto"
    assert [r.characteristic for r in result.rows] == ["Population, 2016", "Population, 2011"]
    assert result.rows[0].value_number == 2731571.0


async def test_profile_2011_uses_attribute_column_and_numbers(datastore):
    result = await client.get_neighbourhood_profile("Regent Park", census_year=2011, limit=2)
    assert result.rows[0].characteristic == "Population, 2011"
    assert result.rows[0].value_number == 10007.0
    assert result.rows[0].data_source is None
    assert result.total_matched == 4 and result.returned_count == 2


async def test_profile_errors(datastore):
    with pytest.raises(NotFound, match="Closest: \\['Annex'\\]"):
        await client.get_neighbourhood_profile("Anex")
    with pytest.raises(InvalidInput, match="matches several"):
        await client.get_neighbourhood_profile("park")
    with pytest.raises(InvalidInput, match="no topic matches"):
        await client.get_neighbourhood_profile("Annex", topic="weather")
    with pytest.raises(InvalidInput, match="Excel file"):
        await client.get_neighbourhood_profile("Annex", census_year=2021)


async def test_profile_french_says_english_only(datastore):
    result = await client.get_neighbourhood_profile("Annex", lang="fr")
    assert "anglais seulement" in (result.provenance.limits or "")
    assert "Licence du gouvernement ouvert – Toronto" in result.source.licence


# --- RentSafeTO -------------------------------------------------------------


async def test_latest_evaluation_per_building(datastore, small_pages):
    result = await client.get_apartment_evaluations(address="pharmacy")
    assert result.total_matched == 1
    building = result.evaluations[0]
    assert building.score == 97.0 and building.evaluation_date == "2025-08-11"
    assert building.evaluations_on_record == 2
    every = await client.get_apartment_evaluations(address="pharmacy", latest_only=False)
    assert every.total_matched == 2


async def test_evaluations_parse_decimal_scores_and_sort(datastore):
    result = await client.get_apartment_evaluations(sort="score_asc")
    scores = [e.score for e in result.evaluations if e.score is not None]
    assert 81.1 in scores
    assert scores == sorted(scores)
    newest = await client.get_apartment_evaluations(sort="date_desc", limit=1)
    assert newest.evaluations[0].evaluation_date == "2025-11-28"


async def test_ward_given_as_number_or_name(datastore):
    by_number = await client.get_apartment_evaluations(ward="5")
    by_name = await client.get_apartment_evaluations(ward="york south-weston")
    assert by_number.total_matched == by_name.total_matched > 0
    assert {e.ward for e in by_number.evaluations} == {"05"}
    with pytest.raises(InvalidInput, match="unknown ward"):
        await client.get_apartment_evaluations(ward="99")


async def test_score_summary_by_ward(datastore):
    result = await client.summarize_apartment_scores()
    assert result.buildings == sum(g.buildings for g in result.groups)
    assert result.city.min_score is not None and result.city.max_score is not None
    assert result.city.min_score <= (result.city.median_score or 0) <= result.city.max_score
    by_type = await client.summarize_apartment_scores(group_by="property_type")
    assert {g.key for g in by_type.groups} <= {"PRIVATE", "TCHC", "SOCIAL HOUSING"}


async def test_score_summary_evaluated_since(datastore):
    everything = await client.summarize_apartment_scores()
    recent = await client.summarize_apartment_scores(evaluated_since=2025)
    assert recent.buildings < everything.buildings


# --- Short-term rentals -----------------------------------------------------


async def test_rentals_counted_by_ward(datastore, small_pages):
    result = await client.summarize_short_term_rentals()
    assert result.registrations == 7
    assert sum(g.registrations for g in result.groups) == 7
    assert all(len(g.key) == 2 for g in result.groups if g.key != "unknown")
    assert abs(sum(g.share for g in result.groups) - 1.0) < 0.01


async def test_rentals_counted_by_property_type(datastore):
    result = await client.summarize_short_term_rentals(group_by="property_type")
    counts = [g.registrations for g in result.groups]
    assert counts == sorted(counts, reverse=True)


# --- DineSafe ---------------------------------------------------------------


async def test_dinesafe_query_is_per_column_and_address_cleaned(datastore):
    result = await client.search_dinesafe(establishment="hashtag india")
    assert datastore[-1]["q"] == json.dumps({"estName": "hashtag india"})
    assert result.total_matched == 2
    assert result.inspections[0].address == "1871 O'Connor Dr M4A 1X1"
    assert result.inspections[0].inspection_date == "2026-04-21"


async def test_dinesafe_status_filter(datastore):
    result = await client.search_dinesafe(status="closed")
    assert json.loads(datastore[-1]["filters"]) == {"inspectionStatus": "Closed"}
    assert result.status_filter == "Closed"
    assert all(i.status == "Closed" for i in result.inspections)
    with pytest.raises(InvalidInput, match="status must be one of"):
        await client.search_dinesafe(status="Fail")


async def test_paging_is_checked():
    with pytest.raises(InvalidInput, match="limit must be between"):
        await client.search_dinesafe(limit=0)
    with pytest.raises(InvalidInput, match="offset must be"):
        await client.get_apartment_evaluations(offset=-1)
