"""Tests for the ST98 workbook reader, shaped on the 2022-2026 executive-summary
workbooks and the ST98 page as read live on 2026-11-07 (see st98.py)."""

from __future__ import annotations

import io
import re
from datetime import datetime

import httpx
import pytest
from openpyxl import Workbook

from maplestats_mcp.modules.aer import client, constants, st98
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_STATIC_2026 = (
    "https://static.aer.ca/prd/documents/sts/ST98/2026/st98-2026-executive-summary-data.xlsx"
)

# The links as the ST98 page writes them (relative, one path scheme per year).
_PAGE = """
<a href="/documents/sts/ST98/2023/ST98_executive_summary-data.xlsx">2023</a>
<a href="/documents/sts/st98/st98-2024-executive-summary-data.xlsx">2024</a>
<a href="/documents/sts/st98/2025/st98-2025-executive-summary-data.xlsx">2025</a>
<a href="/prd/documents/sts/ST98/2026/st98-2026-executive-summary-data.xlsx">2026</a>
<a href="/prd/documents/sts/ST98/2026/st98-2026-CCUS-data.xlsx">CCUS</a>
"""


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


def _workbook() -> bytes:
    """Figures and Tables laid out like st98-2026-executive-summary-data.xlsx."""
    wb = Workbook()
    assert wb.active is not None
    wb.active.title = "Disclaimer"
    wb.active["A1"] = "This data is provided by the AER."
    fig = wb.create_sheet("Figures")
    # Figure 1 (C-F): monthly prices, each column with its own unit.
    fig["C31"] = "Figure 1"
    fig.merge_cells("C31:F31")
    fig["C32"], fig["D32"], fig["E32"] = "Year", "WTI", "WTI-WCS Differential"
    fig.merge_cells("C32:C33")
    fig["D33"], fig["E33"] = "(US$/bbl)", "(US$/bbl)"
    fig["C34"], fig["D34"], fig["E34"] = datetime(2017, 1, 1), 52.61, 15.42
    fig["C35"], fig["D35"], fig["E35"] = datetime(2017, 2, 1), 53.46, 14.32
    fig["C37"] = "Prices are in nominal dollars."
    # Figure 8 (H-M): one unit merged over each group of columns, footnote
    # letters glued to the names, history and forecast years.
    fig["H31"] = "Figure 8"
    fig["H33"], fig["I33"], fig["J33"] = "Year", "Coal", "Natural gasa"
    fig["K33"], fig["L33"] = "Coal", "Natural gasa"
    fig["I34"], fig["K34"] = "(petajoules)", "(million barrels per day)"
    fig.merge_cells("I34:J34")
    fig.merge_cells("K34:L34")
    fig["H35"], fig["I35"], fig["J35"], fig["K35"], fig["L35"] = 2025, 300.5, 5000.25, 0.1, 2.3
    fig["H36"], fig["I36"], fig["J36"], fig["K36"], fig["L36"] = 2026, 290, 5100, 0.1, 2.4
    fig["H38"] = "a Includes coalbed methane and shale gas."
    fig["H39"] = "2025 values are estimated."
    # Figure 10 (O-Q): the group header sits over the label column, merged
    # across the values; one row.
    fig["O31"] = "Figure 10"
    fig["O32"] = "Percentage of total bitumen production"
    fig.merge_cells("O32:Q32")
    fig["O33"], fig["P33"], fig["Q33"] = "Year", "In situ bitumen upgraded ", "Mined"
    fig["O34"], fig["P34"], fig["Q34"] = 2025, 0.0591, 0.3493

    tables = wb.create_sheet("Tables")
    # Table 1 (A-E): items down column A, a value with a footnote letter.
    tables["A2"] = "Table 1 Resources, reserves and production summary "
    tables["B3"], tables["D3"] = "Crude bitumen", "Crude oil"
    tables.merge_cells("B3:C3")
    tables.merge_cells("D3:E3")
    tables["B4"], tables["C4"] = "(million m3)", "(billion barrels)"
    tables["D4"], tables["E4"] = "(million m3)", "(billion barrels)"
    tables["A5"], tables["B5"], tables["C5"] = "Initial In-Place Resources", 293125, 1845
    tables["D5"], tables["E5"] = "15,628a", "98.3a"
    tables["A6"], tables["B6"], tables["C6"] = "2025 Production", 215.66, 1.36
    tables["D6"], tables["E6"] = "56.4b", "0.35b"
    tables["A8"] = "a Crude oil initial in-place resources do not include condensate."
    # Table 2 (G-K): "Successful" over one column, "Crude Bitumen" merged
    # over two, markers, a "Pre-1972" row and a footnoted year.
    tables["G2"] = "Table 2  Development and exploratory wells, pre-1972-2025"
    tables["H3"] = "Development"
    tables.merge_cells("H3:K3")
    tables["G4"], tables["H4"], tables["I4"] = "Year", "Successful", "Crude Bitumen"
    tables.merge_cells("I4:J4")
    tables["H5"], tables["I5"], tables["J5"], tables["K5"] = "Oil", "Commercial", "Exp.", "Gas"
    tables["G6"], tables["H6"], tables["I6"], tables["J6"], tables["K6"] = (
        "Pre-1972",
        11873,
        "      *",
        "      **",
        7869,
    )
    tables["G7"], tables["H7"], tables["I7"], tables["J7"], tables["K7"] = (
        "2014c",
        2528,
        2033,
        0,
        1565,
    )
    tables["G9"] = "*  Included in Oil."
    # Table 3 (M-O): 2025's reserves table, a formation name on its own row
    # above each data row.
    tables["M2"] = "Table 3 Remaining proved + probable reserves volumes"
    tables["M3"], tables["N3"] = "Category", "Oil"
    tables.merge_cells("M3:M4")
    tables.merge_cells("N3:O3")
    tables["N4"], tables["O4"] = "MMbbl", "106 m3"
    tables["M5"] = "Duvernay Formation"
    tables.merge_cells("M5:O5")
    tables["M6"], tables["N6"], tables["O6"] = "2P Producing & Undeveloped Reserves", 1735, 276
    tables["M7"] = "Spirit River Formation"
    tables["M8"], tables["N8"], tables["O8"] = "2P Producing & Undeveloped Reserves", "-", "-"
    tables["M10"] = "Any discrepancy is due to rounding."

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _block(blocks: list[st98.ParsedBlock], table_id: str) -> st98.ParsedBlock:
    return next(b for b in blocks if b.table_id == table_id)


