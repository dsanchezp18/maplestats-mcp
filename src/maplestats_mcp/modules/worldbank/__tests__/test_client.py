"""Tests for worldbank/client.py, shaped on live responses from 2026-10-03:
errors as HTTP 200 with a `message` body, null values for missing years,
newest-first rows, an ignored empty year range, topics with trailing spaces
or none at all, and 502 pages from the edge."""

from __future__ import annotations

import re

import pytest

from maplestats_mcp.modules.worldbank import client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable

CATALOGUE = re.compile(r"https://api\.worldbank\.org/v2/(en|fr)/sources/2/indicators\?.*")
DATA = re.compile(r"https://api\.worldbank\.org/v2/(en|fr)/country/.*")

_ROWS = [
    {
        "id": "NY.GDP.MKTP.KD.ZG",
        "name": "GDP growth (annual %)",
        "unit": "",
        "sourceNote": "Annual percentage growth rate of GDP at market prices.",
        "sourceOrganization": "World Bank national accounts data",
        "topics": [{"id": "3", "value": "Economy & Growth"}],
    },
    {
        "id": "NY.GDP.MKTP.CD",
        "name": "GDP (current US$)",
        "unit": "",
        "sourceNote": "GDP at purchaser's prices.",
        "sourceOrganization": "World Bank national accounts data",
        "topics": [{"id": "3", "value": "Economy & Growth"}],
    },
    {
        "id": "SL.UEM.TOTL.ZS",
        "name": "Unemployment, total (% of total labor force) (modeled ILO estimate)",
        "unit": "",
        "sourceNote": "Share of the labor force without work.",
        "sourceOrganization": "ILO Modelled Estimates database (ILOEST)",
        "topics": [
            {"id": "4", "value": "Education "},
            {"id": "10", "value": "Social Protection & Labor"},
        ],
    },
    {
        "id": "XX.NO.TOPIC",
        "name": "Indicator without topic",
        "unit": "",
        "sourceNote": "",
        "sourceOrganization": "",
        "topics": [],
    },
]


def _catalogue(rows=_ROWS):
    return [{"page": 1, "pages": 1, "per_page": "2000", "total": len(rows)}, rows]


def _row(iso, name, year, value, code="NY.GDP.MKTP.KD.ZG"):
    return {
        "indicator": {"id": code, "value": "GDP growth (annual %)"},
        "country": {"id": iso[:2], "value": name},
        "countryiso3code": iso,
        "date": str(year),
        "value": value,
        "unit": "",
        "obs_status": "",
        "decimal": 1,
    }


def _data(rows):
    header = {"page": 1, "pages": 1, "per_page": 5000, "total": len(rows)}
    header |= {"sourceid": "2", "lastupdated": "2026-07-13"}
    return [header, rows]


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


