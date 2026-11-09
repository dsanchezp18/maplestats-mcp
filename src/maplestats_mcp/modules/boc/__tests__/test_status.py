"""Discontinued series and the exchange-rate caveat (client.status_fields and callers).

Shapes taken from live Valet responses on 2026-11-09: the noon rate IEXE0101
(label USD_NOON, last value 2017-04-28) is still listed and served, `recent=1`
over comma-joined names returns each series' own newest row, and some series
key their rows by "k" or "orr_id" instead of a date "d".
"""

from __future__ import annotations

from datetime import date

import pytest

from maplestats_mcp.modules.boc import client, constants
from maplestats_mcp.modules.boc.schemas import SeriesSummary
from maplestats_mcp.shared import cache as cache_module

TODAY = date(2026, 11, 9)
INVENTORY = {
    "series": {
        "FXUSDCAD": {"label": "USD/CAD", "description": "Daily average exchange rate"},
        "FXMUSDCAD": {"label": "USD/CAD", "description": "Monthly average"},
        "FXAUSDCAD": {"label": "USD/CAD", "description": "Annual average"},
        "IEXE0101": {"label": "USD_NOON", "description": "U.S. dollar (noon)"},
        "IEXE0105": {"label": "USD_NOON", "description": "U.S. dollar noon, 90-day"},
        "IEXE0301": {"label": "DKK_NOON", "description": "Danish krone"},
        "IEXE1601": {"label": "AUD_NOON", "description": "Australian dollar"},
        "IEXM0101": {"label": "USD", "description": "U.S. dollar (noon)"},
        "IEXA0101": {"label": "STATIC_XAVG_A_IEXE0101", "description": "U.S. dollar (noon)"},
    }
}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    cache_module._caches.clear()
    monkeypatch.setattr(client, "today", lambda: TODAY)


def _entry(name: str) -> SeriesSummary:
    e = INVENTORY["series"][name]
    return SeriesSummary(name=name, label=e["label"], description=e["description"])


def _known() -> dict[str, str]:
    return {n: e["label"] for n, e in INVENTORY["series"].items()}


def _recent(httpx_mock, names: str, newest: dict[str, str], date_format: str = "daily"):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}observations/{names}/json?recent=1",
        json={
            "seriesDetail": {n: {"label": n, "dateFormat": date_format} for n in names.split(",")},
            "observations": [{"d": d, n: {"v": "1.3"}} for n, d in newest.items()],
        },
    )


@pytest.mark.parametrize(
    ("latest", "frequency", "status"),
    [
        (date(2017, 4, 28), "daily", "discontinued"),
        (date(2026, 11, 6), "Business daily", "active"),
        (date(2026, 9, 1), "Monthly", "active"),
        (date(2024, 1, 1), "monthly", "discontinued"),
        (date(2025, 1, 1), "annual", "active"),
        (date(2018, 12, 31), "Quotidien ouvrable", "discontinued"),
        (date(2017, 4, 28), None, None),  # frequency unknown: no verdict
        (None, "daily", None),  # rows not dated: no verdict
    ],
)
def test_status_compares_newest_date_with_frequency(latest, frequency, status):
    fields = client.status_fields(_entry("FXUSDCAD"), latest, frequency, None)
    assert fields["status"] == status if status else "status" not in fields
    assert fields["last_observation"] == latest


@pytest.mark.parametrize(
    ("name", "successor"),
    [
        ("IEXE0101", "FXUSDCAD"),  # daily noon rate
        ("IEXM0101", "FXMUSDCAD"),  # its monthly average
        ("IEXA0101", "FXAUSDCAD"),  # its annual average, currency from IEXE0101's label
        ("IEXE0105", None),  # a 90-day forward rate: no daily-average replacement
        ("IEXE0301", None),  # no FXDKKCAD in the inventory
    ],
)
def test_legacy_exchange_rates_name_their_successor(name, successor):
    fields = client.status_fields(_entry(name), date(2017, 4, 28), "daily", _known())
    assert fields["status"] == "discontinued"
    assert fields["successor"] == successor
    assert "2017-04-28" in fields["note"]
    assert "noon and closing exchange rates" in fields["note"]


def test_generic_discontinued_note_and_french():
    entry = SeriesSummary(name="BA.CDN.90D.MID", label="Bankers' acceptances", description="")
    fields = client.status_fields(entry, date(2018, 12, 31), "Business daily", None)
    assert fields["successor"] is None
    assert fields["note"].startswith("Discontinued: no observation since 2018-12-31")
    fr = client.status_fields(_entry("IEXE0101"), date(2017, 4, 28), "quotidien", _known(), "fr")
    assert fr["note"].startswith("Série abandonnée")
    assert "FXUSDCAD" in fr["note"]


def test_fx_daily_and_average_rates_carry_the_indicative_caveat():
    assert "16:30 ET" in (client.fx_note("FXUSDCAD") or "")
    assert "not a transactional rate" in (client.fx_note("FXCADEUR") or "")
    assert "Average of" in (client.fx_note("FXMUSDCAD") or "")
    assert client.fx_note("IEXE0101") is None
    assert client.fx_note("FXCADUSD_CHANGES") is None
    assert "16 h 30" in (client.fx_note("FXUSDCAD", "fr") or "")


