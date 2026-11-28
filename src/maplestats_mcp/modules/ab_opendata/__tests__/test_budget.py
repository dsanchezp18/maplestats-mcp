"""Alberta budget fiscal plan tables, against workbooks laid out as seen live on 2026-11-24.

The workbooks are built here with the live quirks: a picture-only Cover sheet; a
title and units line over two header rows where one fiscal year spans the Budget and
Forecast columns; hidden columns whose cells read "#REF!" (Key Assumptions) or hold a
stale Budget column (Statement of Financial Position); a hidden working sheet; section
labels and footnotes; line numbers left of the labels with a row of column numbers
over the header (Historical Fiscal Summary); a second header block of calendar years;
and a forecaster with "n/a" in every year (Benchmark sheets).
"""

from __future__ import annotations

import io
import re

import pytest
from openpyxl import Workbook

from maplestats_mcp.modules.ab_opendata import budget_sheets, client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

CURRENT_ID = "8055ff9a-6109-45ac-b4dc-b90084c0d28d"
HISTORY_ID = "d0b5f7a3-4b4a-4c2d-9c11-0a8b6f7f3e21"
EO_RESOURCE = "9c686d4d-030f-41be-9b2e-68737bb9c3ac"
OTHER_RESOURCE = "a5e9fba6-5070-450a-b572-171dbd68b7a8"
OLD_RESOURCE = "3f1c2b5e-1111-4a2b-9c3d-7e8f9a0b1c2d"
EO_URL = (
    f"https://open.alberta.ca/dataset/{CURRENT_ID}/resource/{EO_RESOURCE}"
    "/download/budget-2026-fiscal-plan-economic-outlook-tables-2026-29.xlsx"
)
OTHER_URL = (
    f"https://open.alberta.ca/dataset/{CURRENT_ID}/resource/{OTHER_RESOURCE}"
    "/download/budget-2026-fiscal-plan-other-tables-2026-29.xlsx"
)
OLD_URL = (
    f"https://open.alberta.ca/dataset/{HISTORY_ID}/resource/{OLD_RESOURCE}"
    "/download/budget-2024-fiscal-plan-other-tables-2024-27.xlsx"
)


def _bytes(book: Workbook) -> bytes:
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _outlook_book() -> bytes:
    book = Workbook()
    cover = book.active
    assert cover is not None
    cover.title = "Cover"
    key = book.create_sheet("KeyAssumptions")
    key.append(["Key Energy and Economic Assumptions"])
    key.append([])
    key.append(["Fiscal Year Assumptionsa", "2017-18", "2019-20", "2025-26", "2026-27"])
    key.append([None, "Actuals", "Actuals", "Estimate", "Forecast"])
    key.append(["Crude Oil Pricesb"])
    key.append(["WTI (US$/bbl)", 53.69, "#REF!", 61.5, 60.50000000000001])
    key.append(["Calendar Year Assumptionsa", 2017, 2019, 2025, 2026])
    key.append([None, "Actuals", "Actuals", "Estimate", "Forecast"])
    key.append(["Gross Domestic Product"])
    key.append(["Nominal (billions of dollars)", 332.191, "#REF!", 481.1, 490.3])
    key.append(["a Forecast was finalized on January 15, 2026"])
    # The 2017-18 and 2019-20 columns are hidden in the published workbook.
    key.column_dimensions["B"].hidden = True
    key.column_dimensions["C"].hidden = True
    bench = book.create_sheet("B4. FX Rate")
    bench.append(["United States / Canada Exchange Rate Benchmark"])
    bench.append(["(US¢/Cdn$)"])
    bench.append(["Organization", 2026, 2027])
    bench.append(["Banks"])
    bench.append(["BMO Capital Markets", 73.8, 76])
    bench.append(["Desjardins", "n/a", "n/a"])
    bench.append(["Average", 73.5, 75.9])
    working = book.create_sheet("DONOTUSE")
    working.append(["scratch", 1, 2])
    working.sheet_state = "hidden"
    return _bytes(book)


