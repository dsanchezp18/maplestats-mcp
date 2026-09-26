"""Tests on CSV extracts shaped like the real CGC files (checked 2026-09-26).

Each fixture copies a quirk seen live: the header layouts of 2026-27,
2017-18 and the French 2025-26 file, thousands separators, "(0.4)" and "."
values, rows out of week order, national rows with no region, the French
2014-15 date format, Windows-1252 text, and the site's HTTP 200 "page not
found" answer for a missing file.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from maplestats_mcp.modules.cgc import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable

TODAY = date(2026, 9, 26)

# 2026-27 layout: quoted Title Case header; the file does not keep week order.
CURRENT = """\
"Crop Year","Grain Week","Week Ending Date","worksheet","metric","period","grain","grade","Region","Ktonnes"
"2026-2027",2,"16/08/2026","Primary","Deliveries","Current Week","Canola",,"Manitoba",20.5
"2026-2027",1,"09/08/2026","Primary","Deliveries","Current Week","Canola",,"Manitoba",10
"2026-2027",1,"09/08/2026","Primary","Deliveries","Current Week","Canola",,"Saskatchewan",30.25
"2026-2027",1,"09/08/2026","Primary","Deliveries","Crop Year","Canola",,"Manitoba",10
"2026-2027",1,"09/08/2026","Primary","Deliveries","Current Week","Wheat",,"Manitoba",
"2026-2027",1,"09/08/2026","Process","Producer Deliveries","Current Week","Canola",,"",150.2
"2026-2027",2,"16/08/2026","Primary","Deliveries","Current Week","Canola",,"Saskatchewan",40
"2026-2027",2,"16/08/2026","Primary","Stocks","Current Week","Canola",,"Manitoba",99
"2026-2027",2,"16/08/2026","Terminal Exports","Exports","Crop Year","Wheat","No.1 CW RS","Vancouver",12.5
"2026-2027",2,"16/08/2026","Terminal Exports","Exports","Crop Year","Peas","All grades combined","Vancouver",3
"""

# 2017-18 to 2023-24 layout: grain_week first, thousands separators,
# a negative adjustment in brackets and "." for a blank cell.
OLD = """\
grain_week,crop_year,week_ending_date,worksheet,metric,period,grain,grade,region,Ktonnes
1,2017-2018,06/08/2017,Terminal Stocks,Stocks,Current Week,Wheat,No.1 CW RS,Vancouver,"1,191.10"
1,2017-2018,06/08/2017,Terminal Stocks,Stocks,Current Week,Wheat,No.2 CW RS,Vancouver,(0.4)
2,2017-2018,13/08/2017,Terminal Stocks,Stocks,Current Week,Wheat,No.1 CW RS,Vancouver,.
"""

# French 2025-26: Windows-1252, headers that lost their accented letters.
FRENCH = (
    '"Campagne Agricole","Semaine","le semaine se terminant","Silo Agr","Activit",'
    '"periode","grain","grade","region","Ktonnes"\r\n'
    '"2025-2026",1,"10/08/2025","Silos primaires","Livraisons","Semaine en cours",'
    '"Blé",,"Manitoba",1.5\r\n'
    '"2025-2026",1,"10/08/2025","Silos primaires","Livraisons","Semaine en cours",'
    '"Blé",,"Colombie britannique",0.5\r\n'
).encode("cp1252")

# French 2014-15 writes week-ending dates as 10AUG2014.
FRENCH_2014 = (
    '"Campagne Agricole","Semaine","le semaine se terminant","Silo Agréé","Activité",'
    '"periode","grain","grade","region","Ktonnes"\r\n'
    "2014-2015,1,10AUG2014,Grains Fourrager,Livraisons,Semaine en cours,Orge,,Alberta,3.5\r\n"
).encode("cp1252")

NOT_FOUND_PAGE = (
    "<!DOCTYPE html>\n<html><head><title>We couldn't find that Web page (Error 404) / "
    "Nous ne pouvons trouver cette page Web (Erreur 404)</title></head></html>"
)

EXPORTS = (
    "Year,Month,Grain,Grade,Ktonnes,Elevator,Region,Global_region,Destination\r\n"
    "2024,July,Wheat,No.1 CW RS,100.5,TERMINALS,Vancouver,Asia,Japan\r\n"
    "2024,August,Wheat,No.1 CW RS,200.000000,TERMINALS,Vancouver,Asia,Japan\r\n"
    "2024,August,Wheat,No.2 CW RS,50,TERMINALS,Vancouver,Asia,China P.R.\r\n"
    "2025,January,Canola,No.1 CANADA,300.25,TERMINALS,Vancouver,Asia,China P.R.\r\n"
    "2025,February,Lentil,--,1.5,CONTAINER,Unlicensed,Eastern Europe,Türkiye\r\n"
    "2025,March,Peas,All grades combined,2,PRIMARY,Prairie Elevators,,Not Specified\r\n"
).encode("cp1252")

EXPORTS_FR = (
    "Annee,Mois,Grain,Grade,Ktonnes,Silo_a_grains,Secteur,Region_du_Monde,Destination\r\n"
    "2025,février,Blé,AUTRE,52.5,Silos Terminaux,Vancouver,Asie,Japon\r\n"
    "2025,août,Blé,AUTRE,7.5,Silos Terminaux,Vancouver,Asie,Japon\r\n"
).encode("cp1252")


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    cache_module._caches.clear()
    monkeypatch.setattr(client, "_today", lambda: TODAY)
    yield


def _weekly(start: int, lang: str = "en") -> str:
    return client.weekly_url(start, lang)  # type: ignore[arg-type]


def test_urls_follow_the_site_layout():
    assert _weekly(2026) == (
        "https://www.grainscanada.gc.ca/en/grain-research/statistics/"
        "grain-statistics-weekly/2026-27/gsw-shg-en.csv"
    )
    assert _weekly(2017).endswith("/grain-statistics-weekly/2017-18/csv/gsw-shg-en.csv")
    assert _weekly(2026, "fr").endswith("/statistique-hebdomadaire/26-27/gsw-shg-fr.csv")
    assert _weekly(2013, "fr").endswith("/statistique-hebdomadaire/13-14/gsw-shg-fr.csv")


@pytest.mark.parametrize(
    ("value", "start"),
    [("2025-26", 2025), ("2025-2026", 2025), ("25-26", 2025), ("2026", 2026), (2013, 2013)],
)
def test_crop_year_forms(value, start):
    assert client.parse_crop_year(value) == start


@pytest.mark.parametrize("value", ["2025-27", "2012-13", "2027-28", "last year"])
def test_bad_crop_years(value):
    with pytest.raises(InvalidInput):
        client.parse_crop_year(value)


def test_current_crop_year_turns_in_august():
    assert client.current_crop_year(date(2026, 7, 31)) == 2025
    assert client.current_crop_year(date(2026, 8, 1)) == 2026


@pytest.mark.parametrize(
    ("raw", "value"),
    [("1,191.10", 1191.1), ("(0.4)", -0.4), (".", None), ("", None), ("0", 0.0), ("12", 12.0)],
)
def test_numbers(raw, value):
    assert client.parse_number(raw) == value


@pytest.mark.parametrize(
    ("raw", "day"),
    [
        ("09/08/2026", date(2026, 8, 9)),
        ("11/8/2013", date(2013, 8, 11)),
        ("10AUG2014", date(2014, 8, 10)),
        ("2026-10-03", date(2026, 10, 3)),
        ("soon", None),
    ],
)
def test_dates(raw, day):
    assert client.parse_date(raw) == day


async def test_describe_current_crop_year(httpx_mock):
    httpx_mock.add_response(url=_weekly(2026), text=CURRENT)
    result = await client.describe_weekly()
    assert result.crop_year == "2026-27"
    assert result.latest_week == 2 and result.latest_week_ending == date(2026, 8, 16)
    assert [w.week for w in result.weeks] == [1, 2]
    sheets = {w.worksheet: w for w in result.worksheets}
    assert sheets["Primary"].metrics == ["Deliveries", "Stocks"]
    assert sheets["Primary"].periods == ["Current Week", "Crop Year"]
    assert sheets["Process"].has_national_rows and not sheets["Primary"].has_national_rows
    assert sheets["Terminal Exports"].grades_total == 2
    assert result.available_crop_years[0] == "2013-14"
    assert result.available_crop_years[-1] == "2026-27"
    assert result.provenance.as_of is not None and result.provenance.source.startswith("cgc")


async def test_query_rows_in_week_order(httpx_mock):
    httpx_mock.add_response(url=_weekly(2026), text=CURRENT)
    result = await client.query_weekly(
        "primary", metric="deliveries", period="Current Week", grain="canola"
    )
    assert [(r.week, r.region, r.ktonnes) for r in result.rows] == [
        (1, "Manitoba", 10.0),
        (1, "Saskatchewan", 30.25),
        (2, "Manitoba", 20.5),
        (2, "Saskatchewan", 40.0),
    ]
    assert result.rows[0].week_ending == date(2026, 8, 9)
    assert result.filters == {
        "metric": ["deliveries"],
        "period": ["Current Week"],
        "grain": ["canola"],
    }


async def test_blank_cell_and_national_row(httpx_mock):
    httpx_mock.add_response(url=_weekly(2026), text=CURRENT)
    wheat = await client.query_weekly("Primary", grain="Wheat")
    assert wheat.rows[0].ktonnes is None
    cached = await client.query_weekly("Process")
    assert cached.rows[0].region is None and cached.rows[0].ktonnes == 150.2
    assert cached.provenance.cached


async def test_group_by_sums_and_counts_blanks(httpx_mock):
    httpx_mock.add_response(url=_weekly(2026), text=CURRENT)
    result = await client.query_weekly(
        "Primary",
        metric="Deliveries",
        period="Current Week",
        group_by=["grain"],
        week_to=1,
    )
    by_grain = {r.grain: r for r in result.rows}
    assert by_grain["Canola"].ktonnes == 40.25 and by_grain["Canola"].cells == 2
    assert by_grain["Canola"].region is None and by_grain["Canola"].worksheet == "Primary"
    assert by_grain["Wheat"].ktonnes is None and by_grain["Wheat"].blank_cells == 1


async def test_group_by_refuses_to_mix_periods_or_metrics(httpx_mock):
    httpx_mock.add_response(url=_weekly(2026), text=CURRENT)
    with pytest.raises(InvalidInput, match="period"):
        await client.query_weekly("Primary", metric="Deliveries", group_by=["grain"])
    with pytest.raises(InvalidInput, match="metric"):
        await client.query_weekly("Primary", period="Current Week", group_by=["grain"])
    mixed = await client.query_weekly("Primary", group_by=["grain", "metric", "period"])
    assert {(r.metric, r.period) for r in mixed.rows} >= {("Stocks", "Current Week")}


async def test_unknown_values_list_the_choices(httpx_mock):
    httpx_mock.add_response(url=_weekly(2026), text=CURRENT)
    with pytest.raises(InvalidInput, match="'Canola'"):
        await client.query_weekly("Primary", grain="Barley")
    with pytest.raises(InvalidInput, match="Terminal Exports"):
        await client.query_weekly("Elevators")
    with pytest.raises(InvalidInput):
        await client.query_weekly("Primary", group_by=["province"])  # type: ignore[list-item]
    with pytest.raises(InvalidInput):
        await client.query_weekly("Primary", limit=0)


async def test_latest_week_and_truncation_keep_the_newest(httpx_mock):
    httpx_mock.add_response(url=_weekly(2026), text=CURRENT)
    latest = await client.query_weekly("Primary", latest_week_only=True)
    assert {r.week for r in latest.rows} == {2}
    capped = await client.query_weekly("Primary", metric="Deliveries", limit=2)
    assert capped.truncated and capped.total_matched == 6
    assert [r.week for r in capped.rows] == [2, 2]
    assert capped.provenance.limits and "latest 2 of 6" in capped.provenance.limits


async def test_old_layout_and_number_formats(httpx_mock):
    httpx_mock.add_response(url=_weekly(2017), text=OLD)
    result = await client.query_weekly("Terminal Stocks", crop_year="2017-18")
    assert [r.ktonnes for r in result.rows] == [1191.1, -0.4, None]
    assert result.rows[0].grade == "No.1 CW RS"
    summed = await client.query_weekly("Terminal Stocks", crop_year="2017", group_by=["grain"])
    assert [(r.week, r.ktonnes) for r in summed.rows] == [(1, 1190.7), (2, None)]


async def test_french_file(httpx_mock):
    httpx_mock.add_response(url=_weekly(2025, "fr"), content=FRENCH)
    result = await client.query_weekly(
        "silos primaires", crop_year="2025-26", lang="fr", grain="ble", group_by=["grain"]
    )
    assert result.lang == "fr" and result.worksheet == "Silos primaires"
    assert [(r.grain, r.metric, r.ktonnes) for r in result.rows] == [("Blé", None, 2.0)]


async def test_french_2014_dates(httpx_mock):
    httpx_mock.add_response(url=_weekly(2014, "fr"), content=FRENCH_2014)
    result = await client.describe_weekly("2014-15", lang="fr")
    assert result.weeks[0].week_ending == date(2014, 8, 10)
    assert result.worksheets[0].metrics == ["Livraisons"]


async def test_missing_file_is_a_soft_404(httpx_mock):
    httpx_mock.add_response(url=_weekly(2015), text=NOT_FOUND_PAGE)
    with pytest.raises(NotFound):
        await client.describe_weekly("2015-16")


async def test_default_falls_back_before_week_one(httpx_mock, monkeypatch):
    monkeypatch.setattr(client, "_today", lambda: date(2026, 8, 3))
    httpx_mock.add_response(url=_weekly(2026), text=NOT_FOUND_PAGE)
    httpx_mock.add_response(url=_weekly(2025), text=CURRENT.replace("2026-2027", "2025-2026"))
    result = await client.describe_weekly()
    assert result.crop_year == "2025-26"


async def test_handshake_failures_are_retried(httpx_mock):
    for _ in range(4):
        httpx_mock.add_exception(httpx.ConnectError(""), url=_weekly(2026))
    httpx_mock.add_response(url=_weekly(2026), text=CURRENT)
    result = await client.describe_weekly("2026-27")
    assert result.latest_week == 2


async def test_unreachable_host_is_unavailable(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError(""), url=_weekly(2026), is_reusable=True)
    with pytest.raises(UpstreamUnavailable, match="ConnectError"):
        await client.describe_weekly("2026-27")


async def test_http_404_is_not_found(httpx_mock):
    httpx_mock.add_response(url=_weekly(2016), status_code=404)
    with pytest.raises(NotFound):
        await client.describe_weekly("2016-17")


async def test_exports_describe(httpx_mock):
    httpx_mock.add_response(url=constants.EXPORTS_URL_EN, content=EXPORTS)
    result = await client.describe_exports()
    assert result.first_month == "2024-07" and result.latest_month == "2025-03"
    assert "Türkiye" in result.destinations
    assert result.elevators == ["CONTAINER", "PRIMARY", "TERMINALS"]
    assert result.global_regions == ["Asia", "Eastern Europe"]  # blank dropped


async def test_exports_raw_rows(httpx_mock):
    httpx_mock.add_response(url=constants.EXPORTS_URL_EN, content=EXPORTS)
    result = await client.query_exports(grain="wheat", destination=["japan", "china p.r."])
    assert [(r.period, r.destination, r.ktonnes) for r in result.rows] == [
        ("2024-07", "Japan", 100.5),
        ("2024-08", "Japan", 200.0),
        ("2024-08", "China P.R.", 50.0),
    ]
    assert result.total_ktonnes == 350.5 and result.rows[0].cells is None


async def test_exports_crop_year_and_covered_months(httpx_mock):
    httpx_mock.add_response(url=constants.EXPORTS_URL_EN, content=EXPORTS)
    result = await client.query_exports(frequency="crop_year", group_by=["grain"])
    rows = {(r.period, r.grain): r for r in result.rows}
    # July 2024 belongs to crop year 2023-24; August 2024 on to 2024-25.
    assert rows[("2023-24", "Wheat")].ktonnes == 100.5
    assert rows[("2024-25", "Wheat")].ktonnes == 250.0
    assert rows[("2024-25", "Wheat")].cells == 2
    # The file covers Aug 2024, Jan, Feb and Mar 2025 in that crop year,
    # whether or not wheat moved in each of them.
    assert rows[("2024-25", "Wheat")].months == 4
    assert rows[("2023-24", "Wheat")].year is None
    yearly = await client.query_exports(frequency="year", year_from=2025)
    assert [(r.period, r.ktonnes, r.months) for r in yearly.rows] == [("2025", 303.75, 3)]
    # year_from cuts crop year 2024-25 to January-March 2025.
    bounded = await client.query_exports(frequency="crop_year", year_from=2025)
    assert [(r.period, r.months) for r in bounded.rows] == [("2024-25", 3)]


async def test_exports_filters_and_limits(httpx_mock):
    httpx_mock.add_response(url=constants.EXPORTS_URL_EN, content=EXPORTS)
    with pytest.raises(InvalidInput, match="Japan"):
        await client.query_exports(destination="Atlantis")
    with pytest.raises(InvalidInput):
        await client.query_exports(group_by=["port"])  # type: ignore[list-item]
    capped = await client.query_exports(limit=2)
    assert capped.truncated and [r.period for r in capped.rows] == ["2025-02", "2025-03"]
    assert capped.total_ktonnes == 654.25


async def test_french_exports(httpx_mock):
    httpx_mock.add_response(url=constants.EXPORTS_URL_FR, content=EXPORTS_FR)
    result = await client.query_exports(
        lang="fr", grain="Ble", destination="japon", frequency="crop_year", group_by=["grain"]
    )
    assert [(r.period, r.grain, r.ktonnes) for r in result.rows] == [
        ("2024-25", "Blé", 52.5),
        ("2025-26", "Blé", 7.5),
    ]
    assert result.rows[0].months == 1


def test_keep_latest_drops_oldest_periods_first():
    rows = [("w1", "a"), ("w1", "b"), ("w2", "c"), ("w2", "d"), ("w3", "e")]
    assert client.keep_latest(rows, 3, lambda r: r[0]) == [("w2", "c"), ("w2", "d"), ("w3", "e")]
    assert client.keep_latest(rows, 2, lambda r: r[0]) == [("w2", "c"), ("w3", "e")]
    assert client.keep_latest(rows, 9, lambda r: r[0]) == rows


async def test_exports_largest_first_within_a_period(httpx_mock):
    httpx_mock.add_response(url=constants.EXPORTS_URL_EN, content=EXPORTS)
    result = await client.query_exports(
        frequency="crop_year", group_by=["destination"], year_from=2024, limit=2
    )
    assert [(r.period, r.destination) for r in result.rows] == [
        ("2024-25", "China P.R."),
        ("2024-25", "Japan"),
    ]
    assert result.truncated and result.total_matched == 5
