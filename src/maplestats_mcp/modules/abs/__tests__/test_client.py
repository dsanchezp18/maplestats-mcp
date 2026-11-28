"""Tests for abs/client.py on answers recorded live on 2026-11-08
(fixtures/): the dataflow list (9 of its 1,228 flows), the CPI structure
(the INDEX codelist and constraints cut to three codes; two release-version
constraints) and the LF structure, and SDMX-CSV 1.0 data for the
unemployment rate in two states and Australia and for the CPI (newest
first, as the API sends it). The 404 "NoRecordsFound" is the API's own."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

import pytest

from maplestats_mcp.modules.abs import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

FIXTURES = Path(__file__).parent / "fixtures"
CATALOGUE = "https://data.api.abs.gov.au/rest/dataflow/ABS/all/latest"


def _structure(fid: str) -> re.Pattern[str]:
    return re.compile(rf"https://data\.api\.abs\.gov\.au/rest/dataflow/ABS/{fid}/latest\?.*")


def _data(fid: str) -> re.Pattern[str]:
    return re.compile(rf"https://data\.api\.abs\.gov\.au/rest/data/ABS,{fid},/.*")


def _json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _mock(httpx_mock, fid: str, csv_name: str | None):
    httpx_mock.add_response(
        url=CATALOGUE, json=_json("dataflows.json"), is_optional=True, is_reusable=True
    )
    httpx_mock.add_response(
        url=_structure(fid),
        json=_json(f"structure_{fid.lower()}.json"),
        is_optional=True,
        is_reusable=True,
    )
    if csv_name:
        httpx_mock.add_response(url=_data(fid), text=_text(csv_name))


def _data_requests(httpx_mock):
    return [r for r in httpx_mock.get_requests() if "/rest/data/" in str(r.url)]


async def test_search_ranks_name_and_id_matches(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_json("dataflows.json"))
    result = await client.search_datasets("consumer price index")
    assert result.datasets[0].id == "CPI"
    assert (await client.search_datasets("wpi")).datasets[0].id == "WPI"
    assert result.provenance.commercial_use == "allowed"
    assert "Creative Commons Attribution 4.0" in (result.provenance.licence or "")


async def test_describe_merges_release_constraints_and_keys_australia(httpx_mock):
    _mock(httpx_mock, "CPI", None)
    result = await client.describe_dataset("abs,cpi")
    assert result.id == "CPI"
    assert result.key_template == "MEASURE.INDEX.TSEST.REGION.FREQ"
    # The CPI writes Australia as 50, not AUS.
    assert result.example_key == "...50."
    index = next(d for d in result.dimensions if d.id == "INDEX")
    assert {c.id for c in index.codes} == {"10001", "999902", "104101"}


async def test_unknown_dataset_is_not_found(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_json("dataflows.json"))
    with pytest.raises(NotFound, match="abs_search_datasets"):
        await client.describe_dataset("NOPE_X")


async def test_get_data_sorts_newest_first_rows_and_labels_series(httpx_mock):
    _mock(httpx_mock, "LF", "data_lf.csv")
    result = await client.get_data("LF", "m13.3.1599.20.1+2+aus.m", last_n=3)
    assert result.key == "M13.3.1599.20.1+2+AUS.M"
    assert [s.region for s in result.series] == ["New South Wales", "Victoria", "Australia"]
    australia = result.series[2]
    assert australia.adjustment == "Seasonally Adjusted" and australia.unit == "Percent"
    periods = [r.period for r in result.rows if r.series_key == australia.key]
    assert periods == sorted(periods) and periods[-1] == "2026-09"
    assert "format=csvfilewithlabels" in result.csv_url
    assert _data_requests(httpx_mock)[0].url.params["lastNObservations"] == "3"


def _lf_with_gaps(*, everything_blank: bool = False) -> str:
    """The LF answer with the ABS's way of saying a value is missing: an empty OBS_VALUE
    and an OBS_STATUS ("M: Missing value"). New South Wales loses September 2026 and
    Victoria all three months, so that series has no number at all."""
    rows = list(csv.reader(io.StringIO(_text("data_lf.csv"))))
    header, body = rows[0], rows[1:]
    region, period = header.index("REGION: Region"), header.index("TIME_PERIOD: Time Period")
    value, status = header.index("OBS_VALUE"), header.index("OBS_STATUS: Observation Status")
    for row in body:
        gone = everything_blank or (
            row[region].startswith("2:")
            or (row[region].startswith("1:") and row[period] == "2026-09")
        )
        if gone:
            row[value], row[status] = "", "M: Missing value"
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue()


async def test_values_left_out_are_counted_by_status_in_the_notes_and_limits(httpx_mock):
    _mock(httpx_mock, "LF", None)
    httpx_mock.add_response(url=_data("LF"), text=_lf_with_gaps())
    result = await client.get_data("LF", "m13.3.1599.20.1+2+aus.m", last_n=3)
    # What was returned is what it was: Victoria, with no number at all, is still not a series.
    assert [s.region for s in result.series] == ["New South Wales", "Australia"]
    sentence = next(n for n in result.notes if "no numeric value" in n)
    assert "4 observations had no numeric value" in sentence and "4 Missing value" in sentence
    assert "1 series had no numeric value at all" in sentence
    assert sentence in (result.provenance.limits or "")


async def test_values_left_out_are_worded_in_french(httpx_mock):
    _mock(httpx_mock, "LF", None)
    httpx_mock.add_response(url=_data("LF"), text=_lf_with_gaps())
    result = await client.get_data("LF", "m13.3.1599.20.1+2+aus.m", last_n=3, lang="fr")
    sentence = next(n for n in result.notes if "sans valeur numérique" in n)
    assert "4 Missing value" in sentence and "aucune valeur numérique" in sentence
    assert sentence in (result.provenance.limits or "")


async def test_an_answer_without_gaps_has_no_such_note(httpx_mock):
    _mock(httpx_mock, "LF", "data_lf.csv")
    result = await client.get_data("LF", "m13.3.1599.20.1+2+aus.m", last_n=3)
    assert not any("no numeric value" in n for n in result.notes)


async def test_an_answer_with_no_number_at_all_is_still_not_found(httpx_mock):
    _mock(httpx_mock, "LF", None)
    httpx_mock.add_response(url=_data("LF"), text=_lf_with_gaps(everything_blank=True))
    with pytest.raises(NotFound, match="has no values for key"):
        await client.get_data("LF", "m13.3.1599.20.1+2+aus.m", last_n=3)


async def test_unit_multiplier_is_kept_so_thousands_are_not_read_as_units(httpx_mock):
    _mock(httpx_mock, "LF", None)
    thousands = _text("data_lf.csv").replace("0: Units", "3: Thousands")
    httpx_mock.add_response(url=_data("LF"), text=thousands)
    result = await client.get_data("LF", "m13.3.1599.20.1+2+aus.m", last_n=3)
    assert {s.unit_multiplier for s in result.series} == {"Thousands"}


async def test_unknown_code_fails_before_a_request(httpx_mock):
    _mock(httpx_mock, "LF", None)
    with pytest.raises(InvalidInput, match="M99 is not a MEASURE code"):
        await client.get_data("LF", "M99.3.1599.20.AUS.M", last_n=1)
    assert not _data_requests(httpx_mock)


async def test_no_records_is_not_found(httpx_mock):
    _mock(httpx_mock, "LF", None)
    httpx_mock.add_response(url=_data("LF"), status_code=404, text="NoRecordsFound")
    with pytest.raises(NotFound, match="in the periods asked for"):
        await client.get_data("LF", "M13.3.1599.20.AUS.M", start_period="2040-01")


@pytest.mark.parametrize(
    ("body", "match"),
    [
        (
            "<html><body>Service temporarily unavailable</body></html>",
            "unexpected SDMX-CSV columns",
        ),
        ("", "empty body"),
        ("  \n", "empty body"),
    ],
)
async def test_a_200_that_is_not_sdmx_csv_is_an_error_and_is_not_cached(httpx_mock, body, match):
    # The body was cached before it was read, so an outage page or an empty answer sent
    # with HTTP 200 was replayed from the cache for hours, past the end of the outage.
    _mock(httpx_mock, "LF", None)
    httpx_mock.add_response(url=_data("LF"), text=body)
    with pytest.raises(UpstreamError, match=match):
        await client.get_data("LF", "m13.3.1599.20.1+2+aus.m", last_n=3)
    httpx_mock.add_response(url=_data("LF"), text=_text("data_lf.csv"))
    result = await client.get_data("LF", "m13.3.1599.20.1+2+aus.m", last_n=3)
    assert len(result.rows) > 0 and not result.provenance.cached
    assert len(_data_requests(httpx_mock)) == 2


async def test_a_header_with_no_rows_is_still_no_values(httpx_mock):
    # A well-formed answer with nothing in it stays "no values" (and may be cached).
    _mock(httpx_mock, "LF", None)
    header = _text("data_lf.csv").splitlines()[0] + "\n"
    httpx_mock.add_response(url=_data("LF"), text=header)
    with pytest.raises(NotFound, match="has no values for key"):
        await client.get_data("LF", "m13.3.1599.20.1+2+aus.m", last_n=3)


async def test_indicator_keeps_the_status_of_an_estimated_value(httpx_mock):
    # get_data keeps each observation's status; the indicator rebuilt its observations as
    # (period, value) and an estimated or provisional figure looked like any other.
    _mock(httpx_mock, "CPI", None)
    text = _text("data_cpi.csv")
    row = "2026-08,4,PCT: Percent,,,,25: Sep 2025 = 100.0"
    assert text.count(row) == 1
    httpx_mock.add_response(
        url=_data("CPI"),
        text=text.replace(row, "2026-08,4,PCT: Percent,E: Estimate,,,25: Sep 2025 = 100.0"),
    )
    result = await client.get_indicator("cpi_inflation")
    by_period = {o.period: o.status for o in result.observations}
    assert by_period["2026-08"] == "Estimate"
    assert by_period["2026-09"] is None


async def test_indicator_gives_the_canadian_counterpart(httpx_mock):
    _mock(httpx_mock, "CPI", "data_cpi.csv")
    result = await client.get_indicator("cpi_inflation", lang="fr")
    assert result.key == "3.10001.10.50.M"
    assert result.latest_period == "2026-09" and result.latest_value == 4.3
    assert result.frequency == "Monthly"
    assert result.indicator_label.startswith("IPC")
    assert "18-10-0004-01" in result.canada_counterpart
    assert result.provenance.schema_name == "abs.IndicatorResult"
    assert _data_requests(httpx_mock)[0].url.params["lastNObservations"] == "24"


async def test_indicator_carries_the_note_on_values_left_out(httpx_mock):
    _mock(httpx_mock, "CPI", None)
    gap = "2026-08,4,PCT: Percent,,"
    text = _text("data_cpi.csv")
    assert text.count(gap) == 1
    httpx_mock.add_response(
        url=_data("CPI"), text=text.replace(gap, "2026-08,,PCT: Percent,M: Missing value,")
    )
    result = await client.get_indicator("cpi_inflation")
    assert "2026-08" not in [o.period for o in result.observations]
    sentence = next(n for n in result.notes if "no numeric value" in n)
    assert "1 observation had no numeric value" in sentence and "1 Missing value" in sentence
    assert sentence in (result.provenance.limits or "")


async def test_bad_inputs_are_invalid():
    with pytest.raises(InvalidInput, match="Unknown indicator"):
        await client.get_indicator("gdp")
    with pytest.raises(InvalidInput, match="SDMX period"):
        await client.get_data("LF", "M13.3.1599.20.AUS.M", start_period="Sept 2026")