def _other_book() -> bytes:
    book = Workbook()
    cover = book.active
    assert cover is not None
    cover.title = "Cover"
    ops = book.create_sheet("Sch 3 St of Ops")
    ops.append(["Statement of Operations"])
    ops.append(["(millions of dollars)"])
    ops.append([None, "2024-25", "2025-26", None, "2026-27"])
    ops.append([None, "Actual", "Budget", "Forecast", "Estimate"])
    ops.append(["Revenue"])
    ops.append(["Total revenue", 82469.44000000002, 74137.915, 75291.934, 74549.535])
    ops.append(["Expense"])
    ops.append(["Operating expense", 62024.831, 64310.545, 67016.496, 70398.123])
    summary = book.create_sheet("Summary p1 St of Ops")
    summary.append(["Summary Statement of Operations"])
    summary.append([None, "2024-25"])
    summary.append([None, "Actual"])
    summary.append(["Total revenue", 82469.44])
    position = book.create_sheet("Summary p1 Fin Position")
    position.append(["Summary Statement of Financial Position"])
    position.append(["(millions of dollars)", None, "Hide Column when published"])
    position.append([None, "At March 31"])
    position.append([None, "2025", 2026, "2026", "2027"])
    position.append([None, "Actual", "Budget", "Forecast", "Estimate"])
    position.append(
        ["Net financial assets / (debt)", -34337.108, -40811.0497, -39698.736, -51362.975]
    )
    position.column_dimensions["C"].hidden = True
    history = book.create_sheet("Sch 25 Historical")
    history.append(["Historical Fiscal Summary, 2014-15 to 2028-29 a"])
    history.append(["(millions of dollars)"])
    history.append([None, None, 1, 2, 3])
    history.append([None, None, "2014-15", "2015-16", "2016-17"])
    history.append(["Statement of Operations"])
    history.append([None, "Revenue"])
    history.append([1, "Personal income tax", 11042, 11357, 10763])
    history.append([2, "Corporate income tax", 5796, 4195, 3769])
    return _bytes(book)


def _resource(rid: str, name: str, url: str, fmt: str = "XLSX") -> dict:
    return {"id": rid, "name": name, "format": fmt, "url": url, "size": 1000}


def _package(name: str, dataset_id: str, resources: list[dict]) -> dict:
    return {
        "success": True,
        "result": {
            "id": dataset_id,
            "name": name,
            "title": name,
            "type": "opendata",
            "license_id": "OGLA",
            "license_title": "Open Government Licence - Alberta",
            "organization": {"name": "treasury-board-and-finance", "title": "TBF"},
            "resources": resources,
        },
    }


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def budget(httpx_mock):
    current = [
        _resource(EO_RESOURCE, "2026-2029 fiscal plan : economic outlook tables", EO_URL),
        _resource(OTHER_RESOURCE, "2026-2029 fiscal plan : other tables", OTHER_URL),
        _resource("c0ffee00-0000-4000-8000-000000000001", "Budget 2026 PDF", EO_URL[:-4] + "pdf"),
    ]
    history = [
        # Typed OTHERS on the live portal; the file is an .xlsx.
        _resource(OLD_RESOURCE, "2024-27 fiscal plan : other tables", OLD_URL, "OTHERS"),
    ]
    httpx_mock.add_response(
        url=re.compile(rf".*package_show\?id=({constants.BUDGET_DATASET_CURRENT}|{CURRENT_ID})$"),
        json=_package(constants.BUDGET_DATASET_CURRENT, CURRENT_ID, current),
        is_reusable=True,
        is_optional=True,
    )
    httpx_mock.add_response(
        url=re.compile(rf".*package_show\?id=({constants.BUDGET_DATASET_HISTORY}|{HISTORY_ID})$"),
        json=_package(constants.BUDGET_DATASET_HISTORY, HISTORY_ID, history),
        is_reusable=True,
        is_optional=True,
    )
    httpx_mock.add_response(url=EO_URL, content=_outlook_book(), is_reusable=True, is_optional=True)
    httpx_mock.add_response(
        url=OTHER_URL, content=_other_book(), is_reusable=True, is_optional=True
    )
    httpx_mock.add_response(url=OLD_URL, content=_other_book(), is_reusable=True, is_optional=True)


