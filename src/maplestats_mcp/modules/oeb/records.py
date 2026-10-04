"""Read OEB XML and Excel files as flat records (blocking; run in the parse pool).

XML, as read from all 196 linked XML files on 2026-10-03, comes in three
shapes, all handled by one rule (a record is an element whose children are
all leaves):

- Microsoft Access exports (`<dataroot xmlns:od=...>` then one element per
  row, e.g. `<ED_x0020_2142_x0020_System_x0020_Reliability_x0020_Indicators>`),
  the RRR files. Access escapes characters in names as `_xHHHH_`
  (`_x0020_` space, `_x002C_` comma, `_x0028_` parenthesis) and leaves out an
  element when its value is empty, so the field list is the union over rows.
- Flat report tables (`<BillDataTable><BillDataRow>`, `<PerformanceItemsTable>`,
  `<data>`, `<RS>`; one file puts its rows in the
  `urn:schemas-microsoft-com:xml-analysis:rowset` namespace, which is dropped).
- Nested Oracle-report XML: `<ALL_LICENCES><LIST_G_LICENCE_NUMBER>
  <G_LICENCE_NUMBER>`, `<MODULE2><LIST_G_LINEITEM><G_LINEITEM>`, the open
  applications file.

Parsing is incremental (`iterparse`): each record is removed from its parent
once read, so a 62 MB file never becomes a tree. A DTD is refused (defusedxml).
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from datetime import date, datetime, time
from typing import Any

from defusedxml.ElementTree import iterparse

from maplestats_mcp.shared.executor import check_deadline

_ESCAPE = re.compile(r"_x([0-9A-Fa-f]{4})_")
_SPACES = re.compile(r"\s+")
_NUMBER = re.compile(r"^-?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_XSD = "http://www.w3.org/2001/XMLSchema"
HEADER_SEARCH_ROWS = 30
HEADER_MIN_CELLS = 3

Cell = int | float | str | None


def label(tag: str) -> str:
    """A readable field name: namespace dropped, `_xHHHH_` decoded, `_` as space."""
    local = tag.rsplit("}", 1)[-1]
    decoded = _ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), local)
    return _SPACES.sub(" ", decoded.replace("_", " ")).strip()


def to_cell(text: str | None) -> Cell:
    """Whitespace collapsed; plain numbers become int or float; blank is None."""
    if text is None:
        return None
    value = _SPACES.sub(" ", text).strip()
    if not value:
        return None
    if _NUMBER.match(value):
        number = float(value)
        if "." not in value and "e" not in value.lower() and abs(number) < 2**53:
            return int(value)
        return number
    return value


def xml_records(body: bytes) -> Iterator[tuple[str, dict[str, Cell]]]:
    """(record tag, record) for every record element in document order."""
    stack: list[Any] = []
    # Per open element: whether a record was read inside it. Records are
    # removed once read, so without this an emptied <LIST_G_...> would look
    # like a field and its parent like a one-field record.
    holds: list[bool] = []
    skip = 0
    count = 0
    for event, elem in iterparse(io.BytesIO(body), events=("start", "end"), forbid_dtd=True):
        if event == "start":
            stack.append(elem)
            holds.append(False)
            if str(elem.tag).startswith("{" + _XSD + "}"):
                skip += 1
            continue
        stack.pop()
        container = holds.pop()
        if str(elem.tag).startswith("{" + _XSD + "}"):
            skip -= 1
            continue
        if container:
            if holds:
                holds[-1] = True
            continue
        if skip or len(elem) == 0 or any(len(child) for child in elem):
            continue
        record = {label(child.tag): to_cell(child.text) for child in elem}
        if stack:
            stack[-1].remove(elem)
            holds[-1] = True
        else:
            elem.clear()
        count += 1
        if count % 500 == 0:
            check_deadline()
        yield label(elem.tag), record


def _xlsx_cell(value: Any) -> Cell:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return int(value) if isinstance(value, float) and value.is_integer() else value
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0) else value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return to_cell(str(value))


def xlsx_sheets(body: bytes) -> list[str]:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()


def xlsx_records(body: bytes, sheet: str) -> Iterator[dict[str, Cell]]:
    """Rows of one sheet as records keyed by its header row.

    The header is the first of the first 30 rows with three filled cells: the
    rates databases put a title and a note above it, the yearbook and RPP
    workbooks start with it. Header text has line breaks collapsed
    ('Off-Peak price \\n(¢ per kWh)'); a blank or repeated header becomes
    'column N'. Rows with no value at all are skipped.
    """
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    try:
        rows = workbook[sheet].iter_rows(values_only=True)
        header: list[str] | None = None
        for index, raw in enumerate(rows):
            cells = [_xlsx_cell(c) for c in raw]
            if header is None:
                if sum(1 for c in cells if c is not None) >= HEADER_MIN_CELLS:
                    header = _header(cells)
                elif index >= HEADER_SEARCH_ROWS:
                    return
                continue
            if all(c is None for c in cells):
                continue
            if index % 500 == 0:
                check_deadline()
            yield {name: cells[i] if i < len(cells) else None for i, name in enumerate(header)}
    finally:
        workbook.close()


def _header(cells: list[Cell]) -> list[str]:
    last = max(i for i, c in enumerate(cells) if c is not None)
    names: list[str] = []
    for i, cell in enumerate(cells[: last + 1]):
        name = _SPACES.sub(" ", str(cell)).strip() if cell is not None else ""
        if not name or name in names:
            name = f"column {i + 1}"
        names.append(name)
    return names
