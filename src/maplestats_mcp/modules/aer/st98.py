"""Parser for the ST98 (Alberta Energy Outlook) executive-summary workbooks.

Read from the 2022-2026 workbooks on 2026-11-07:

1. Each workbook has a "Figures" sheet and a "Tables" sheet (plus a
   disclaimer, units and, from 2026, definitions). Every block on them sits
   side by side on one row: a cell "Figure 8" (or "Table 1 Resources,
   reserves, and production summary") opens a block that runs right up to
   the next title on that row. The workbook gives no figure captions, only
   the number, so titles come from constants.ST98_TITLES.
2. Under the title, one to three header rows: a group spanning several
   columns ("Number of wells drilled", "Per cent of total (%)"), the series
   names, and units in parentheses ("(petajoules)"). A header that covers
   several columns is a merged cell, so spans come from the sheet's merged
   ranges, never from filling blanks rightwards: "Successful" over one
   column and "Crude Bitumen" over two sit on the same row of Table 2.
3. The first column holds the row label: a year (2025, "2014c" with a
   footnote letter, "Pre-1972"), a month as a date (Figure 1's monthly
   prices), or an item ("Proved Developed Producing (PDP)", "Total").
4. Values are numbers, numbers with a footnote letter glued on ("15,628a",
   "53.9b"), or markers ("*" included in oil, "**" not available).
5. Notes follow the last data row in the label column: sources, footnotes,
   and "2025 values are estimated."
6. History runs to the year before the edition; the edition year onwards is
   AER's forecast (the 2026 edition: history to 2025, forecast 2026-2035).
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from maplestats_mcp.modules.aer import constants
from maplestats_mcp.shared.executor import check_deadline

_TITLE = re.compile(r"^\s*(Figure|Table)\s+(\d+)\b", re.IGNORECASE)
_NUMBER = re.compile(r"^(-?[\d,]*\.?\d+)\s*([a-z]{0,2})$")
_YEAR_LABEL = re.compile(r"^(1[89]\d\d|20\d\d|21\d\d)\s*([a-z*]{0,3})$")
_PAREN = re.compile(r"^\((.*)\)$")
_TRAILING_UNIT = re.compile(r"^(.*\S)\s*\(([^()]+)\)$")
_ESTIMATED = re.compile(r"\b((?:19|20)\d\d)\b values are estimated", re.IGNORECASE)
_SPACES = re.compile(r"\s+")
_POWER = re.compile(r"\b10([369]) (m3|BOE)")
_MERGE_REF = re.compile(rb'<(?:\w+:)?mergeCell\s+ref="([A-Z]+\d+:[A-Z]+\d+)"')
_STYLE_XFS = re.compile(rb"<cellStyleXfs\b.*?</cellStyleXfs>", re.DOTALL)
_CELL_STYLES = re.compile(rb"<cellStyles\b.*?</cellStyles>", re.DOTALL)
_XF_ID = re.compile(rb'xfId="\d+"')
_ONE_STYLE_XF = (
    b'<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
)
_ONE_CELL_STYLE = (
    b'<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
)
# A footnote letter or asterisks glued to the end of a header word
# ("Oil sandsa", "Natural gasa", "Totala", "Bitumen**"). A blind "drop the
# last letter" would eat real words, so only these stems are trimmed.
_FOOTNOTE_STEMS = re.compile(
    r"\b(sands|gas|resources|renewables|total|bitumen|oil|production)[a-d]\b", re.IGNORECASE
)


@dataclass
class ParsedSeries:
    label: str
    unit: str | None


@dataclass
class ParsedRow:
    label: str
    year: int | None
    period: str | None
    is_item: bool
    values: list[float | None]
    markers: list[str | None]


@dataclass
class ParsedBlock:
    table_id: str
    kind: str
    number: int
    sheet: str
    heading: str
    series: list[ParsedSeries] = field(default_factory=list)
    rows: list[ParsedRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def estimated_years(self) -> set[int]:
        return {int(y) for note in self.notes for y in _ESTIMATED.findall(note)}


def clean(value: Any) -> str:
    """A header or note cell as one line of text.

    "10^6 m3" loses its superscript in the cell text and reads "106 m3";
    the power is put back so the unit does not read as 106 cubic metres.
    """
    if value is None:
        return ""
    return _POWER.sub(r"10^\1 \2", _SPACES.sub(" ", str(value)).strip())


def _header_name(text: str) -> str:
    text = text.rstrip("*").strip()
    return _FOOTNOTE_STEMS.sub(lambda m: m.group(1), text)


def parse_value(value: Any) -> tuple[float | None, str | None, bool]:
    """(number, marker, is_value) for one data cell.

    is_value says the cell carries data (a number, or a marker such as "*");
    an empty cell is (None, None, False).
    """
    if value is None or isinstance(value, bool):
        return None, None, False
    if isinstance(value, int | float):
        # Sums in the sheet carry float noise (26728.530000000002).
        return float(f"{value:.12g}"), None, True
    text = clean(value)
    if not text:
        return None, None, False
    match = _NUMBER.match(text)
    if match:
        return float(match.group(1).replace(",", "")), match.group(2) or None, True
    if set(text) <= {"*", "-", "–", "—", "."}:
        return None, text, True
    return None, None, False


def _is_number(value: Any) -> bool:
    number, _, _ = parse_value(value)
    return number is not None


def parse_label(value: Any) -> tuple[str, int | None, str | None, bool] | None:
    """(label, year, period, is_item) for a row label, or None for an empty one."""
    if isinstance(value, datetime | date):
        return (
            f"{value.year:04d}-{value.month:02d}",
            value.year,
            f"{value.year:04d}-{value.month:02d}",
            False,
        )
    if isinstance(value, int | float) and not isinstance(value, bool):
        if float(value).is_integer() and 1800 <= value <= 2200:
            return str(int(value)), int(value), None, False
        return clean(value), None, None, True
    text = clean(value)
    if not text:
        return None
    match = _YEAR_LABEL.match(text)
    if match:
        return text, int(match.group(1)), None, False
    if text.lower().startswith("pre-"):
        return text, None, None, False
    return text, None, None, True


def merged_ranges(body: bytes) -> dict[str, list[tuple[int, int, int, int]]]:
    """Sheet title -> its merged ranges as (min_col, min_row, max_col, max_row), 1-based.

    Read from the sheet XML directly: openpyxl's read-only worksheets do not
    expose merged cells, and loading the workbook in full to get them took
    about 11 s for the 2026 workbook against under 1 s read-only.
    """
    from defusedxml import ElementTree
    from openpyxl.utils import range_boundaries

    main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel_id = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.get("Id"): rel.get("Target", "") for rel in rels}
        found: dict[str, list[tuple[int, int, int, int]]] = {}
        for sheet in workbook.iter(f"{main}sheet"):
            target = targets.get(sheet.get(rel_id), "")
            path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
            try:
                xml = archive.read(path)
            except KeyError:
                continue
            spans = []
            for ref in _MERGE_REF.findall(xml):
                min_col, min_row, max_col, max_row = range_boundaries(ref.decode("ascii"))
                if None not in (min_col, min_row, max_col, max_row):
                    spans.append((min_col, min_row, max_col, max_row))
            found[sheet.get("name", "")] = spans  # type: ignore[arg-type]
        return found


def _merged_lookup(
    spans: list[tuple[int, int, int, int]],
) -> dict[tuple[int, int], tuple[int, int, int]]:
    """(row, col) -> (top-left row, top-left col, last col) for every merged cell (0-based)."""
    lookup: dict[tuple[int, int], tuple[int, int, int]] = {}
    for min_col, min_row, max_col, max_row in spans:
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                lookup[(r - 1, c - 1)] = (min_row - 1, min_col - 1, max_col - 1)
    return lookup


def _cell(grid: list[list[Any]], r: int, c: int) -> Any:
    if r < len(grid) and c < len(grid[r]):
        return grid[r][c]
    return None


def _header_cell(
    grid: list[list[Any]],
    merged: dict[tuple[int, int], tuple[int, int, int]],
    r: int,
    c: int,
    first: int,
    end: int,
) -> str:
    """The header text over column c on row r, following a merged span inside the block."""
    span = merged.get((r, c))
    if span is not None:
        top, left, right = span
        if left >= first and right < end:
            return clean(_cell(grid, top, left))
    return clean(_cell(grid, r, c))


def parse_block(
    grid: list[list[Any]],
    merged: dict[tuple[int, int], tuple[int, int, int]],
    sheet: str,
    title_row: int,
    first: int,
    end: int,
) -> ParsedBlock | None:
    """One Figure or Table block: columns first..end-1, title on title_row."""
    heading = clean(grid[title_row][first])
    match = _TITLE.match(heading)
    if match is None:
        return None
    kind = match.group(1).lower()
    number = int(match.group(2))
    block = ParsedBlock(
        table_id=f"{kind}_{number}", kind=kind, number=number, sheet=sheet, heading=heading
    )
    value_cols = range(first + 1, end)

    def numeric(r: int) -> bool:
        return any(_is_number(_cell(grid, r, c)) for c in value_cols)

    def has_values(r: int) -> bool:
        """Numbers or markers: a reserves row can be all "-" (no oil in that formation)."""
        return any(parse_value(_cell(grid, r, c))[2] for c in value_cols)

    first_data = next((r for r in range(title_row + 1, len(grid)) if numeric(r)), None)
    if first_data is None:
        return None

    def label_only(r: int) -> str | None:
        """The row's text when only the label column holds any (a section or a note)."""
        text = clean(_cell(grid, r, first))
        if not text or any(clean(_cell(grid, r, c)) for c in value_cols):
            return None
        return text

    # The 2025 reserves table puts a formation name on its own row above each
    # data row ("Duvernay Formation", then "2P Producing & Undeveloped
    # Reserves" with the numbers): a label-only row with numbers after it is
    # a section heading, and label-only rows after the last numbers are notes.
    section = None
    header_end = first_data
    if first_data - 1 > title_row and label_only(first_data - 1):
        section = label_only(first_data - 1)
        header_end = first_data - 1

    data_rows: list[tuple[int, str | None]] = []
    pending: list[str] = []
    in_notes = False
    for r in range(first_data, len(grid)):
        check_deadline()
        texts = [clean(_cell(grid, r, c)) for c in range(first, end)]
        if any(_TITLE.match(t) for t in texts):
            break
        if has_values(r):
            if in_notes:
                break
            if pending:
                section = pending[-1]
                pending = []
            data_rows.append((r, section))
            continue
        if not any(texts):
            continue
        line = " ".join(t for t in texts if t)
        heading = label_only(r)
        if not in_notes and heading and not heading.endswith("."):
            pending.append(line)
            continue
        in_notes = True
        block.notes.extend(pending)
        pending = []
        block.notes.append(line)
    block.notes.extend(pending)

    # A header over the label column counts only when its merged cell spans
    # value columns too (2026 Figure 10's "Percentage of total bitumen
    # production"); _header_cell finds those through the value columns.
    header_rows = range(title_row + 1, header_end)
    kept: list[int] = []
    labels: list[str] = []
    for c in value_cols:
        if not any(parse_value(_cell(grid, r, c))[2] for r, _ in data_rows):
            continue
        names: list[str] = []
        unit: str | None = None
        for r in header_rows:
            text = _header_cell(grid, merged, r, c, first, end)
            if not text:
                continue
            paren = _PAREN.match(text)
            if paren:
                unit = unit or paren.group(1).strip()
            elif _header_name(text) not in names:
                names.append(_header_name(text))
        parts = names
        if unit is None:
            for part in parts:
                trailing = _TRAILING_UNIT.match(part)
                if trailing:
                    unit = trailing.group(2).strip()
        elif any("share" in n.lower() for n in names):
            # Figure 4 (2026) merges "(million barrels per day)" across the
            # share column too; a share has no such unit.
            unit = None
        label = " - ".join(parts) or f"column {c + 1}"
        if unit and f"({unit})" not in label:
            label = f"{label} ({unit})"
        while label in labels:
            label = f"{label} [{len(labels)}]"
        labels.append(label)
        kept.append(c)
        block.series.append(ParsedSeries(label=label, unit=unit))

    for r, row_section in data_rows:
        parsed = parse_label(_cell(grid, r, first))
        if parsed is None:
            continue
        label, year, period, is_item = parsed
        if row_section:
            label = f"{row_section} - {label}"
        values: list[float | None] = []
        markers: list[str | None] = []
        for c in kept:
            number, marker, _ = parse_value(_cell(grid, r, c))
            values.append(number)
            markers.append(marker)
        block.rows.append(ParsedRow(label, year, period, is_item, values, markers))
    return block if block.series and block.rows else None