async def test_search_requires_every_word_and_ranks_name_hits(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    result = await client.search_indicators("GDP growth")
    assert [i.id for i in result.indicators] == ["NY.GDP.MKTP.KD.ZG"]
    assert result.provenance.licence and "CC BY 4.0" in result.provenance.licence


async def test_search_by_code_and_topic_name_with_trailing_space(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    by_code = await client.search_indicators("sl.uem.totl.zs")
    assert by_code.indicators[0].id == "SL.UEM.TOTL.ZS"
    by_topic = await client.search_indicators(topic="education")
    assert by_topic.topic == "Education"
    assert [i.id for i in by_topic.indicators] == ["SL.UEM.TOTL.ZS"]


async def test_list_topics_counts_and_skips_empty(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    topics = await client.list_topics()
    assert [t.id for t in topics.topics] == ["3", "4", "10"]
    assert topics.topics[0].name == "Economy & Growth (2)"


async def test_unknown_topic_and_empty_search_are_invalid(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    with pytest.raises(InvalidInput):
        await client.search_indicators()
    with pytest.raises(InvalidInput, match="Unknown WDI topic"):
        await client.search_indicators(topic="zzz")


async def test_get_indicator_not_in_wdi_is_not_found(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    detail = await client.get_indicator("SL.UEM.TOTL.ZS")
    assert detail.source_organization.startswith("ILO")
    assert detail.topics == ["Education", "Social Protection & Labor"]
    with pytest.raises(NotFound):
        await client.get_indicator("NOPE.X")


async def test_series_sorts_drops_nulls_and_ranks(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    httpx_mock.add_response(
        url=DATA,
        json=_data(
            [
                _row("CAN", "Canada", 2025, 1.7),
                _row("CAN", "Canada", 2024, 2.0),
                _row("CAN", "Canada", 2023, None),
                _row("USA", "United States", 2024, 2.8),
                _row("USA", "United States", 2025, None),
                _row("DEU", "Germany", 2024, -0.2),
                _row("OED", "OECD members", 2024, 1.8),
            ]
        ),
    )
    result = await client.get_canada_series(
        "ny.gdp.mktp.kd.zg", compare_with=["usa", "DEU", "OECD"]
    )
    request = httpx_mock.get_requests()[-1]
    assert "/country/CAN;USA;DEU;OED/indicator/NY.GDP.MKTP.KD.ZG" in str(request.url)
    canada = result.countries[0]
    assert [o.year for o in canada.observations] == [2024, 2025]
    assert canada.latest_year == 2025
    # 2025 has only Canada, so the rank uses 2024, which three countries report.
    assert (result.canada_rank, result.rank_year, result.ranked_countries) == (2, 2024, 3)
    assert any("OECD members" in n for n in result.notes)


async def test_empty_year_range_is_filtered_here(httpx_mock):
    """The API ignores date=2030:2100 and sends every year."""
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    httpx_mock.add_response(url=DATA, json=_data([_row("CAN", "Canada", 2024, 2.0)]))
    with pytest.raises(NotFound, match="no value for Canada"):
        await client.get_canada_series("NY.GDP.MKTP.KD.ZG", start_year=2030)


async def test_api_message_body_becomes_invalid_input(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    httpx_mock.add_response(
        url=DATA,
        json=[{"message": [{"id": "120", "key": "Invalid value", "value": "not valid"}]}],
    )
    with pytest.raises(InvalidInput, match="not valid"):
        await client.get_canada_series("NY.GDP.MKTP.KD.ZG")


async def test_comparisons_outside_g7_oecd_are_refused():
    with pytest.raises(InvalidInput, match="OECD"):
        await client.get_canada_series("NY.GDP.MKTP.KD.ZG", compare_with=["CHN"])
    with pytest.raises(InvalidInput):
        await client.get_canada_series("NY.GDP.MKTP.KD.ZG", start_year=2000, most_recent=3)


async def test_g7_alias_expands_without_duplicating_canada(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    httpx_mock.add_response(url=DATA, json=_data([_row("CAN", "Canada", 2024, 2.0)]))
    result = await client.get_canada_series("NY.GDP.MKTP.KD.ZG", compare_with=["G7", "USA"])
    assert "/country/CAN;USA;GBR;FRA;DEU;ITA;JPN/" in str(httpx_mock.get_requests()[-1].url)
    assert any("No values for" in n for n in result.notes)


async def test_most_recent_keeps_last_years(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    rows = [_row("CAN", "Canada", y, float(y - 2000)) for y in range(2025, 2015, -1)]
    httpx_mock.add_response(url=DATA, json=_data(rows))
    result = await client.get_canada_series("NY.GDP.MKTP.KD.ZG", most_recent=3)
    assert [o.year for o in result.countries[0].observations] == [2023, 2024, 2025]


async def test_502_edge_page_is_unavailable(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_catalogue())
    for _ in range(3):
        httpx_mock.add_response(url=DATA, status_code=502, text="<html>Bad gateway</html>")
    with pytest.raises(UpstreamUnavailable):
        await client.get_canada_series("NY.GDP.MKTP.KD.ZG")