def test_hidden_columns_and_sheets_are_left_out():
    body = _outlook_book()
    titles = budget_sheets.list_sheets(body)
    assert [t.name for t in titles] == ["KeyAssumptions", "B4. FX Rate"]
    sheet = budget_sheets.parse_sheet(body, "KeyAssumptions")
    wti = next(r for r in sheet.rows if r.label == "WTI (US$/bbl)")
    assert wti.values == {"2025-26 Estimate": 61.5, "2026-27 Forecast": 60.5}
    assert wti.section == "Crude Oil Pricesb"
    gdp = next(r for r in sheet.rows if r.label == "Nominal (billions of dollars)")
    # The second header block (calendar years) names the rows under it.
    assert gdp.values == {"2025 Estimate": 481.1, "2026 Forecast": 490.3}
    assert sheet.notes == ["a Forecast was finalized on January 15, 2026"]
    assert not any("#REF" in str(v) for r in sheet.rows for v in r.values.values())


def test_a_row_of_na_is_data_not_a_header():
    sheet = budget_sheets.parse_sheet(_outlook_book(), "B4. FX Rate")
    assert sheet.columns == ["2026", "2027"]
    assert sheet.title_lines == ["United States / Canada Exchange Rate Benchmark", "(US¢/Cdn$)"]
    labels = {r.label: r.values for r in sheet.rows}
    assert labels["Desjardins"] == {"2026": "n/a", "2027": "n/a"}
    assert labels["Average"] == {"2026": 73.5, "2027": 75.9}
    assert sheet.label_header == "Organization"


def test_a_year_spanning_two_columns_names_both():
    sheet = budget_sheets.parse_sheet(_other_book(), "Sch 3 St of Ops")
    assert sheet.columns == [
        "2024-25 Actual",
        "2025-26 Budget",
        "2025-26 Forecast",
        "2026-27 Estimate",
    ]
    total = sheet.rows[0]
    assert total.label == "Total revenue" and total.section == "Revenue"
    assert total.values["2024-25 Actual"] == 82469.44  # binary noise rounded away
    assert sheet.rows[1].section == "Expense"


def test_a_hidden_stale_column_is_not_read():
    sheet = budget_sheets.parse_sheet(_other_book(), "Summary p1 Fin Position")
    assert sheet.columns == [
        "At March 31 2025 Actual",
        "At March 31 2026 Forecast",
        "At March 31 2027 Estimate",
    ]
    assert sheet.title_lines == ["Summary Statement of Financial Position", "(millions of dollars)"]


def test_line_numbers_and_column_numbers_are_dropped():
    sheet = budget_sheets.parse_sheet(_other_book(), "Sch 25 Historical")
    assert sheet.columns == ["2014-15", "2015-16", "2016-17"]
    assert [r.label for r in sheet.rows] == ["Personal income tax", "Corporate income tax"]
    assert sheet.rows[0].section == "Revenue"


def test_a_line_item_that_looks_like_years_is_data_not_a_header():
    # Values in $ millions can all be whole numbers between 1900 and 2100 and rise
    # left to right. Read as a header row they swallowed the line item and gave
    # every later row column names such as "2025-26 Budget 1950".
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "Capital plan"
    sheet.append(["Capital plan"])
    sheet.append(["(millions of dollars)"])
    sheet.append([None, "2025-26", "2026-27", "2027-28", "2028-29"])
    sheet.append([None, "Budget", "Target", "Target", "Target"])
    sheet.append(["Roads", 1950, 1980, 2020, 2075])
    sheet.append(["Buildings", 100, 200, 300, 400])
    # Consecutive numbers after the data have begun, with no header line under
    # them, are a line item too, not the start of a second table.
    sheet.append(["Backlog", 2020, 2021, 2022, 2023])
    sheet.append(["Reserve", 5, 6, 7, 8])
    parsed = budget_sheets.parse_sheet(_bytes(book), "Capital plan")
    assert parsed.columns == [
        "2025-26 Budget",
        "2026-27 Target",
        "2027-28 Target",
        "2028-29 Target",
    ]
    assert [r.label for r in parsed.rows] == ["Roads", "Buildings", "Backlog", "Reserve"]
    assert parsed.rows[0].values["2027-28 Target"] == 2020
    assert parsed.rows[2].values["2028-29 Target"] == 2023
    assert parsed.rows[3].section is None