def slim_styles(body: bytes) -> bytes:
    """The workbook with its named cell styles cut down to one.

    The 2026 workbook's styles.xml is 12 MB: 55,214 named styles, copied in
    from other workbooks over the years. openpyxl expands every one of them
    even in read-only mode, which took about 10 s of the 10.5 s it spent on
    the file. Cells keep their own formats (cellXfs, numFmts), so dates still
    read as dates; only the named-style layer, which no value depends on, goes.
    """
    source = zipfile.ZipFile(io.BytesIO(body))
    out = io.BytesIO()
    with source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "xl/styles.xml":
                data = _STYLE_XFS.sub(_ONE_STYLE_XF, data, count=1)
                data = _CELL_STYLES.sub(_ONE_CELL_STYLE, data, count=1)
                data = _XF_ID.sub(b'xfId="0"', data)
            target.writestr(info, data)
    return out.getvalue()


def parse_workbook(body: bytes) -> list[ParsedBlock]:
    """Every Figure and Table block of an ST98 executive-summary workbook."""
    from openpyxl import load_workbook

    spans = merged_ranges(body)
    workbook = load_workbook(io.BytesIO(slim_styles(body)), read_only=True, data_only=True)
    try:
        blocks: list[ParsedBlock] = []
        for sheet in workbook.worksheets:
            grid = [
                list(row)
                for row in sheet.iter_rows(
                    max_row=constants.ST98_MAX_SHEET_ROWS,
                    max_col=constants.ST98_MAX_SHEET_COLUMNS,
                    values_only=True,
                )
            ]
            merged = _merged_lookup(spans.get(sheet.title, []))
            for r, row in enumerate(grid):
                titles = [c for c, v in enumerate(row) if isinstance(v, str) and _TITLE.match(v)]
                for k, c in enumerate(titles):
                    end = titles[k + 1] if k + 1 < len(titles) else len(row)
                    block = parse_block(grid, merged, sheet.title, r, c, end)
                    if block is not None:
                        blocks.append(block)
        return blocks
    finally:
        workbook.close()
