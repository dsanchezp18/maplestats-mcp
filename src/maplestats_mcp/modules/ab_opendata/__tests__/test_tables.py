"""Tests for the Open Alberta table reader on layouts seen in the live files.

The layouts mirror files read on 2026-10-02: a title row above a 5-column
header (AISH caseload), a header split over two rows with years above
labels (highway traffic volumes), a one-column index sheet, a report
parameters sheet with two columns, and an .xlsx resource that is really an
.xls file.
"""

from __future__ import annotations

import io
from typing import Any

import pytest

from maplestats_mcp.modules.ab_opendata import tables
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError


def _xlsx(sheets: dict[str, list[list[Any]]]) -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    book.remove(book.worksheets[0])
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _scan(rows, **kwargs):
    options = {"csv_like": False, **kwargs}
    return tables.scan_rows(rows, **options)


CASELOAD = [
    ["AISH caseload"],
    ["Ref_Date", "Geography", "Measure", "Value"],
    ["2008/04", "Alberta", "Single Total", "32948"],
    ["2008/04", "Calgary", "Single Total", "10000"],
    ["2008/05", "Alberta", "Single Total", "33000"],
]


def test_title_row_is_skipped_and_header_guessed():
    result = _scan(CASELOAD, limit=10)
    assert result.header_row == 2
    assert result.all_columns == ["Ref_Date", "Geography", "Measure", "Value"]
    assert result.total_rows == 3


def test_filters_are_exact_and_case_insensitive_and_columns_selectable():
    result = _scan(CASELOAD, filters={"geography": " alberta "}, columns=["Ref_Date", "Value"])
    assert result.total_rows == 2
    assert result.rows == [
        {"Ref_Date": "2008/04", "Value": "32948"},
        {"Ref_Date": "2008/05", "Value": "33000"},
    ]
    assert _scan(CASELOAD, filters={"Geography": "Alb"}).total_rows == 0


def test_contains_offset_and_limit_count_all_matches():
    result = _scan(CASELOAD, contains="single", offset=1, limit=1)
    assert result.total_rows == 3
    assert [r["Geography"] for r in result.rows] == ["Calgary"]


def test_unknown_column_lists_the_real_ones():
    with pytest.raises(InvalidInput, match="Geography"):
        _scan(CASELOAD, filters={"Region": "x"})
    with pytest.raises(InvalidInput, match="Value"):
        _scan(CASELOAD, columns=["Nope"])


def test_header_row_override_and_too_large_row():
    result = _scan(CASELOAD, header_row=1, limit=1)
    assert result.all_columns[0] == "AISH caseload"
    with pytest.raises(InvalidInput, match="only 5 rows"):
        _scan(CASELOAD, header_row=9)


def test_two_row_header_is_joined_per_column():
    rows = [
        ["", "ALBERTA HIGHWAYS"],
        [],
        ["", "", "", "2016", "2017"],
        ["", "Hwy", "Muni", "AADT", "AADT"],
        ["", "1", "BNP", "7330", "7580"],
        ["", "1", "CAL", "9000", "9100"],
    ]
    result = _scan(rows, header_row=3, header_rows=2)
    assert result.all_columns == ["column_1", "Hwy", "Muni", "2016 AADT", "2017 AADT"]
    assert result.rows[0] == {
        "column_1": "",
        "Hwy": "1",
        "Muni": "BNP",
        "2016 AADT": "7330",
        "2017 AADT": "7580",
    }


def test_duplicate_and_blank_headers_get_unique_names():
    rows = [["Total", "Total", "", "Year"], ["1", "2", "3", "2020"]]
    result = _scan(rows, csv_like=True)
    assert result.all_columns == ["Total", "Total_2", "column_3", "Year"]


def test_ragged_rows_are_padded_and_empty_rows_dropped():
    rows = [["a", "b", "c"], ["1"], [], ["", ""], ["2", "x", "y"]]
    result = _scan(rows, csv_like=True)
    assert result.total_rows == 2
    assert result.rows[0] == {"a": "1", "b": "", "c": ""}


def test_two_column_csv_still_gets_a_header():
    rows = [["year", "value"], ["2020", "5"]]
    assert _scan(rows, csv_like=True).header_row == 1
    assert _scan(rows, csv_like=False).header_row == 1


def test_csv_with_bom_semicolons_and_cp1252():
    body = "﻿nom;année;valeur\nÉdith;2020;5\nLéa;2021;6\n".encode()
    rows = list(tables._csv_rows(body))
    assert rows[0] == ["nom", "année", "valeur"]
    legacy = "nom,ville\nJosé,Québec\n".encode("cp1252")
    assert list(tables._csv_rows(legacy))[1] == ["José", "Québec"]


def test_format_is_detected_from_bytes_not_from_the_portal_label():
    xlsx = _xlsx({"A": [["a", "b", "c"], [1, 2, 3]]})
    assert tables.detect_format(xlsx, "XLS") == "xlsx"
    assert tables.detect_format(b"\xd0\xcf\x11\xe0" + b"0" * 20, "XLSX") == "xls"
    assert tables.detect_format(b"a,b\n1,2\n", "CSV") == "csv"
    with pytest.raises(UpstreamError, match="web page"):
        tables.detect_format(b"<!DOCTYPE html><html>", "CSV")
    with pytest.raises(UpstreamError, match="not a readable"):
        tables.detect_format(b"%PDF-1.4", "PDF")


def test_xlsx_sheets_largest_sheet_is_default_and_dates_are_text():
    from datetime import datetime

    body = _xlsx(
        {
            "Report Parameters": [["@PeriodFrom", "2025"], ["@PeriodTo", "2025"]],
            "Data": [["Project", "Year", "Revenue"]]
            + [[f"P{i}", datetime(2025, 1, 1), i * 1.5] for i in range(30)],  # noqa: DTZ001,
        }
    )
    sizes = tables.sheet_sizes(body, "xlsx")
    assert [s[0] for s in sizes] == ["Report Parameters", "Data"]
    assert tables.largest_sheet(sizes) == "Data"
    result = tables.scan(
        body,
        "xlsx",
        "Data",
        header_row=None,
        header_rows=1,
        columns=None,
        filters={"project": "P3"},
        contains=None,
        offset=0,
        limit=5,
    )
    assert result.rows == [{"Project": "P3", "Year": "2025-01-01", "Revenue": "4.5"}]
    total, summaries = tables.describe(body, "xlsx", None)
    assert total == 2
    assert summaries[1].header_row == 1
    assert summaries[1].column_names == ["Project", "Year", "Revenue"]
    assert len(summaries[1].preview) == tables.constants.PREVIEW_ROWS


def test_wrong_dimension_in_a_sheet_does_not_hide_rows():
    # Some writers store <dimension ref="A1"/>; openpyxl read-only mode then
    # yields one row unless the dimensions are reset.
    import re
    import zipfile

    body = _xlsx({"S": [["a", "b", "c"], [1, 2, 3], [4, 5, 6]]})
    src = zipfile.ZipFile(io.BytesIO(body))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = re.sub(rb'<dimension ref="[^"]*"/>', b'<dimension ref="A1"/>', data)
            dst.writestr(item, data)
    result = tables.scan(
        out.getvalue(),
        "xlsx",
        "S",
        header_row=None,
        header_rows=1,
        columns=None,
        filters=None,
        contains=None,
        offset=0,
        limit=10,
    )
    assert result.total_rows == 2


def test_broken_workbook_is_an_upstream_error():
    with pytest.raises(UpstreamError, match="could not"):
        tables.sheet_sizes(b"PK\x03\x04 not really a zip", "xlsx")
