"""How queries and places are read. Before 2026-11-06 the query had to appear as one
phrase in the title and geo_code took only numbers, so "unemployment rate Alberta",
"inflation", "GDP" and geo_code="AB" found nothing or failed (live /stats error)."""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.indicators import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput

_PLACES = ["Canada", "Newfoundland and Labrador", "Prince Edward Island", "Nova Scotia"]
_PLACES += ["New Brunswick", "Quebec", "Ontario", "Manitoba", "Saskatchewan", "Alberta"]


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield
    cache_module._caches.clear()


def _indicator(geo_code: int, en: str, fr: str | None = None) -> dict:
    return {
        "registry_number": 1,
        "indicator_number": geo_code,
        "geo_code": geo_code,
        "title": {"en": en, "fr": fr or en},
        "value": {"en": "1", "fr": "1"},
    }


_FEED = {
    "results": {
        "geo": [
            {"geo_code": str(code), "label": {"en": name, "fr": name}}
            for code, name in enumerate(_PLACES)
        ],
        "indicators": [
            _indicator(0, "Unemployment rate", "Taux de chômage"),
            _indicator(9, "Unemployment rate", "Taux de chômage"),
            _indicator(5, "Unemployment rate", "Taux de chômage"),
            _indicator(0, "Consumer Price Index", "Indice des prix à la consommation"),
            _indicator(0, "Real GDP – Canada"),
            _indicator(9, "Annual real gross domestic product by industry"),
            _indicator(0, "Quarterly population estimate"),
            _indicator(0, "Rate of unemployment, experimental"),
        ],
    }
}


@pytest.fixture
def feed(httpx_mock):
    httpx_mock.add_response(url=constants.DATASET_URLS["all"], json=_FEED, is_reusable=True)


def _titles(result) -> list[tuple[str, int]]:
    return [(i.title, i.geo_code) for i in result.indicators]


async def test_words_match_in_any_order_and_the_phrase_comes_first(feed):
    result = await client.get_indicators(query="rate unemployment")
    assert result.total_matched == 4
    result = await client.get_indicators(query="unemployment rate")
    assert result.indicators[0].title == "Unemployment rate"
    assert result.indicators[-1].title == "Rate of unemployment, experimental"


async def test_a_place_in_the_query_filters_by_it(feed):
    result = await client.get_indicators(query="unemployment rate Alberta")
    assert _titles(result) == [("Unemployment rate", 9)]
    assert "geo_code 9" in (result.provenance.limits or "")


async def test_a_capitalized_abbreviation_in_the_query_filters_by_it(feed):
    result = await client.get_indicators(query="AB unemployment")
    assert _titles(result) == [("Unemployment rate", 9)]


async def test_lowercase_short_words_are_not_read_as_places(feed):
    result = await client.get_indicators(query="rate on unemployment")
    assert result.total_matched == 4


async def test_an_explicit_geo_code_wins_over_the_query(feed):
    result = await client.get_indicators(query="unemployment rate Alberta", geo_code=5)
    assert result.total_matched == 0


@pytest.mark.parametrize("place", ["AB", "ab", "Alberta", "alberta", "9", "48"])
async def test_geo_code_takes_names_abbreviations_and_numbers_as_text(feed, place):
    result = await client.get_indicators(query="unemployment", geo_code=place)
    assert _titles(result) == [("Unemployment rate", 9)]


async def test_geo_code_with_accents(feed):
    result = await client.get_indicators(query="unemployment", geo_code="Québec")
    assert _titles(result) == [("Unemployment rate", 5)]


async def test_an_unknown_place_name_is_rejected_with_the_valid_list(feed):
    with pytest.raises(InvalidInput, match="9=Alberta"):
        await client.get_indicators(geo_code="Atlantis")


@pytest.mark.parametrize(
    ("query", "title"),
    [
        ("CPI", "Consumer Price Index"),
        ("inflation", "Consumer Price Index"),
        ("GDP", "Real GDP – Canada"),
        ("population estimates", "Quarterly population estimate"),
    ],
)
async def test_aliases_and_plurals(feed, query, title):
    result = await client.get_indicators(query=query, geo_code=0)
    assert title in [i.title for i in result.indicators]


async def test_gdp_finds_gross_domestic_product(feed):
    result = await client.get_indicators(query="GDP Alberta")
    assert _titles(result) == [("Annual real gross domestic product by industry", 9)]


async def test_french_query_without_accents(feed):
    result = await client.get_indicators(query="taux de chomage", lang="fr", geo_code=0)
    assert _titles(result) == [("Taux de chômage", 0)]


async def test_no_match_for_a_place_says_where_it_is_published(feed):
    result = await client.get_indicators(query="consumer price index", geo_code=48)
    assert result.total_matched == 0
    limits = result.provenance.limits or ""
    assert "published for Canada" in limits and "wds_search_cubes" in limits


async def test_no_match_lists_titles_holding_some_words(feed):
    result = await client.get_indicators(query="unemployment widgets")
    assert "Unemployment rate" in (result.provenance.limits or "")


async def test_no_match_at_all_points_to_the_tables(feed):
    result = await client.get_indicators(query="zzzz")
    assert "wds_search_cubes" in (result.provenance.limits or "")


async def test_a_limit_above_the_maximum_is_lowered_and_noted(feed):
    result = await client.get_indicators(limit=constants.SEARCH_LIMIT_MAX + 200)
    assert result.returned_count == len(_FEED["results"]["indicators"])
    assert "lowered to the maximum" in (result.provenance.limits or "")
