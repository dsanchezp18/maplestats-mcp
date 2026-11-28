"""Read the Alberta budget's fiscal plan workbooks as labelled tables.

The fiscal plan tables (Treasury Board and Finance) are laid out for print:
a title and a units line, two header rows (fiscal years over Actual, Budget,
Forecast, Estimate, Target, with one year spanning two columns), section
labels, indented line items and footnotes. Workbooks checked live on
2026-11-24 (Budget 2026 and Budget 2025 editions) also keep hidden working
columns and sheets: the Key Assumptions sheet hides three columns whose
cells read "#REF!", the Statement of Financial Position hides a stale
"Budget" column marked "Hide Column when published", and the capital plan
workbook hides ten sheets (one named "DONOTUSE-Retained Income"). Only what
the published page shows is read: hidden sheets, rows and columns are left
out. Nothing here reaches the network.
"""

from __future__ import annotations

import io
import itertools
import re
import unicodedata
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from maplestats_mcp.shared.executor import check_deadline
from maplestats_mcp.shared.xlsx_sheets import check_inflated_size

Value = float | int | str

# A header row of years: integers in this range, in increasing order.
_YEAR_MIN, _YEAR_MAX = 1900, 2100
_SPACES = re.compile(r"\s+")
_YEARISH = re.compile(r"^\d{4}(?:-\d{2,4})?[a-z]?$")
_PLACEHOLDERS = frozenset({"n/a", "na", "-", "–", "—", "..", "...", "x", "nil"})
# Words that name a table of years rather than a line item ("Calendar Year
# Assumptions", "Fiscal year", "Hypothèses par année civile", "Exercice"). Matched as
# word starts, accents removed: the live workbooks leave a footnote letter on the
# label ("Fiscal Year Assumptionsa").
_HEADER_WORDS = re.compile(
    r"\b(?:year|fiscal|calendar|assumption|period|annee|exercice|civil|hypothese|periode)"
)


@dataclass
class SheetTitle:
    name: str
    title: str | None


@dataclass
class ParsedRow:
    label: str | None
    section: str | None
    values: dict[str, Value]


@dataclass
class ParsedSheet:
    name: str
    title: str | None
    title_lines: list[str]
    label_header: str | None
    columns: list[str]
    rows: list[ParsedRow]
    notes: list[str] = field(default_factory=list)


def _load(body: bytes) -> Any:
    # openpyxl takes ~0.7 s to import, so it loads on first use. The full (not
    # read-only) mode is needed: only it reports hidden rows and columns.
    from openpyxl import load_workbook

    check_inflated_size(body)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return load_workbook(io.BytesIO(body), data_only=True)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return _SPACES.sub(" ", str(value).replace("\xa0", " ").replace("�", "")).strip()