def test_parse_workbook_finds_every_block():
    blocks = st98.parse_workbook(_workbook())
    assert [b.table_id for b in blocks] == [
        "figure_1",
        "figure_8",
        "figure_10",
        "table_1",
        "table_2",
        "table_3",
    ]


def test_monthly_rows_keep_the_month_and_each_column_its_unit():
    block = _block(st98.parse_workbook(_workbook()), "figure_1")
    assert [s.label for s in block.series] == ["WTI (US$/bbl)", "WTI-WCS Differential (US$/bbl)"]
    assert block.rows[0].period == "2017-01"
    assert block.rows[0].year == 2017
    assert block.rows[1].values == [53.46, 14.32]
    assert block.notes == ["Prices are in nominal dollars."]


def test_merged_unit_spans_its_group_and_footnote_letters_are_trimmed():
    block = _block(st98.parse_workbook(_workbook()), "figure_8")
    assert [s.label for s in block.series] == [
        "Coal (petajoules)",
        "Natural gas (petajoules)",
        "Coal (million barrels per day)",
        "Natural gas (million barrels per day)",
    ]
    assert block.estimated_years() == {2025}


def test_label_column_group_header_applies_through_its_merge():
    block = _block(st98.parse_workbook(_workbook()), "figure_10")
    assert block.series[0].label == (
        "Percentage of total bitumen production - In situ bitumen upgraded"
    )