def test_a_header_of_years_with_gaps_is_still_a_header_with_evidence():
    # The Key Assumptions calendar header read 2017, 2019, 2025, 2026 in older editions,
    # where no column is hidden. With a header line under it, the gaps do not matter;
    # requiring consecutive years turned the row into data and named the columns
    # "Actuals", "Actuals (2)", "Estimate", "Forecast".
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "KeyAssumptions"
    sheet.append(["Key Energy and Economic Assumptions"])
    sheet.append(["Fiscal Year Assumptionsa", "2017-18", "2019-20", "2025-26", "2026-27"])
    sheet.append([None, "Actuals", "Actuals", "Estimate", "Forecast"])
    sheet.append(["Crude Oil Pricesb"])
    sheet.append(["WTI (US$/bbl)", 53.69, 56.99, 61.5, 60.5])
    sheet.append(["Calendar Year Assumptionsa", 2017, 2019, 2025, 2026])
    sheet.append([None, "Actuals", "Actuals", "Estimate", "Forecast"])
    sheet.append(["Gross Domestic Product"])
    sheet.append(["Nominal (billions of dollars)", 332.191, 345.0, 481.1, 490.3])
    parsed = budget_sheets.parse_sheet(_bytes(book), "KeyAssumptions")
    wti = next(r for r in parsed.rows if r.label == "WTI (US$/bbl)")
    assert list(wti.values) == [
        "2017-18 Actuals",
        "2019-20 Actuals",
        "2025-26 Estimate",
        "2026-27 Forecast",
    ]
    gdp = next(r for r in parsed.rows if r.label == "Nominal (billions of dollars)")
    assert gdp.values == {
        "2017 Actuals": 332.191,
        "2019 Actuals": 345.0,
        "2025 Estimate": 481.1,
        "2026 Forecast": 490.3,
    }
    assert gdp.section == "Gross Domestic Product"


def test_an_unlabelled_header_of_years_with_gaps_names_the_columns():
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "Projection"
    sheet.append(["Population projection"])
    sheet.append(["(thousands)"])
    sheet.append([None, 2025, 2030, 2035])
    sheet.append(["Alberta", 4900, 5300, 5700])
    sheet.append(["Total", 5400, 5800, 6300])
    parsed = budget_sheets.parse_sheet(_bytes(book), "Projection")
    assert parsed.columns == ["2025", "2030", "2035"]
    assert [r.label for r in parsed.rows] == ["Alberta", "Total"]
    assert parsed.rows[0].values == {"2025": 4900, "2030": 5300, "2035": 5700}


def test_a_labelled_second_header_of_consecutive_years_is_a_header_not_data():
    # A calendar-year table after a fiscal-year one, with no Actual/Forecast line under
    # its years: the label ("Calendar Year Assumptions") is the only sign it is a
    # header. Read as data, the GDP rows under it kept the fiscal-year column names.
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "KeyAssumptions"
    sheet.append(["Key Energy and Economic Assumptions"])
    sheet.append(["Fiscal Year Assumptionsa", "2024-25", "2025-26", "2026-27"])
    sheet.append(["WTI (US$/bbl)", 70.1, 61.5, 60.5])
    sheet.append(["Calendar Year Assumptionsa", 2024, 2025, 2026])
    sheet.append(["Gross Domestic Product"])
    sheet.append(["Nominal (billions of dollars)", 410.2, 481.1, 490.3])
    parsed = budget_sheets.parse_sheet(_bytes(book), "KeyAssumptions")
    assert [r.label for r in parsed.rows] == ["WTI (US$/bbl)", "Nominal (billions of dollars)"]
    assert parsed.rows[0].values == {"2024-25": 70.1, "2025-26": 61.5, "2026-27": 60.5}
    gdp = parsed.rows[1]
    assert gdp.values == {"2024": 410.2, "2025": 481.1, "2026": 490.3}
    assert gdp.section == "Gross Domestic Product"
    assert parsed.columns == ["2024-25", "2025-26", "2026-27", "2024", "2025", "2026"]


@pytest.mark.parametrize(
    "label",
    ["Calendar Year", "Hypothèses par année civile", "Fiscal assumptions", "Exercice financier"],
)
def test_header_wording_in_english_and_french_marks_a_second_header(label):
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "Assumptions"
    sheet.append(["Assumptions"])
    sheet.append(["Fiscal year", "2024-25", "2025-26", "2026-27"])
    sheet.append(["Oil", 70, 61, 60])
    sheet.append([label, 2024, 2025, 2026])
    sheet.append(["Gas", 2.1, 2.4, 2.9])
    parsed = budget_sheets.parse_sheet(_bytes(book), "Assumptions")
    assert [r.label for r in parsed.rows] == ["Oil", "Gas"]
    assert parsed.rows[1].values == {"2024": 2.1, "2025": 2.4, "2026": 2.9}


