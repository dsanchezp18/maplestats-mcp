"""Tests for ons/client.py on answers recorded live on 2026-11-08
(fixtures/): Search API answers for "d7g7", "ihyq" (one series in four
datasets) and "cpih annual rate" (where the headline L55O comes 13th), and
the /data JSON of D7G7 (MM23) and IHYQ (QNA), cut to their last 40 values
per frequency."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from maplestats_mcp.modules.ons import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH = re.compile(r"https://api\.beta\.ons\.gov\.uk/v1/search\?.*")
D7G7 = "https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7g7/mm23/data"
IHYQ = "https://www.ons.gov.uk/economy/grossdomesticproductgdp/timeseries/ihyq/qna/data"


def _json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _search(httpx_mock, q: str, name: str):
    httpx_mock.add_response(
        url=re.compile(rf"https://api\.beta\.ons\.gov\.uk/v1/search\?q={q}&.*"),
        json=_json(name),
        is_reusable=True,
    )


@pytest.fixture(autouse=True)
def _reset_block():
    client.BLOCK.reset()
    yield
    client.BLOCK.reset()


async def test_search_reranks_the_headline_first(httpx_mock):
    httpx_mock.add_response(url=SEARCH, json=_json("search_cpih.json"))
    result = await client.search_series("CPIH annual rate all items", limit=5)
    assert result.series[0].series_id == "L55O"
    assert result.series[0].dataset == "MM23"
    assert result.series[0].url.endswith("/timeseries/l55o/mm23")
    # 2026-10-20T23:00Z is 21 October in London.
    assert result.series[0].release_date == "2026-10-21"
    request = httpx_mock.get_requests()[0]
    assert request.url.params["content_type"] == "timeseries"
    assert result.provenance.commercial_use == "allowed"
    assert "Open Government Licence" in (result.provenance.licence or "")


async def test_search_needs_words():
    with pytest.raises(InvalidInput, match="English words"):
        await client.search_series("the uk")


async def test_get_series_parses_months_and_release(httpx_mock):
    _search(httpx_mock, "d7g7", "search_d7g7.json")
    httpx_mock.add_response(url=D7G7, json=_json("d7g7_mm23.json"))
    result = await client.get_series("d7g7", last_n=3)
    assert result.series_id == "D7G7" and result.dataset == "MM23"
    assert result.frequency == "monthly"
    assert result.available_frequencies == ["monthly", "quarterly", "annual"]
    assert [o.period for o in result.observations] == ["2026-07", "2026-08", "2026-09"]
    assert result.latest_value == 3.5
    assert result.unit == "%"
    assert result.next_release == "18 November 2026"
    assert "generator?format=csv" in result.csv_url
    assert result.citation.startswith("Office for National Statistics, CPI ANNUAL RATE")


async def test_get_series_annual_with_year_bounds(httpx_mock):
    _search(httpx_mock, "d7g7", "search_d7g7.json")
    httpx_mock.add_response(url=D7G7, json=_json("d7g7_mm23.json"))
    result = await client.get_series(
        "D7G7", frequency="annual", start_period="2022", end_period="2024"
    )
    assert [(o.period, o.value) for o in result.observations] == [
        ("2022", 9.1),
        ("2023", 7.3),
        ("2024", 2.5),
    ]


async def test_series_in_several_datasets_says_so(httpx_mock):
    _search(httpx_mock, "ihyq", "search_ihyq.json")
    httpx_mock.add_response(url=IHYQ, json=_json("ihyq_qna.json"))
    result = await client.get_series("IHYQ", dataset="qna", start_period="2026-Q1")
    assert result.dataset == "QNA" and result.frequency == "quarterly"
    assert result.observations[0].period == "2026-Q1"
    assert set(result.other_datasets) >= {"PN2", "UKEA"}
    assert any("also published in" in n for n in result.notes)


async def test_wrong_dataset_and_frequency(httpx_mock):
    _search(httpx_mock, "ihyq", "search_ihyq.json")
    with pytest.raises(NotFound, match="not in ONS dataset LMS"):
        await client.get_series("IHYQ", dataset="LMS")
    httpx_mock.add_response(url=IHYQ, json=_json("ihyq_qna.json"))
    with pytest.raises(InvalidInput, match="published quarterly"):
        await client.get_series("IHYQ", dataset="QNA", frequency="monthly")


async def test_unknown_series_is_not_found(httpx_mock):
    httpx_mock.add_response(
        url=SEARCH, json={"count": 0, "took": 1, "distinct_items_count": 0, "items": []}
    )
    with pytest.raises(NotFound, match="ons_search_series"):
        await client.get_series("ZZZ9")


async def test_bad_inputs_are_invalid():
    with pytest.raises(InvalidInput, match="four letters or digits"):
        await client.get_series("CPI annual")
    with pytest.raises(InvalidInput, match="not a period"):
        await client.get_series("D7G7", start_period="Sept 2026")
    with pytest.raises(InvalidInput, match="Unknown indicator"):
        await client.get_indicator("gdp")


async def test_rate_limit_blocks_later_requests(httpx_mock):
    httpx_mock.add_response(url=SEARCH, status_code=429, headers={"Retry-After": "120"})
    with pytest.raises(UpstreamUnavailable, match="429"):
        await client.search_series("unemployment rate")
    # The next call is refused without a request.
    with pytest.raises(UpstreamUnavailable, match="slow down"):
        await client.search_series("inflation")
    assert len(httpx_mock.get_requests()) == 1


async def test_indicator_names_the_canadian_counterpart(httpx_mock):
    _search(httpx_mock, "d7g7", "search_d7g7.json")
    httpx_mock.add_response(url=D7G7, json=_json("d7g7_mm23.json"))
    result = await client.get_indicator("cpi_inflation", lang="fr")
    assert len(result.observations) == 24
    assert result.indicator_label.startswith("IPC")
    assert "18-10-0004-01" in result.canada_counterpart
    assert result.citation.endswith("Open Government Licence v3.0.")
    assert "consulté le" in result.citation