def test_items_values_with_footnote_letters():
    block = _block(st98.parse_workbook(_workbook()), "table_1")
    assert block.series[2].label == "Crude oil (million m3)"
    row = block.rows[0]
    assert row.is_item and row.label == "Initial In-Place Resources"
    assert row.values == [293125.0, 1845.0, 15628.0, 98.3]
    assert row.markers == [None, None, "a", "a"]


def test_spans_follow_merges_not_blank_cells():
    """'Successful' covers one column; 'Gas' is not under 'Crude Bitumen'."""
    block = _block(st98.parse_workbook(_workbook()), "table_2")
    assert [s.label for s in block.series] == [
        "Development - Successful - Oil",
        "Development - Crude Bitumen - Commercial",
        "Development - Crude Bitumen - Exp.",
        "Development - Gas",
    ]
    pre, footnoted = block.rows
    assert (pre.label, pre.year, pre.is_item) == ("Pre-1972", None, False)
    assert pre.values[1:3] == [None, None]
    assert pre.markers[1:3] == ["*", "**"]
    assert (footnoted.label, footnoted.year) == ("2014c", 2014)


def test_section_rows_prefix_the_item_and_powers_of_ten_return():
    block = _block(st98.parse_workbook(_workbook()), "table_3")
    assert [s.label for s in block.series] == ["Oil - MMbbl", "Oil - 10^6 m3"]
    assert [r.label for r in block.rows] == [
        "Duvernay Formation - 2P Producing & Undeveloped Reserves",
        "Spirit River Formation - 2P Producing & Undeveloped Reserves",
    ]
    assert block.rows[1].markers == ["-", "-"]
    assert block.notes == ["Any discrepancy is due to rounding."]


def test_slim_styles_keeps_dates_as_dates():
    from openpyxl import load_workbook

    slim = st98.slim_styles(_workbook())
    sheet = load_workbook(io.BytesIO(slim), read_only=True)["Figures"]
    assert next(sheet.iter_rows(min_row=34, max_row=34, min_col=3, max_col=3, values_only=True))[
        0
    ] == datetime(2017, 1, 1)


def test_editions_from_page_reads_every_path_scheme():
    found = client.st98_editions_from_page(_PAGE)
    assert sorted(found) == [2023, 2024, 2025, 2026]
    assert found[2023].endswith("/ST98/2023/ST98_executive_summary-data.xlsx")
    assert found[2026].startswith("https://www.aer.ca/prd/")


def _mock_page_and_workbook(httpx_mock, body: bytes | None = None) -> None:
    httpx_mock.add_response(url=constants.ST98_PAGE_URL, text=_PAGE)
    # www.aer.ca answers every document link with a 301 to static.aer.ca.
    httpx_mock.add_response(
        url=constants.ST98_WORKBOOKS[2026], status_code=301, headers={"location": _STATIC_2026}
    )
    httpx_mock.add_response(url=_STATIC_2026, content=body if body is not None else _workbook())


async def test_list_tables_defaults_to_the_latest_edition(httpx_mock):
    _mock_page_and_workbook(httpx_mock)
    result = await client.list_st98_tables()
    assert result.edition == 2026
    assert [e.edition for e in result.editions] == [2026, 2025, 2024, 2023, 2022]
    figure_8 = next(t for t in result.tables if t.table == "figure_8")
    assert figure_8.title == "Total primary energy production in Alberta"
    assert figure_8.has_forecast is True
    assert (figure_8.first_year, figure_8.last_year) == (2025, 2026)
    table_1 = next(t for t in result.tables if t.table == "table_1")
    assert table_1.title == "Resources, reserves and production summary"
    assert "copyright-and-disclaimer" in (result.provenance.licence or "")
    assert result.provenance.coverage is None


async def test_list_tables_query_filters(httpx_mock):
    _mock_page_and_workbook(httpx_mock)
    result = await client.list_st98_tables(query="bitumen")
    assert {t.table for t in result.tables} == {"figure_10", "table_1", "table_2"}