def test_a_first_data_row_of_consecutive_values_under_the_header_is_data():
    # Whole numbers rising by exactly one look like years, but the columns already
    # have their years above (2025-26 ...), so a line-item label with no header
    # wording and no header line under it is data. It was dropped as a second header.
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "Capital plan"
    sheet.append(["Capital plan"])
    sheet.append([None, "2025-26", "2026-27", "2027-28"])
    sheet.append([None, "Budget", "Target", "Target"])
    sheet.append(["Roads", 2020, 2021, 2022])
    sheet.append(["Buildings", 100, 200, 300])
    parsed = budget_sheets.parse_sheet(_bytes(book), "Capital plan")
    assert parsed.columns == ["2025-26 Budget", "2026-27 Target", "2027-28 Target"]
    assert [r.label for r in parsed.rows] == ["Roads", "Buildings"]
    assert parsed.rows[0].values == {
        "2025-26 Budget": 2020,
        "2026-27 Target": 2021,
        "2027-28 Target": 2022,
    }


def test_a_labelled_row_of_years_under_a_header_line_without_years_is_a_header():
    # The unnamed header line above ("At March 31") holds no year, so the labelled row
    # of consecutive years under it is what names the columns.
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "Position"
    sheet.append(["Position"])
    sheet.append([None, "At March 31"])
    sheet.append(["Item", 2025, 2026, 2027])
    sheet.append(["Net debt", 10, 12, 14])
    parsed = budget_sheets.parse_sheet(_bytes(book), "Position")
    # "At March 31" spans all three columns, as "2025-26" spans Budget and Forecast.
    names = ["At March 31 2025", "At March 31 2026", "At March 31 2027"]
    assert parsed.columns == names
    assert parsed.rows[0].values == dict(zip(names, [10, 12, 14], strict=True))


async def test_no_part_lists_the_workbooks(budget):
    result = await client.get_budget_table()
    assert result.edition == 2026 and result.editions == [2026]
    assert [p.part for p in result.parts] == ["economic outlook", "other"]
    assert result.tables == [] and result.rows == []
    assert result.ogl_alberta and result.attribution
    assert result.provenance.limits and "pass `part`" in result.provenance.limits


async def test_a_part_lists_its_tables_and_a_table_is_read(budget):
    listing = await client.get_budget_table(part="economic")
    assert [s.table for s in listing.tables] == ["KeyAssumptions", "B4. FX Rate"]
    assert listing.tables[0].title == "Key Energy and Economic Assumptions"
    result = await client.get_budget_table(part="economic outlook", table="key energy")
    assert result.table == "KeyAssumptions"
    assert result.rows[0].values["2026-27 Forecast"] == 60.5
    assert "Open Government Licence" in (result.provenance.licence or "")


async def test_exact_title_wins_over_a_longer_one(budget):
    result = await client.get_budget_table(part="other", table="Statement of Operations")
    assert result.table == "Sch 3 St of Ops"
    filtered = await client.get_budget_table(part="other", table="Sch 3", contains="expense")
    assert [r.label for r in filtered.rows] == ["Operating expense"]
    assert filtered.total_rows == 1


async def test_an_older_budget_comes_from_the_history_dataset(budget):
    result = await client.get_budget_table(edition=2024, part="other", table="Historical")
    assert result.edition == 2024 and result.fiscal_plan == "2024-27"
    assert result.dataset == constants.BUDGET_DATASET_HISTORY
    assert result.rows[0].label == "Personal income tax"


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"part": "nothing"}, InvalidInput),
        ({"table": "KeyAssumptions"}, InvalidInput),
        ({"part": "other", "table": "zzz"}, InvalidInput),
        ({"edition": 2010}, InvalidInput),
        ({"edition": 2019}, NotFound),
    ],
)
async def test_bad_arguments_are_refused(budget, kwargs, error):
    with pytest.raises(error):
        await client.get_budget_table(**kwargs)
