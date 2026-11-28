"""Tests for imf/client.py on responses recorded live on 2026-11-18 (fixtures/):
the two dataflow lists (8 of 195 and 4 of 11 flows), the CPI structure (7 concept
schemes and 48 codelists cut to the concepts the dimensions use and a few codes
each) and the CPI answer for Canada as the API sent it (SDMX-ML structure-specific
XML: 2026-M08 = 169.8, 2026-M09 = 170). The error statuses are the ones the API sent
or another client recorded for it (404 unknown flow, 400 unknown value)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from maplestats_mcp.modules.imf import client, constants
from maplestats_mcp.shared.errors import (
    CloudflareChallenge,
    InvalidInput,
    NotFound,
    TooLarge,
    UpstreamError,
    UpstreamUnavailable,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://api.imf.org/external/sdmx/2.1/"
STA_LIST = re.compile(r"https://api\.imf\.org/external/sdmx/2\.1/dataflow/IMF\.STA$")
RES_LIST = re.compile(r"https://api\.imf\.org/external/sdmx/2\.1/dataflow/IMF\.RES$")
CPI_STRUCTURE = re.compile(
    r"https://api\.imf\.org/external/sdmx/2\.1/dataflow/IMF\.STA/CPI/latest\?references=all"
)
CPI_DATA = re.compile(r"https://api\.imf\.org/external/sdmx/2\.1/data/IMF\.STA,CPI/.*")
KEY = "CAN.CPI._T.IX.M"


def _json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _mock(httpx_mock, data: bool = True):
    httpx_mock.add_response(
        url=STA_LIST, json=_json("dataflows_sta.json"), is_optional=True, is_reusable=True
    )
    httpx_mock.add_response(
        url=RES_LIST, json=_json("dataflows_res.json"), is_optional=True, is_reusable=True
    )
    httpx_mock.add_response(
        url=CPI_STRUCTURE, json=_json("structure_cpi.json"), is_optional=True, is_reusable=True
    )
    if data:
        httpx_mock.add_response(url=CPI_DATA, content=_bytes("data_cpi_can.xml"))


def _data_requests(httpx_mock):
    return [r for r in httpx_mock.get_requests() if "/data/" in str(r.url)]


# ------------------------------------------------------------------ search


async def test_search_ranks_name_matches_and_hides_vintages(httpx_mock):
    _mock(httpx_mock, data=False)
    result = await client.search_datasets("consumer price index")
    ids = [d.id for d in result.datasets]
    assert ids[0] == "CPI" and "CPI_WCA" in ids
    cpi = result.datasets[0]
    assert (
        cpi.agency == "IMF.STA" and cpi.browse_url == "https://data.imf.org/en/datasets/IMF.STA:CPI"
    )
    assert "ANEA_2026_APR_VINTAGE" not in ids
    assert any("vintage" in n and "left out" in n for n in result.notes)
    assert any("not Statistics Canada's" in n for n in result.notes)
    # The licence says what the IMF allows and what it asks, and results are classed so.
    assert result.provenance.commercial_use == "not_allowed"
    licence = result.provenance.licence or ""
    assert "copyright@imf.org" in licence and "bulk download" in licence
    assert "Users may download, extract, copy" in licence


async def test_search_finds_the_research_agency_and_vintages_on_request(httpx_mock):
    _mock(httpx_mock, data=False)
    weo = await client.search_datasets("world economic outlook")
    assert weo.datasets[0].id == "WEO" and weo.datasets[0].agency == "IMF.RES"
    vintages = await client.search_datasets("national economic accounts vintage")
    assert any(d.id == "ANEA_2026_APR_VINTAGE" for d in vintages.datasets)
    # Two lists, read once for both searches.
    assert len(httpx_mock.get_requests()) == 2


async def test_search_needs_english_words_and_a_sane_limit(httpx_mock):
    with pytest.raises(InvalidInput, match="English words"):
        await client.search_datasets("the of")
    with pytest.raises(InvalidInput, match="anglais"):
        await client.search_datasets("  ", lang="fr")
    with pytest.raises(InvalidInput, match="limit"):
        await client.search_datasets("cpi", limit=500)
    assert not httpx_mock.get_requests()


# --------------------------------------------------------------- structure


async def test_describe_reads_dimensions_through_concepts_and_codelists(httpx_mock):
    _mock(httpx_mock, data=False)
    result = await client.describe_dataset("imf.sta,cpi")
    assert result.id == "CPI" and result.agency == "IMF.STA" and result.version == "5.0.0"
    assert result.key_template == "COUNTRY.INDEX_TYPE.COICOP_1999.TYPE_OF_TRANSFORMATION.FREQUENCY"
    assert result.example_key == "CAN...."
    country = result.dimensions[0]
    assert country.name == "Country" and {c.id for c in country.codes} == {"CAN", "USA", "GBR"}
    frequency = result.dimensions[4]
    assert frequency.position == 5 and ("M", "Monthly") in [(c.id, c.name) for c in frequency.codes]
    assert result.citation.startswith("International Monetary Fund (")
    assert "does not publish which" in (result.provenance.coverage or "")


async def test_describe_in_french_uses_the_codelists_french_names(httpx_mock):
    _mock(httpx_mock, data=False)
    result = await client.describe_dataset("CPI", lang="fr")
    names = {c.id: c.name for c in result.dimensions[4].codes}
    assert names["M"] == "Mensuel"
    assert result.citation.startswith("Fonds monétaire international (")


async def test_unknown_dataset_or_wrong_agency_is_not_found(httpx_mock):
    _mock(httpx_mock, data=False)
    with pytest.raises(NotFound, match="imf_search_datasets"):
        await client.describe_dataset("NOPE")
    with pytest.raises(NotFound):
        await client.describe_dataset("IMF.RES,CPI")
    with pytest.raises(InvalidInput, match="not an IMF dataset id"):
        await client.describe_dataset("consumer prices")


# --------------------------------------------------------------------- data


async def test_get_data_parses_xml_rows_dimensions_and_update_date(httpx_mock):
    _mock(httpx_mock)
    result = await client.get_data("CPI", "can.cpi._t.ix.m", last_n=2)
    # Codes are normalised to the API's case, and the XML default media type is asked for.
    assert result.key == KEY
    request = _data_requests(httpx_mock)[0]
    assert "/data/IMF.STA,CPI/CAN.CPI._T.IX.M" in str(request.url)
    assert request.url.params["lastNObservations"] == "2"
    assert request.headers["accept"] == "application/xml"
    assert [(r.period, r.value) for r in result.rows] == [("2026-M08", 169.8), ("2026-M09", 170.0)]
    series = result.series[0]
    assert series.key == KEY and series.frequency == "Monthly" and series.scale == "0"
    assert (series.latest_period, series.latest_value, series.observation_count) == (
        "2026-M09",
        170.0,
        2,
    )
    assert series.label == "Canada; Consumer price index (CPI); All Items; Index; Monthly"
    assert result.provenance.as_of is not None and result.provenance.as_of.year == 2026
    assert result.provenance.as_of.month == 11
    assert result.provenance.commercial_use == "not_allowed"
    assert any("not Statistics Canada's" in n for n in result.notes)
    assert "IMF.STA:CPI" in result.citation


async def test_get_data_passes_periods_and_pads_a_short_key(httpx_mock):
    _mock(httpx_mock)
    await client.get_data("CPI", "CAN", start_period="2026-M01", end_period="2026-M09")
    request = _data_requests(httpx_mock)[0]
    assert str(request.url).split("?")[0].endswith("/data/IMF.STA,CPI/CAN....")
    assert request.url.params["startPeriod"] == "2026-M01"
    assert request.url.params["endPeriod"] == "2026-M09"


async def test_get_data_refuses_a_key_that_could_match_too_much(httpx_mock):
    _mock(httpx_mock, data=False)
    with pytest.raises(InvalidInput, match="last_n or start_period"):
        await client.get_data("CPI", "")
    assert not _data_requests(httpx_mock)


async def test_unknown_code_long_key_and_bad_period_fail_before_a_request(httpx_mock):
    _mock(httpx_mock, data=False)
    with pytest.raises(InvalidInput, match="ZZZ is not a COUNTRY code"):
        await client.get_data("CPI", "ZZZ.CPI._T.IX.M", last_n=1)
    with pytest.raises(InvalidInput, match="6 parts but CPI has 5 dimensions"):
        await client.get_data("CPI", "CAN.CPI._T.IX.M.X", last_n=1)
    with pytest.raises(InvalidInput, match="SDMX period"):
        await client.get_data("CPI", KEY, start_period="last year")
    assert not _data_requests(httpx_mock)


async def test_data_in_french_labels_codes_in_french(httpx_mock):
    _mock(httpx_mock)
    result = await client.get_data("CPI", KEY, last_n=2, lang="fr")
    assert result.series[0].frequency == "Mensuel"
    assert any("Statistique Canada" in n for n in result.notes)
    assert (result.provenance.licence or "").startswith("Source : Fonds monétaire international")
    assert result.citation.startswith("Fonds monétaire international (")


async def test_no_data_404_and_empty_answer_are_not_found(httpx_mock):
    _mock(httpx_mock, data=False)
    httpx_mock.add_response(url=CPI_DATA, status_code=404, text="No results")
    with pytest.raises(NotFound, match="in the periods asked for"):
        await client.get_data("CPI", KEY, start_period="2040")
    empty = (
        b"<?xml version='1.0'?><message:StructureSpecificData "
        b'xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message">'
        b"<message:DataSet/></message:StructureSpecificData>"
    )
    httpx_mock.add_response(url=CPI_DATA, content=empty)
    with pytest.raises(NotFound, match="no values for key"):
        await client.get_data("CPI", "USA.CPI._T.IX.M", last_n=1)


async def test_unreadable_and_hostile_xml_is_an_upstream_error(httpx_mock):
    _mock(httpx_mock, data=False)
    httpx_mock.add_response(url=CPI_DATA, content=b"<not xml")
    with pytest.raises(UpstreamError, match="not readable XML"):
        await client.get_data("CPI", KEY, last_n=1)
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'
    httpx_mock.add_response(url=CPI_DATA, content=bomb)
    with pytest.raises(UpstreamError, match="not readable XML"):
        await client.get_data("CPI", "USA.CPI._T.IX.M", last_n=1)


async def test_rejected_unavailable_and_challenged_answers(httpx_mock):
    _mock(httpx_mock, data=False)
    httpx_mock.add_response(url=CPI_DATA, status_code=400, text="Could not resolve")
    with pytest.raises(InvalidInput, match="rejected the request"):
        await client.get_data("CPI", KEY, last_n=1)
    for _ in range(3):
        httpx_mock.add_response(url=CPI_DATA, status_code=503, text="unavailable")
    with pytest.raises(UpstreamUnavailable, match="did not answer"):
        await client.get_data("CPI", "USA.CPI._T.IX.M", last_n=1)
    httpx_mock.add_response(
        url=CPI_DATA,
        status_code=403,
        headers={"cf-mitigated": "challenge"},
        text="<html>Just a moment...</html>",
    )
    with pytest.raises(CloudflareChallenge):
        await client.get_data("CPI", "GBR.CPI._T.IX.M", last_n=1)


async def test_an_answer_over_the_byte_cap_is_refused_not_cut(httpx_mock, monkeypatch):
    _mock(httpx_mock, data=False)
    monkeypatch.setattr(constants, "MAX_DATA_BYTES", 1_000)
    httpx_mock.add_response(url=CPI_DATA, content=_bytes("data_cpi_can.xml"))
    with pytest.raises(TooLarge):
        await client.get_data("CPI", KEY, last_n=2)


async def test_rows_over_the_cap_keep_the_last_of_each_series(httpx_mock, monkeypatch):
    _mock(httpx_mock)
    monkeypatch.setattr(constants, "MAX_ROWS", 1)
    result = await client.get_data("CPI", KEY, last_n=2)
    assert [r.period for r in result.rows] == ["2026-M09"]
    assert any("only the last 1 of each series" in n for n in result.notes)


async def test_a_cut_history_keeps_its_note_on_a_repeat_call(httpx_mock, monkeypatch):
    # get_data cut the series it got from the cache in place, so a second call inside
    # the cache time saw series already short enough, found the rows under the cap and
    # dropped the "only the last N" note: a silently cut history.
    _mock(httpx_mock)
    monkeypatch.setattr(constants, "MAX_ROWS", 1)
    first = await client.get_data("CPI", KEY, last_n=2)
    second = await client.get_data("CPI", KEY, last_n=2)
    assert len(_data_requests(httpx_mock)) == 1  # the second answer came from the cache
    for result in (first, second):
        assert [r.period for r in result.rows] == ["2026-M09"]
        assert any("only the last 1 of each series" in n for n in result.notes)
        assert result.provenance.limits is not None
    # The cut is on the answer, not on the cached series: a caller with room to spare
    # still gets both rows from the same cached answer.
    monkeypatch.setattr(constants, "MAX_ROWS", 100)
    full = await client.get_data("CPI", KEY, last_n=2)
    assert [r.period for r in full.rows] == ["2026-M08", "2026-M09"]
    assert not any("only the last" in n for n in full.notes)


def _data_xml(*observations: str) -> bytes:
    obs = "".join(f"<Obs {o}/>" for o in observations)
    return (
        "<?xml version='1.0'?><message:StructureSpecificData "
        'xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message">'
        '<message:DataSet UPDATE_DATE="2026-11-18T07:43:27Z">'
        '<Series COUNTRY="CAN" INDEX_TYPE="CPI" COICOP_1999="_T" '
        f'TYPE_OF_TRANSFORMATION="IX" FREQUENCY="M">{obs}</Series>'
        "</message:DataSet></message:StructureSpecificData>"
    ).encode()


async def test_a_nan_observation_is_no_value_not_the_latest_value(httpx_mock):
    # float("NaN") parses, so an observation written OBS_VALUE="NaN" became the latest
    # value: latest_period moved to the empty period and the value went out as null.
    _mock(httpx_mock, data=False)
    httpx_mock.add_response(
        url=CPI_DATA,
        content=_data_xml(
            'TIME_PERIOD="2026-M08" OBS_VALUE="169.8"',
            'TIME_PERIOD="2026-M09" OBS_VALUE="170"',
            'TIME_PERIOD="2026-M10" OBS_VALUE="NaN"',
            'TIME_PERIOD="2026-M11" OBS_VALUE="inf"',
        ),
    )
    result = await client.get_data("CPI", KEY, last_n=4)
    assert [(r.period, r.value) for r in result.rows] == [("2026-M08", 169.8), ("2026-M09", 170.0)]
    series = result.series[0]
    assert (series.latest_period, series.latest_value, series.observation_count) == (
        "2026-M09",
        170.0,
        2,
    )


# ------------------------------------------------------------ search_series


async def test_search_series_lists_canadas_series_with_latest_values(httpx_mock):
    _mock(httpx_mock)
    result = await client.search_series("CPI")
    request = _data_requests(httpx_mock)[0]
    assert str(request.url).split("?")[0].endswith("/data/IMF.STA,CPI/CAN....")
    assert request.url.params["lastNObservations"] == "1"
    assert result.country == "CAN" and result.total_matches == 1
    found = result.series[0]
    assert found.key == KEY and found.latest_period == "2026-M09" and found.latest_value == 170.0
    assert any("not Statistics Canada's" in n for n in result.notes)
    assert result.provenance.commercial_use == "not_allowed"


async def test_search_series_filters_by_every_word(httpx_mock):
    _mock(httpx_mock)
    hit = await client.search_series("CPI", query="index monthly")
    assert hit.total_matches == 1
    httpx_mock.add_response(url=CPI_DATA, content=_bytes("data_cpi_can.xml"))
    # Another country code, the same answer: the words, not the code, decide the match.
    miss = await client.search_series("CPI", query="weights", country="usa")
    assert miss.total_matches == 0 and miss.series == []


async def test_search_series_checks_country_and_limit(httpx_mock):
    _mock(httpx_mock, data=False)
    with pytest.raises(InvalidInput, match="not an IMF country code"):
        await client.search_series("CPI", country="not a code")
    with pytest.raises(InvalidInput, match="ZZZ is not a COUNTRY code"):
        await client.search_series("CPI", country="ZZZ")
    with pytest.raises(InvalidInput, match="limit"):
        await client.search_series("CPI", limit=0)
    assert not _data_requests(httpx_mock)


def test_update_dates_with_nine_fractional_digits_are_read():
    when = client._when("2026-11-18T07:43:27.119173800Z")
    assert when is not None and (when.year, when.month, when.day) == (2026, 11, 18)
    assert client._when("not a date") is None and client._when(None) is None


def test_weo_results_carry_a_projection_note():
    assert any("projections" in n for n in client._dataset_notes("WEO", "en"))
    assert any("projections" in n for n in client._dataset_notes("WEO_2026_APR_VINTAGE", "fr"))
    assert client._dataset_notes("CPI", "en") == []