async def test_get_table_flags_forecast_and_estimates(httpx_mock):
    _mock_page_and_workbook(httpx_mock)
    result = await client.get_st98_table("Figure 8", series="petajoules")
    assert result.table == "figure_8"
    assert result.forecast_from == 2026
    by_key = {(o.series, o.year): o for o in result.observations}
    history = by_key[("Natural gas (petajoules)", 2025)]
    assert (history.value, history.forecast, history.estimated) == (5000.25, False, True)
    forecast = by_key[("Coal (petajoules)", 2026)]
    assert (forecast.value, forecast.forecast, forecast.unit) == (290.0, True, "petajoules")
    assert result.total_observations == 4


async def test_get_table_forecast_filter_and_years(httpx_mock):
    _mock_page_and_workbook(httpx_mock)
    result = await client.get_st98_table("figure_8", forecast=True)
    assert {o.year for o in result.observations} == {2026}
    cache_module._caches.clear()
    _mock_page_and_workbook(httpx_mock)
    result = await client.get_st98_table("figure_8", start_year=2025, end_year=2025)
    assert {o.year for o in result.observations} == {2025}


async def test_get_table_items_have_a_category_and_no_forecast(httpx_mock):
    _mock_page_and_workbook(httpx_mock)
    result = await client.get_st98_table("table_1", lang="fr")
    first = result.observations[0]
    assert first.category == "Initial In-Place Resources"
    assert first.forecast is None
    assert result.observations[2].marker == "a"
    assert "Conditions de droit d'auteur" in (result.provenance.licence or "")
    assert result.provenance.limits and "anglais" in result.provenance.limits


async def test_get_table_unknown_table_lists_the_ids(httpx_mock):
    _mock_page_and_workbook(httpx_mock)
    with pytest.raises(NotFound, match="figure_1, figure_8"):
        await client.get_st98_table("figure_99")


async def test_get_table_unknown_series_lists_the_series(httpx_mock):
    _mock_page_and_workbook(httpx_mock)
    with pytest.raises(NotFound, match=re.escape("Coal (petajoules)")):
        await client.get_st98_table("figure_8", series="uranium")


async def test_get_table_rejects_a_malformed_id():
    with pytest.raises(InvalidInput):
        await client.get_st98_table("chart 3")


async def test_get_table_rejects_reversed_years():
    with pytest.raises(InvalidInput):
        await client.get_st98_table("figure_8", start_year=2030, end_year=2020)


async def test_unknown_edition_is_not_found(httpx_mock):
    httpx_mock.add_response(url=constants.ST98_PAGE_URL, text=_PAGE)
    with pytest.raises(NotFound, match="2019"):
        await client.list_st98_tables(2019)


async def test_page_down_falls_back_to_recorded_editions(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("refused"), url=constants.ST98_PAGE_URL)
    httpx_mock.add_exception(httpx.ConnectError("refused"), url=constants.ST98_PAGE_URL)
    httpx_mock.add_exception(httpx.ConnectError("refused"), url=constants.ST98_PAGE_URL)
    httpx_mock.add_response(url=constants.ST98_WORKBOOKS[2024], content=_workbook())
    result = await client.list_st98_tables(2024)
    assert result.edition == 2024
    assert result.provenance.coverage and "did not answer" in result.provenance.coverage


async def test_a_page_that_is_not_a_workbook_is_an_upstream_error(httpx_mock):
    _mock_page_and_workbook(httpx_mock, body=b"<html>maintenance</html>")
    with pytest.raises(UpstreamError, match="not an Excel workbook"):
        await client.get_st98_table("figure_8")


async def test_a_workbook_without_figures_is_an_upstream_error(httpx_mock):
    wb = Workbook()
    buffer = io.BytesIO()
    wb.save(buffer)
    _mock_page_and_workbook(httpx_mock, body=buffer.getvalue())
    with pytest.raises(UpstreamError, match="layout"):
        await client.list_st98_tables()
