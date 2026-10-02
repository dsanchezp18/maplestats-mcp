"""Read `.xlsx` workbooks sheet by sheet as published text, for agency tables.

Agency workbooks (BC Stats, provincial statistics bureaus) are laid out for
people: title rows above the table, two- and three-row column headers, years
across columns. Nothing here reshapes them; a sheet comes back as rows of
text with a guessed header row, so the caller sees what the agency published.
nl_stats keeps its own copy of the same cell and header logic (it also reads
legacy `.xls`) and is left as is.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

from maplestats_mcp.shared.errors import InvalidInput

# A header row is the first of the first rows with this many filled cells.
HEADER_MIN_CELLS = 3
HEADER_SEARCH_ROWS = 30


def cell_text(value: Any) -> str:
    """One cell as text: whole floats lose the `.0`, dates are ISO, blanks are ''."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ") if value.time() else value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return " ".join(str(value).split())


def trim_rows(rows: list[list[str]]) -> list[list[str]]:
    """Drop trailing empty rows and columns, and pad every row to one width."""
    while rows and not any(rows[-1]):
        rows.pop()
    width = max((max((i for i, c in enumerate(r) if c), default=-1) + 1 for r in rows), default=0)
    return [r[:width] + [""] * (width - len(r[:width])) for r in rows]


def sheet_dimensions(body: bytes) -> list[tuple[str, int | None, int | None]]:
    """Sheet names with the row and column counts the file declares (None if absent)."""
    # openpyxl takes ~0.7 s to import, so it loads on first use.
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    try:
        return [(ws.title, ws.max_row, ws.max_column) for ws in workbook.worksheets]
    finally:
        workbook.close()


def read_sheet(body: bytes, sheet: str, max_rows: int) -> tuple[list[list[str]], bool]:
    """Rows of one sheet as text, capped at `max_rows`; the flag says rows were cut."""
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    try:
        if sheet not in workbook.sheetnames:
            raise InvalidInput(f"No sheet {sheet!r}; sheets are {workbook.sheetnames}.")
        rows: list[list[str]] = []
        capped = False
        for raw in workbook[sheet].iter_rows(values_only=True):
            if len(rows) >= max_rows:
                capped = True
                break
            rows.append([cell_text(c) for c in raw])
        return trim_rows(rows), capped
    finally:
        workbook.close()


def guess_header(rows: list[list[str]]) -> int | None:
    """0-based index of the first row with at least three filled cells."""
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        if sum(1 for cell in row if cell) >= HEADER_MIN_CELLS:
            return index
    return None