def _value(value: Any) -> Value | None:
    """A cell as a number when it holds one, else its text; None when blank."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # Formula results carry binary noise (14771.186000000002); the published
        # tables show at most a few decimals.
        rounded = round(value, 6)
        return int(rounded) if rounded.is_integer() and abs(rounded) < 1e15 else rounded
    if isinstance(value, datetime):
        return value.date().isoformat() if not value.time() else value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    text = _text(value)
    return text or None


def _is_number(value: Value | None) -> bool:
    return isinstance(value, int | float)


def _is_year(value: Value | None) -> bool:
    return isinstance(value, int) and _YEAR_MIN <= value <= _YEAR_MAX


def _visible_sheets(workbook: Any) -> list[Any]:
    return [ws for ws in workbook.worksheets if ws.sheet_state == "visible"]


def _hidden_columns(sheet: Any) -> set[int]:
    hidden: set[int] = set()
    for dims in sheet.column_dimensions.values():
        if dims.hidden and dims.min and dims.max:
            hidden.update(range(dims.min, dims.max + 1))
    return hidden


def _grid(sheet: Any) -> list[list[Value | None]]:
    """Visible cells only, merged ranges spread across their first row."""
    hidden_cols = _hidden_columns(sheet)
    hidden_rows = {r for r, dims in sheet.row_dimensions.items() if dims.hidden}
    spread: dict[tuple[int, int], Any] = {}
    for merged in sheet.merged_cells.ranges:
        top_left = sheet.cell(merged.min_row, merged.min_col).value
        for col in range(merged.min_col + 1, merged.max_col + 1):
            spread[(merged.min_row, col)] = top_left
    columns = [c for c in range(1, (sheet.max_column or 0) + 1) if c not in hidden_cols]
    grid: list[list[Value | None]] = []
    for index, row in enumerate(sheet.iter_rows(), start=1):
        if index % 200 == 0:
            check_deadline()
        if index in hidden_rows:
            continue
        cells = {c.column: c.value for c in row if hasattr(c, "column")}
        grid.append([_value(cells.get(c, spread.get((index, c)))) for c in columns])
    # Spacer columns (empty in every visible row) and trailing blank rows go.
    keep = [i for i in range(len(columns)) if any(r[i] is not None for r in grid)]
    grid = [[r[i] for i in keep] for r in grid]
    while grid and all(v is None for v in grid[-1]):
        grid.pop()
    return grid


def _sheet_title(grid: list[list[Value | None]]) -> str | None:
    for row in grid[:10]:
        for value in row:
            if isinstance(value, str):
                return value
    return None


def list_sheets(body: bytes) -> list[SheetTitle]:
    """The visible sheets with their first text cell as the title; covers are skipped."""
    workbook = _load(body)
    try:
        titles: list[SheetTitle] = []
        for sheet in _visible_sheets(workbook):
            if sheet.title.strip().lower() == "cover":
                continue
            check_deadline()
            titles.append(SheetTitle(sheet.title, _sheet_title(_grid(sheet))))
        return titles
    finally:
        workbook.close()


def _label_column(grid: list[list[Value | None]]) -> int:
    """The column most rows with a number start in: where line-item labels sit."""
    counts: dict[int, int] = {}
    for row in grid:
        if not any(_is_number(v) for v in row):
            continue
        first = _first_cell(row)
        if first is not None:
            counts[first] = counts.get(first, 0) + 1
    return min(counts, key=lambda i: (-counts[i], i)) if counts else 0


def _header_wording(label: str | None) -> bool:
    """Whether a row label reads like the name of a table of years, in English or French."""
    if not label:
        return False
    plain = unicodedata.normalize("NFD", label.lower())
    return bool(_HEADER_WORDS.search("".join(c for c in plain if not unicodedata.combining(c))))


def _names_years(row: list[Value | None]) -> bool:
    return any(_is_year(v) or (isinstance(v, str) and _YEARISH.match(v) is not None) for v in row)


def _header_like(
    values: list[Value | None],
    *,
    label: str | None,
    seen_data: bool,
    header_line_below: bool,
    years_above: bool,
) -> bool:
    """No figures, or a row of years (a year row over the columns).

    Whole numbers between 1900 and 2100 are also what a line item in $ millions
    looks like (1950, 1980, 2020, 2075), so a row of them is a header only on
    evidence that it is one. A row with no line-item label, with header wording in
    its label ("Calendar Year Assumptions"), or with a line of header text (Actual,
    Budget, Forecast) right under it, is a header whatever the gaps between its
    years (2017, 2019, 2025 once hidden columns are shown; 2025, 2030, 2035). A
    labelled row with none of those must have the years one after another (years do
    step by exactly one; amounts rarely do), come before the first data row, and
    not sit under header rows that already hold the years. Anything else is data and
    keeps its label and values.
    """
    filled = [v for v in values if v is not None]
    # A forecaster with no figure for any year ("n/a" in every column, Benchmark
    # sheets) is a data row, not a new header.
    if not filled or all(isinstance(v, str) and v.lower() in _PLACEHOLDERS for v in filled):
        return False
    numbers = [v for v in filled if _is_number(v)]
    if not numbers:
        return True
    if not all(_is_year(v) for v in numbers):
        return False
    # A label-less row, one named like a table of years, or one with a header line
    # under it is the header of a table (a second one too: Key Assumptions has
    # calendar years under the fiscal years).
    evidence = label is None or header_line_below or _header_wording(label)
    # Years typed as numbers beside years typed as text ('2025', 2026, '2027' on
    # the capital assets schedule).
    if any(isinstance(v, str) and _YEARISH.match(v) for v in filled):
        return evidence or not seen_data
    years = [v for v in numbers if isinstance(v, int)]
    if len(years) < 2 or not all(a < b for a, b in itertools.pairwise(years)):
        return False
    consecutive = all(b - a == 1 for a, b in itertools.pairwise(years))
    # Header rows above that already name the columns by year leave no work for
    # this row: a line item such as "Roads" 2020, 2021, 2022 is data.
    return evidence or (consecutive and not seen_data and not years_above)


def _numbering(values: list[Value | None]) -> bool:
    """A row of column numbers 1, 2, 3, ... above a header (historical fiscal summary)."""
    filled = [v for v in values if v is not None]
    return len(filled) >= 3 and filled == list(range(1, len(filled) + 1))


def _first_cell(row: list[Value | None]) -> int | None:
    """Where a row's label starts: its first text cell, else its first filled cell."""
    texts = [i for i, v in enumerate(row) if isinstance(v, str)]
    filled = [i for i, v in enumerate(row) if v is not None]
    if texts and (not filled or texts[0] <= filled[0] + 1):
        # A line number before the label (consolidated fiscal summary: 1, 'Total
        # revenue', ...) does not move the label column.
        return texts[0]
    return filled[0] if filled else None


