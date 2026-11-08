"""Tests for bls/client.py against responses recorded live on 2026-11-07 (fixtures/):
"-" for a month with no value (October 2025, the appropriations lapse), the
year range silently cut to the oldest 10 years, an unknown id answered with an
empty series and a message, catalog refused without a key, preliminary
footnotes, the survey list and popular series."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from maplestats_mcp.modules.bls import client, constants
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable

FIXTURES = Path(__file__).parent / "fixtures"
DATA = re.compile(r"https://api\.bls\.gov/publicAPI/v2/timeseries/data/")
SURVEYS = re.compile(r"https://api\.bls\.gov/publicAPI/v2/surveys$")
POPULAR = re.compile(r"https://api\.bls\.gov/publicAPI/v2/timeseries/popular.*")


@pytest.fixture(autouse=True)
def _limit_not_reached(monkeypatch):
    monkeypatch.setattr(client, "_exhausted_on", None)


def _fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _bodies(httpx_mock):
    return [json.loads(r.content) for r in httpx_mock.get_requests() if r.method == "POST"]


async def test_missing_value_and_changes(httpx_mock):
    httpx_mock.add_response(url=DATA, method="POST", json=_fixture("data_missing_value.json"))
    result = await client.get_series(["LNS14000000", "CUUR0000SA0"], 2024, 2026)

    unemployment, cpi = result.series
    october = next(o for o in unemployment.observations if o.date == "2025-10")
    assert october.value is None
    assert "lapse in appropriations" in october.footnotes[0]
    november = next(o for o in unemployment.observations if o.date == "2025-11")
    assert november.change_from_previous is None  # previous month has no value
    assert unemployment.seasonal_adjustment == "seasonally adjusted"
    assert unemployment.title == "Unemployment rate, 16 years and over"
    assert unemployment.release and unemployment.release.schedule_url.endswith("empsit.htm")
    assert unemployment.observations[0].date < unemployment.observations[-1].date

    assert cpi.seasonal_adjustment == "not seasonally adjusted"
    assert cpi.frequency == "monthly"
    latest = cpi.observations[-1]
    assert cpi.latest_date == latest.date and latest.value is not None
    year_ago = next(
        o for o in cpi.observations if o.year == latest.year - 1 and o.period == latest.period
    )
    assert year_ago.value is not None
    assert latest.pct_change_from_year_ago == pytest.approx(
        round((latest.value / year_ago.value - 1) * 100, 2)
    )
    assert not any("catalog has been disabled" in n for n in result.notes)
    assert "public domain" in (result.provenance.licence or "")


async def test_long_range_is_fetched_newest_chunk_first(httpx_mock):
    # The recorded answer to a 2012-2026 request: only 2012-2021 came back.
    httpx_mock.add_response(url=DATA, method="POST", json=_fixture("data_truncated_years.json"))
    httpx_mock.add_response(url=DATA, method="POST", json=_fixture("data_truncated_years.json"))
    result = await client.get_series(["CES0000000001", "XXX123", "CUSR0000SA0L1E"], 2007, 2026)

    bodies = _bodies(httpx_mock)
    assert [(b["startyear"], b["endyear"]) for b in bodies] == [("2017", "2026"), ("2007", "2016")]
    assert [s.series_id for s in result.series] == ["CES0000000001", "CUSR0000SA0L1E"]
    assert any("XXX123" in n for n in result.notes)
    assert not any("Year range" in n for n in result.notes)


async def test_range_beyond_three_chunks_is_trimmed(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(url=DATA, method="POST", json=_fixture("data_missing_value.json"))
    result = await client.get_series(["LNS14000000"], 1980, 2026)
    assert len(_bodies(httpx_mock)) == 3
    assert result.start_year == 1997
    assert "1980 to 1996" in result.notes[0]


async def test_no_registration_is_sent_and_limits_are_stated(httpx_mock):
    httpx_mock.add_response(url=DATA, method="POST", json=_fixture("data_missing_value.json"))
    result = await client.get_series(["LNS14000000"], 2017, 2026)
    body = _bodies(httpx_mock)[0]
    assert "registrationkey" not in body and "catalog" not in body
    limits = result.provenance.limits or ""
    assert "25 queries a day" in limits and "10 years per query" in limits


async def test_unknown_series_only_is_not_found(httpx_mock):
    payload = _fixture("data_truncated_years.json")
    payload["Results"]["series"] = [
        s for s in payload["Results"]["series"] if s["seriesID"] == "XXX123"
    ]
    httpx_mock.add_response(url=DATA, method="POST", json=payload)
    with pytest.raises(NotFound, match="XXX123"):
        await client.get_series(["XXX123"], 2020, 2021)


async def test_daily_threshold_is_unavailable_with_key_hint(httpx_mock):
    httpx_mock.add_response(
        url=DATA,
        method="POST",
        json={
            "status": "REQUEST_NOT_PROCESSED",
            "responseTime": 10,
            "message": [
                (
                    # Wording recorded live on 2026-11-07 (two spaces: no key).
                    "Request could not be serviced, as the daily threshold for total number "
                    "of requests allocated to the user with registration key  has been reached."
                )
            ],
            "Results": {},
        },
    )
    with pytest.raises(UpstreamUnavailable, match="25 queries a day") as caught:
        await client.get_series(["LNS14000000"], 2025, 2026)
    assert "Fix:" in str(caught.value)
    # BLS answers 200, so nothing else stops the next call: it fails locally.
    with pytest.raises(UpstreamUnavailable, match="no query was sent"):
        await client.get_series(["CUSR0000SA0"], 2025, 2026)
    assert len(_bodies(httpx_mock)) == 1


async def test_input_checks():
    with pytest.raises(InvalidInput):
        await client.get_series(["CPI all items"])
    with pytest.raises(InvalidInput, match="25"):
        await client.get_series([f"LNS1400000{i:02d}" for i in range(26)])
    with pytest.raises(InvalidInput):
        await client.get_series(["LNS14000000"], 2026, 2020)
    with pytest.raises(InvalidInput, match="indicateur inconnu"):
        await client.get_indicator("gdp", lang="fr")


async def test_indicator_picks_adjusted_or_not(httpx_mock):
    httpx_mock.add_response(url=DATA, method="POST", json=_fixture("data_known_series_2026.json"))
    result = await client.get_indicator("cpi_core", seasonally_adjusted=False, lang="fr")
    assert _bodies(httpx_mock)[0]["seriesid"] == ["CUUR0000SA0L1E"]
    assert not result.seasonally_adjusted
    assert result.series.seasonal_adjustment == "non désaisonnalisé"
    assert result.series.latest_value == pytest.approx(339.287)
    assert any("12 mois" in n for n in result.notes)


async def test_preliminary_and_quarterly(httpx_mock):
    httpx_mock.add_response(url=DATA, method="POST", json=_fixture("data_known_series_2026.json"))
    result = await client.get_series(
        ["CEU0000000001", "CIU1010000000000A", "SUUR0000SA0"], 2026, 2026
    )
    payroll, eci, chained = result.series
    assert payroll.observations[-1].preliminary
    assert eci.frequency == "quarterly" and eci.latest_date == "2026-Q3"
    assert chained.observations[-1].preliminary  # footnote I, "Initial"


async def test_surveys_and_popular_search(httpx_mock):
    httpx_mock.add_response(url=SURVEYS, json=_fixture("surveys.json"))
    surveys = await client.list_surveys()
    assert any(s.code == "CU" for s in surveys.surveys)

    httpx_mock.add_response(url=POPULAR, json=_fixture("popular_cu.json"))
    found = await client.search_series("core", survey="cu")
    assert found.matches[0].series_id in {"CUSR0000SA0L1E", "CUUR0000SA0L1E"}
    assert found.matches[0].popular
    assert all(m.survey == "CU" for m in found.matches)


async def test_search_known_series_offline():
    found = await client.search_series("taux de chômage", lang="fr")
    assert found.matches[0].series_id.startswith("LN")
    with pytest.raises(InvalidInput):
        await client.search_series("")
    lookup = await client.search_series("LAUST060000000000003")
    assert lookup.matches[0].series_id == "LAUST060000000000003"
    assert lookup.matches[0].seasonal_adjustment == "not seasonally adjusted"


def test_known_series_cover_every_indicator():
    for preset in constants.INDICATORS.values():
        assert preset.seasonally_adjusted in constants.KNOWN_SERIES
        assert preset.not_seasonally_adjusted in constants.KNOWN_SERIES
        assert preset.seasonally_adjusted[2] == "S"
        assert preset.not_seasonally_adjusted[2] == "U"


async def test_windows_inside_one_block_spend_one_query(httpx_mock):
    # The 25 unregistered queries a day are shared by every user of the hosted
    # server: 2018-2026, 2020-2026 and 2022-2024 all read the same cached block.
    httpx_mock.add_response(url=DATA, method="POST", json=_fixture("data_missing_value.json"))
    for start, end in ((2018, 2026), (2020, 2026), (2022, 2024)):
        result = await client.get_series(["LNS14000000"], start, end)
        assert result.start_year == start
        years = {o.year for s in result.series for o in s.observations}
        assert years and min(years) >= start and max(years) <= end
    assert len(_bodies(httpx_mock)) == 1