async def test_get_series_marks_the_noon_rate_discontinued(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}series/IEXE0101/json",
        json={
            "seriesDetails": {
                "name": "IEXE0101",
                "label": "USD_NOON",
                "description": "U.S. dollar (noon)",
                "dateFormat": "daily",
                "metadata": {},
            }
        },
    )
    _recent(httpx_mock, "IEXE0101", {"IEXE0101": "2017-04-28"})
    httpx_mock.add_response(url=f"{constants.BASE_URL}lists/series/json", json=INVENTORY)
    result = await client.get_series("IEXE0101")
    assert result.status == "discontinued"
    assert result.last_observation == date(2017, 4, 28)
    assert result.successor == "FXUSDCAD"
    assert result.frequency == "daily"


async def test_search_lists_legacy_series_with_their_status(httpx_mock):
    httpx_mock.add_response(url=f"{constants.BASE_URL}lists/series/json", json=INVENTORY)
    found = ["IEXE0101", "IEXE0105", "IEXM0101", "IEXA0101"]
    _recent(
        httpx_mock,
        ",".join(found),
        {"IEXE0101": "2017-04-28", "IEXE0105": "2017-04-28", "IEXM0101": "2017-04-01"}
        | {"IEXA0101": "2016-01-01"},
    )
    # The words a user types find Valet's "U.S. dollar (noon)"; "us" is a word,
    # not a substring of "Australian".
    result = await client.search_series("US dollar noon")
    assert [s.name for s in result.series] == found
    assert all(s.status == "discontinued" for s in result.series)
    assert [s.successor for s in result.series] == ["FXUSDCAD", None, "FXMUSDCAD", "FXAUSDCAD"]
    assert "status" in (result.provenance.coverage or "")


async def test_status_check_survives_undated_rows_and_failures(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}observations/ORR_KEY,FXUSDCAD/json?recent=1",
        json={
            "seriesDetail": {
                "ORR_KEY": {"dateFormat": "daily"},
                "FXUSDCAD": {"metadata": {"frequency": "Business daily"}},
            },
            "observations": [
                {"orr_id": "HIST_ORR_1", "ORR_KEY": {"v": "HIST_ORR_1"}},
                {"d": "2026-11-06", "FXUSDCAD": {"v": "1.41"}},
            ],
        },
    )
    found = await client.latest_dates(["ORR_KEY", "FXUSDCAD"])
    assert found == {"ORR_KEY": (None, "daily"), "FXUSDCAD": (date(2026, 11, 6), "Business daily")}
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}observations/NOPE/json?recent=1", status_code=404, json={}
    )
    assert await client.latest_dates(["NOPE"]) == {}


async def test_status_checks_are_chunked(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "STATUS_CHUNK", 2)
    _recent(httpx_mock, "A,B", {"A": "2026-11-06", "B": "2026-11-06"})
    _recent(httpx_mock, "C", {"C": "2010-01-01"})
    found = await client.latest_dates(["A", "B", "C"])
    assert found["C"] == (date(2010, 1, 1), "daily")
    assert len(httpx_mock.get_requests()) == 2


async def test_observations_mark_a_series_with_no_rows_in_the_window(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}observations/IEXE0101/json?start_date=2024-01-01",
        json={
            "seriesDetail": {"IEXE0101": {"label": "USD_NOON", "dateFormat": "daily"}},
            "observations": [],
        },
    )
    _recent(httpx_mock, "IEXE0101", {"IEXE0101": "2017-04-28"})
    httpx_mock.add_response(url=f"{constants.BASE_URL}lists/series/json", json=INVENTORY)
    result = await client.get_observations(["IEXE0101"], start_date="2024-01-01")
    info = result.series["IEXE0101"]
    assert (info.status, info.last_observation, info.successor) == (
        "discontinued",
        date(2017, 4, 28),
        "FXUSDCAD",
    )
    assert result.provenance.caveats == []


async def test_observations_of_fx_rates_carry_the_caveat_once(httpx_mock):
    rows = [{"d": "2026-11-06", "FXUSDCAD": {"v": "1.41"}, "FXEURCAD": {"v": "1.62"}}]
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}observations/FXUSDCAD,FXEURCAD/json?recent=1",
        json={
            "seriesDetail": {
                "FXUSDCAD": {"label": "USD/CAD", "dateFormat": "daily"},
                "FXEURCAD": {"label": "EUR/CAD", "dateFormat": "daily"},
            },
            "observations": rows,
        },
    )
    result = await client.get_observations(["FXUSDCAD", "FXEURCAD"], recent=1)
    assert result.series["FXUSDCAD"].status == "active"
    assert result.series["FXUSDCAD"].note is None  # said once, in provenance.caveats
    assert len(result.provenance.caveats) == 1
    assert "16:30 ET" in result.provenance.caveats[0]


async def test_observations_ended_before_today_reuse_the_newer_data_request(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}observations/FXUSDCAD/json"
            "?start_date=2026-10-01&end_date=2026-10-02"
        ),
        json={
            "seriesDetail": {"FXUSDCAD": {"label": "USD/CAD", "dateFormat": "daily"}},
            "observations": [{"d": "2026-10-01", "FXUSDCAD": {"v": "1.39"}}],
        },
    )
    _recent(httpx_mock, "FXUSDCAD", {"FXUSDCAD": "2026-11-06"})
    result = await client.get_observations(
        ["FXUSDCAD"], start_date="2026-10-01", end_date="2026-10-02"
    )
    assert result.series["FXUSDCAD"].last_observation == date(2026, 11, 6)
    assert result.series["FXUSDCAD"].status == "active"
    assert len(httpx_mock.get_requests()) == 2  # one recent=1 serves both checks