def _header_line_below(grid: list[list[Value | None]], index: int, label_col: int) -> bool:
    """Whether the next non-blank row is a line of header text: no label, no figures."""
    for row in itertools.islice(grid, index + 1, None):
        if all(v is None for v in row):
            continue
        beside = list(row[label_col + 1 :])
        no_label = label_col >= len(row) or row[label_col] is None
        return no_label and any(v is not None for v in beside) and not any(map(_is_number, row))
    return False


def _column_names(block: list[list[Value | None]], width: int) -> list[str]:
    """Join the header rows per column, carrying a year across the column it spans.

    "2025-26" sits above both "Budget" and "Forecast": a cell left blank in an
    upper header row takes its left neighbour's text when the last header row
    has a label in that column.
    """
    filled = [[_text(v) if v is not None else "" for v in row] for row in block]
    last = filled[-1] if filled else []
    for row in filled[:-1]:
        for i in range(1, width):
            if not row[i] and row[i - 1] and i < len(last) and last[i]:
                row[i] = row[i - 1]
    names: list[str] = []
    seen: dict[str, int] = {}
    for i in range(width):
        name = " ".join(row[i] for row in filled if i < len(row) and row[i]) or f"column {i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        names.append(name)
    return names


def parse_sheet(body: bytes, name: str) -> ParsedSheet:
    """One visible sheet as titled, labelled rows of named values."""
    workbook = _load(body)
    try:
        sheet = next(ws for ws in _visible_sheets(workbook) if ws.title == name)
        grid = _grid(sheet)
    finally:
        workbook.close()
    label_col = _label_column(grid)
    width = max((len(r) for r in grid), default=0)
    value_width = max(width - label_col - 1, 0)

    title_lines: list[str] = []
    label_header: str | None = None
    columns: list[str] = []
    block: list[list[Value | None]] = []
    rows: list[ParsedRow] = []
    texts_after: list[str] = []
    section: str | None = None
    seen_data = False

    def close_block() -> None:
        nonlocal columns, block
        if block:
            columns = _column_names(block, value_width)
            block = []

    for index, raw in enumerate(grid):
        # Line numbers left of the label column are dropped.
        lead = raw[:label_col]
        if all(v is None or isinstance(v, int) for v in lead):
            raw = [None] * len(lead) + list(raw[label_col:])
        cells = [v for v in raw if v is not None]
        if not cells:
            continue
        first = next(i for i, v in enumerate(raw) if v is not None)
        label = (
            _text(raw[label_col]) if label_col < len(raw) and raw[label_col] is not None else None
        )
        values = list(raw[label_col + 1 :]) + [None] * (value_width - len(raw[label_col + 1 :]))
        if label is None and _numbering(values):
            continue
        if first < label_col or (len(cells) == 1 and not any(v is not None for v in values)):
            # One text cell: a title or units line before the table, a section
            # label inside it, a footnote after it.
            text = _text(cells[0])
            if not seen_data and not columns and not block:
                title_lines.append(text)
            else:
                close_block()
                texts_after.append(text)
            continue
        is_header = _header_like(
            values,
            label=label,
            seen_data=seen_data,
            header_line_below=label is not None and _header_line_below(grid, index, label_col),
            years_above=any(_names_years(row) for row in block),
        )
        if is_header:
            if seen_data and not block:
                # A second table on the same sheet (Key Assumptions: fiscal years,
                # then calendar years): its label cell names the block.
                section = label
            elif label and not block:
                label_header = label if not seen_data else label_header
            block.append(values)
            continue
        close_block()
        # Pending one-cell lines between data rows are section labels.
        if texts_after:
            section = texts_after[-1]
            texts_after = []
        seen_data = True
        named = {
            columns[i] if i < len(columns) else f"column {i + 1}": v
            for i, v in enumerate(values)
            if v is not None
        }
        rows.append(ParsedRow(label=label, section=section, values=named))
    # Every column name the rows use, in order of first use: a sheet with two
    # header blocks (fiscal years, then calendar years) has both sets.
    columns = list(dict.fromkeys(name for row in rows for name in row.values))
    return ParsedSheet(
        name=name,
        title=title_lines[0] if title_lines else None,
        title_lines=title_lines,
        label_header=label_header,
        columns=columns,
        rows=rows,
        notes=texts_after,
    )
