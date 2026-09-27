"""Scripts for the PHAC Health Infobase tools, which filter a downloaded file.

phac_infobase_query downloads one catalogue file (a CSV, a CSV inside a
ZIP, or a CNISP table as JSON from /api/cnisp-vri/table/<table>), reads
every cell as text and filters it itself, so no recorded request
reproduces its rows. These scripts download the same file, decode it
with the encoding the tool used, read it the way the tool does (trimmed
cells, blank rows and empty-header columns dropped) and repeat each step
in the tool's order: exact column values, the province, the date bounds,
the most recent rows, the chosen columns.

Everything comes from the catalogue entry, the file as the tool loaded
it and phac_infobase's own constants and patterns (PROVINCES, MARKERS,
the period regexes, the fold and place rules), so a catalogue change
reaches the scripts without an edit here. Stata runs the Python steps in
its built-in Python, as for every filtered file (render.py).
"""

from __future__ import annotations

import codecs
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import unquote, urlparse

from maplestats_mcp.modules.phac_infobase import client as phac
from maplestats_mcp.modules.phac_infobase import constants
from maplestats_mcp.modules.reproduce.spec import Code, Spec

_METHOD = "exact: the catalogue file, then the tool's filters"
_MIN_DATE = date(1, 1, 1)  # sort key for rows without a date (the tool uses date.min)
_ENCODING_LABELS = {
    "utf-8": "UTF-8",
    "utf-8-sig": "UTF-8 with a byte order mark",
    "cp1252": "Windows-1252",
    "cp850": "DOS code page 850",
}
_PLACE_STRIP = r"[.\s-]"  # phac._place: periods, spaces and hyphens do not count
# Numbers are converted after the tool's steps (the tool returns text).
# English files may group thousands with commas ("8,083"); the French files
# flagged decimal_comma write "12,2", with the odd "3.4" in the same column.
_NUMBER_EN = r"^[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?$"
_NUMBER_DECIMAL_COMMA = r"^[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?$"


@dataclass
class _Plan:
    """A phac_infobase call resolved against the file the tool loads."""

    tool: str
    dataset: Any  # catalogue.Dataset
    lang: str
    url: str
    member: str | None
    file_lang: str
    encoding: str  # as the tool decoded it: utf-8, utf-8-sig, cp1252, cp850 or json
    marker_counts: dict[str, int]
    decimal_comma: bool
    date_column: str | None
    geo_column: str | None
    last_modified: str | None
    arguments: dict[str, Any]
    filters: list[tuple[str, str]] = field(default_factory=list)  # (column, folded value)
    geography: str = ""
    pruid: str | None = None
    accepted_places: list[str] = field(default_factory=list)
    geo_needle: str = ""
    start: str = ""
    end: str = ""
    start_date: date | None = None
    end_date: date | None = None
    columns: list[str] | None = None
    limit: int | None = None  # None: the whole file (describe)
    counts: tuple[int, int, int] | None = None  # (returned, matching, total)

    @property
    def kind(self) -> str:
        return str(self.dataset.kind)

    @property
    def needs_fold(self) -> bool:
        return bool(self.filters or self.geography or self.kind == "zip")

    @property
    def needs_periods(self) -> bool:
        return self.date_column is not None


# Resolution ----------------------------------------------------------------------


def _file_name(plan_url: str, kind: str) -> str:
    name = unquote(urlparse(plan_url).path.rstrip("/").rsplit("/", 1)[-1]) or "download"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return f"{name}.json" if kind == "api" else name


async def _plan(tool: str, args: dict[str, Any], *, describe: bool) -> _Plan:
    lang = "fr" if str(args.get("lang", "en")) == "fr" else "en"
    dataset = phac._dataset(str(args["dataset_id"]))
    url, member, _, file_lang = phac._source(dataset, lang)
    table, _, _, _ = await phac.load(dataset, lang)
    keys = ("filters", "geography", "start", "end", "columns", "limit")
    shown = {"dataset_id": dataset.id}
    shown |= {k: args[k] for k in keys if not describe and args.get(k) not in (None, "", {}, [])}
    shown["lang"] = lang
    markers = phac._markers(table.rows, lang)
    plan = _Plan(
        tool=tool,
        dataset=dataset,
        lang=lang,
        url=url,
        member=member,
        file_lang=file_lang,
        encoding=table.encoding,
        marker_counts={m.value: m.count for m in markers},
        decimal_comma=phac._decimal_comma(table.rows, file_lang),
        date_column=phac._first_present(table.columns, dataset.date_columns),
        geo_column=phac._first_present(table.columns, dataset.geo_columns),
        last_modified=table.last_modified,
        arguments=shown,
    )
    if describe:
        return plan
    # Only a missing limit takes the default: 0 or a negative limit reaches the
    # tool below, which rejects it as the tool call would have.
    limit = constants.ROWS_DEFAULT if args.get("limit") is None else int(args["limit"])
    # The tool validates every argument; running it here raises the same
    # InvalidInput for a bad column, bound or limit, and gives the counts.
    result = await phac.query(
        dataset.id,
        filters=args.get("filters"),
        geography=args.get("geography"),
        start=args.get("start"),
        end=args.get("end"),
        columns=args.get("columns"),
        limit=limit,
        lang=lang,
    )
    plan.counts = (result.returned_count, result.matching_rows, result.total_rows)
    plan.limit = limit
    plan.filters = [
        (phac._resolve(table.columns, str(k)), phac._fold(str(v)))
        for k, v in (args.get("filters") or {}).items()
    ]
    geography = str(args.get("geography") or "").strip()
    if geography:
        plan.geography = geography
        plan.pruid = phac._province(geography)
        if plan.pruid is None:
            plan.geo_needle = phac._fold(geography)
        else:
            english, french, abbreviations = constants.PROVINCES[plan.pruid]
            accepted = {plan.pruid, phac._place(english), phac._place(french)}
            accepted |= {phac._place(a) for a in abbreviations}
            plan.accepted_places = sorted(accepted)
    plan.start = str(args.get("start") or "").strip()
    plan.end = str(args.get("end") or "").strip()
    plan.start_date = phac._bound(plan.start or None, "start", end=False)
    plan.end_date = phac._bound(plan.end or None, "end", end=True)
    if args.get("columns"):
        # A column named twice ("value", "VALUE") is kept once: the tool's rows hold
        # it once, and polars and DataFrames reject a repeated name in a selection.
        resolved = [phac._resolve(table.columns, str(c)) for c in args["columns"]]
        plan.columns = list(dict.fromkeys(resolved))
    return plan


def _iconv(encoding: str) -> str:
    """The iconv name R (readr) and Julia (StringEncodings) use for a Python codec."""
    name = codecs.lookup(encoding).name
    if name.startswith("utf-8"):
        return "UTF-8"
    if name.startswith("cp125"):
        return f"WINDOWS-{name[2:]}"
    if name.startswith("cp"):
        return f"CP{name[2:]}"
    if name.startswith("iso8859-"):
        return f"ISO-8859-{name[8:]}"
    return name.upper()


def _markers_comment(plan: _Plan, prefix: str) -> str:
    index = 1 if plan.lang == "fr" else 0
    width = max(len(value) for value in constants.MARKERS)
    lines = [
        f"{prefix} Suppression and missing-value markers are left as published, as the tool",
        f"{prefix} leaves them. The markers PHAC files use, and the cells in this file:",
    ]
    for value, meanings in constants.MARKERS.items():
        count = plan.marker_counts.get(value, 0)
        cells = f"{count:,} cell{'' if count == 1 else 's'}" if count else "none"
        lines.append(f"{prefix}   {value.ljust(width)}  {meanings[index]} ({cells})")
    return "\n".join(lines) + "\n"


def _number_pattern(plan: _Plan) -> str:
    return _NUMBER_DECIMAL_COMMA if plan.decimal_comma else _NUMBER_EN


def _numbers_comment(plan: _Plan, prefix: str) -> str:
    separator = (
        "This file writes decimal commas (12,2)."
        if plan.decimal_comma
        else "Commas group thousands (8,083)."
    )
    return (
        f"{prefix} Numbers stay text through the tool's steps; now each column whose\n"
        f"{prefix} non-empty cells are all numbers becomes numeric, and a column holding\n"
        f"{prefix} a marker stays text. {separator}\n"
    )


def _steps_comment(plan: _Plan, prefix: str) -> str:
    """What the tool did, in its order, as a comment above the steps."""
    lines = [f"Keep the rows {plan.tool} kept, in the tool's order:"]
    for column, value in plan.filters:
        lines.append(f"- {column} equals {value!r} (compared as fold() does);")
    if plan.geography and plan.pruid:
        lines.append(
            f"- {plan.geo_column} is {plan.geography!r}: PRUID {plan.pruid} or its English, "
            "French or abbreviated name (compared as place() does);"
        )
    elif plan.geography:
        lines.append(f"- {plan.geo_column} contains {plan.geography!r} (compared as fold() does);")
    if plan.start_date or plan.end_date:
        bounds = []
        if plan.start_date:
            bounds.append(f"from {plan.start_date} (start {plan.start!r})")
        if plan.end_date:
            bounds.append(f"to {plan.end_date} (end {plan.end!r})")
        lines.append(f"- {plan.date_column}, read by parse_period(), {' '.join(bounds)};")
    if plan.date_column:
        lines.append(
            f"- sorted by {plan.date_column} (rows without a date first, ties in file "
            f"order), then the last {plan.limit} rows, oldest first;"
        )
    else:
        lines.append(f"- the first {plan.limit} rows (no date column);")
    if plan.columns:
        lines.append(f"- the columns {', '.join(plan.columns)}.")
    return "".join(f"{prefix} {line}\n" for line in lines)


# Python (also Stata's built-in Python) ----------------------------------------------------


def _py_helpers(fold: bool, periods: bool) -> str:
    blocks: list[str] = []
    if fold:
        blocks.append(
            "# fold() and place() repeat phac_infobase's matching rules: lower case, no\n"
            "# accents, typographic apostrophes as ', runs of spaces as one; place names\n"
            '# also ignore periods, hyphens and spaces ("Terre-Neuve et Labrador").\n\n\n'
            "def fold(text):\n"
            '    text = text.replace("\\u2019", "\'").replace("\\u2018", "\'")\n'
            '    decomposed = unicodedata.normalize("NFKD", text)\n'
            '    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))\n'
            '    return " ".join(stripped.lower().split())\n\n\n'
            "def place(text):\n"
            f'    return re.sub(r"{_PLACE_STRIP}", "", fold(text))\n'
        )
    if periods:

        def compiled(pattern: re.Pattern[str]) -> str:
            flags = ", re.IGNORECASE" if pattern.flags & re.IGNORECASE else ""
            return f"re.compile({pattern.pattern!r}{flags})"

        blocks.append(
            "# parse_period() gives the start date of a period cell, as the tool reads\n"
            "# it: 2025-08-30, 2025 Q3 (French files: 2025 T3), 2024-10, 30-08-2025, or a\n"
            '# leading year ("2026 (Jan to Mar)", "2015-2018"); None when there is no year.\n\n'
            f"QUARTER = {compiled(phac._QUARTER)}\n"
            f"YEAR_MONTH = {compiled(phac._YEAR_MONTH)}\n"
            f"DAY_FIRST = {compiled(phac._DAY_FIRST)}\n"
            f"YEAR = {compiled(phac._YEAR)}\n\n\n"
            "def parse_period(value):\n"
            "    text = value.strip()\n"
            "    if not text:\n"
            "        return None\n"
            "    try:\n"
            "        return date.fromisoformat(text[:10])\n"
            "    except ValueError:\n"
            "        pass\n"
            "    if match := QUARTER.match(text):\n"
            "        year = int(match.group(1))\n"
            "        return date(year, 3 * int(match.group(2)) - 2, 1) if 1800 <= year <= 2100 else None\n"
            "    # 2024-25 is a fiscal or school year: only months 1 to 12 count.\n"
            "    if (match := YEAR_MONTH.match(text)) and 1 <= int(match.group(2)) <= 12:\n"
            "        year = int(match.group(1))\n"
            "        return date(year, int(match.group(2)), 1) if 1800 <= year <= 2100 else None\n"
            "    if match := DAY_FIRST.match(text):\n"
            "        try:\n"
            "            return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))\n"
            "        except ValueError:\n"
            "            return None\n"
            "    if match := YEAR.match(text):\n"
            "        year = int(match.group(1))\n"
            "        return date(year, 1, 1) if 1800 <= year <= 2100 else None\n"
            "    return None\n"
        )
    return "\n\n".join(blocks)


def _py_read(plan: _Plan) -> Code:
    imports = ["from pathlib import Path", "import httpx", "import polars as pl"]
    if plan.needs_fold:
        imports += ["import re", "import unicodedata"]
    if plan.needs_periods:
        imports += ["import re", "from datetime import date"]
    fetch = (
        f"URL = {plan.url!r}\n"
        "with httpx.Client(http2=True, follow_redirects=True, timeout=300) as client:\n"
        "    response = client.get(URL)\n"
        "response.raise_for_status()\n\n"
        f"# A missing file redirects to {constants.NOT_FOUND_PAGE}, which answers HTTP 200.\n\n"
        f"if response.url.path == {constants.NOT_FOUND_PAGE!r}:\n"
        '    raise SystemExit(f"{URL} has moved or been removed; see phac_infobase_list_datasets.")\n'
        "raw_path.write_bytes(response.content)\n"
    )
    if plan.kind == "api":
        imports.append("import json")
        read = (
            "# A whole CNISP table as a JSON array of records; JSON null is an empty\n"
            "# cell and every value is text, as the tool reads it.\n\n"
            'records = json.loads(raw_path.read_text(encoding="utf-8"))\n'
            "names = list(dict.fromkeys(key for record in records for key in record))\n"
            "data = pl.DataFrame(\n"
            '    [["" if record.get(name) is None else str(record.get(name)).strip() for name in names] for record in records],\n'
            "    schema={name: pl.Utf8 for name in names},\n"
            '    orient="row",\n'
            ")\n"
        )
        return Code(
            imports,
            "\n".join(
                b for b in (_py_helpers(plan.needs_fold, plan.needs_periods), fetch, read) if b
            ),
        )
    imports += ["import csv", "import io"]
    label = _ENCODING_LABELS.get(plan.encoding, plan.encoding)
    decode = (
        f"# The tool decoded this file as {label}: it tries UTF-8 (with or without a\n"
        "# byte order mark), falls back to Windows-1252, and the catalogue names the\n"
        "# odd one out (DOS code page 850).\n\n"
    )
    if plan.kind == "zip":
        imports.append("import zipfile")
        pick = (
            "    members = [name for name in archive.namelist() if name.lower().endswith('.csv')]\n"
            + (
                f"    member = next(name for name in members if fold({plan.member!r}) in fold(name))\n"
                if plan.member
                else "    member = members[0]\n"
            )
        )
        decode += (
            "# The data file inside the ZIP: the first CSV whose name holds the catalogue's\n"
            "# member name, ignoring case and accents (DonnéesMéfaitsSubstances.csv).\n\n"
            "with zipfile.ZipFile(raw_path) as archive:\n"
            f"{pick}"
            f"    text = archive.read(member).decode({plan.encoding!r})\n"
        )
    else:
        decode += f"text = raw_path.read_bytes().decode({plan.encoding!r})\n"
    parse = (
        "# Every cell as text, as the tool reads it: names and cells trimmed, blank rows\n"
        "# skipped, columns with an empty header (R row numbers, trailing blank columns)\n"
        "# dropped, and a repeated name numbered name_2.\n\n"
        "grid = list(csv.reader(io.StringIO(text)))\n"
        "header = [name.strip() for name in grid[0]]\n"
        "keep = [i for i, name in enumerate(header) if name]\n"
        "seen = {}\n"
        "names = []\n"
        "for i in keep:\n"
        "    seen[header[i]] = seen.get(header[i], 0) + 1\n"
        '    names.append(header[i] if seen[header[i]] == 1 else f"{header[i]}_{seen[header[i]]}")\n'
        "cells = [\n"
        '    [row[i].strip() if i < len(row) else "" for i in keep]\n'
        "    for row in grid[1:]\n"
        "    if any(cell.strip() for cell in row)\n"
        "]\n"
        'data = pl.DataFrame(cells, schema={name: pl.Utf8 for name in names}, orient="row")\n'
    )
    body = "\n".join(
        b for b in (_py_helpers(plan.needs_fold, plan.needs_periods), fetch, decode, parse) if b
    )
    return Code(imports, body)


def _py_numbers(plan: _Plan) -> str:
    convert = "str.replace_all(',', '.')" if plan.decimal_comma else "str.replace_all(',', '')"
    return (
        _numbers_comment(plan, "#") + "\n" + f"NUMBER = {_number_pattern(plan)!r}\n"
        "for name in data.columns:\n"
        "    column = data.get_column(name)\n"
        '    cells = column.filter(column != "")\n'
        "    if cells.len() > 0 and cells.str.contains(NUMBER).all():\n"
        f'        numbers = column.replace("", None).{convert}.cast(pl.Float64)\n'
        "        if (numbers.drop_nulls() % 1 == 0).all():\n"
        "            numbers = numbers.cast(pl.Int64)\n"
        "        data = data.with_columns(numbers.alias(name))\n"
    )


def _py_steps(plan: _Plan) -> str:
    fold_col = "pl.col({!r}).map_elements(fold, return_dtype=pl.Utf8)"
    conditions = [f"{fold_col.format(c)} == {v!r}" for c, v in plan.filters]
    if plan.geography and plan.pruid:
        conditions.append(
            f"pl.col({plan.geo_column!r}).map_elements(place, return_dtype=pl.Utf8)"
            f".is_in({plan.accepted_places!r})"
        )
    elif plan.geography:
        conditions.append(
            f"{fold_col.format(plan.geo_column)}.str.contains({plan.geo_needle!r}, literal=True)"
        )
    out = _steps_comment(plan, "#") + "\n"
    if conditions:
        out += "data = data.filter(\n" + "".join(f"    {c},\n" for c in conditions) + ")\n"
    if plan.date_column:
        out += (
            "data = data.with_columns(\n"
            f"    pl.col({plan.date_column!r}).map_elements(parse_period, return_dtype=pl.Date)"
            '.alias("_period")\n'
            ")\n"
        )
        if plan.start_date or plan.end_date:
            bounds = []
            if plan.start_date:
                d = plan.start_date
                bounds.append(f'pl.col("_period") >= date({d.year}, {d.month}, {d.day})')
            if plan.end_date:
                d = plan.end_date
                bounds.append(f'pl.col("_period") <= date({d.year}, {d.month}, {d.day})')
            out += "data = data.filter(" + ", ".join(bounds) + ")\n"
        out += (
            'data = data.sort(pl.col("_period").fill_null(date.min), maintain_order=True)'
            f".tail({plan.limit})\n"
            'data = data.drop("_period")\n'
        )
    else:
        out += f"data = data.head({plan.limit})\n"
    if plan.columns:
        out += f"data = data.select({plan.columns!r})\n"
    return out


def _py_summary(plan: _Plan) -> str:
    out = (
        f"# {plan.tool} summarizes the whole file: rows, date coverage and places.\n\n"
        'print(f"{data.height} rows, {data.width} columns")\n'
    )
    if plan.date_column:
        out += (
            f"periods = data.get_column({plan.date_column!r})"
            ".map_elements(parse_period, return_dtype=pl.Date)\n"
            f"print({plan.date_column + ':'!r}, periods.min(), 'to', periods.max())\n"
        )
    if plan.geo_column:
        out += (
            f"places = data.get_column({plan.geo_column!r}).unique(maintain_order=True)\n"
            f"print({plan.geo_column + ':'!r}, [p for p in places.to_list() if p])\n"
        )
    return out


def _python(plan: _Plan, describe: bool) -> tuple[Code, Code]:
    read = _py_read(plan)
    steps = _py_summary(plan) if describe else _py_steps(plan)
    prepare = "\n".join([steps, _markers_comment(plan, "#"), _py_numbers(plan)])
    return read, Code([], prepare)


# R ------------------------------------------------------------------------------------------


def _r_str(value: str) -> str:
    """An ASCII R string literal. R parses a script in the session's locale, so
    a literal "Unité" misses the UTF-8 column name under LANG=C (checked with
    R 4.3); \\u escapes always give UTF-8."""
    out = []
    for ch in json.dumps(value, ensure_ascii=False):
        code = ord(ch)
        out.append(ch if code < 128 else f"\\U{{{code:x}}}" if code > 0xFFFF else f"\\u{code:04x}")
    return "".join(out)


def _r_vector(values: list[str]) -> str:
    return "c(" + ", ".join(_r_str(v) for v in values) + ")"


def _r_helpers(plan: _Plan) -> str:
    blocks: list[str] = []
    if plan.needs_fold:
        blocks.append(
            "# fold() and place() repeat phac_infobase's matching rules: lower case, no\n"
            "# accents, typographic apostrophes as ', runs of spaces as one; place names\n"
            '# also ignore periods, hyphens and spaces ("Terre-Neuve et Labrador").\n\n'
            "fold <- function(x) {\n"
            "  x |>\n"
            '    str_replace_all("[\\u2018\\u2019]", "\'") |>\n'
            "    stri_trans_nfkd() |>\n"
            '    str_remove_all("\\\\p{Mn}") |>\n'
            "    str_to_lower() |>\n"
            "    str_squish()\n"
            "}\n\n"
            f"place <- function(x) str_remove_all(fold(x), {_r_str(_PLACE_STRIP)})\n"
        )
    if plan.needs_periods:

        def pattern(p: re.Pattern[str]) -> str:
            if p.flags & re.IGNORECASE:
                return f"regex({_r_str(p.pattern)}, ignore_case = TRUE)"
            return _r_str(p.pattern)

        blocks.append(
            "# parse_period() gives the start date of a period cell, as the tool reads\n"
            "# it: 2025-08-30, 2025 Q3 (French files: 2025 T3), 2024-10, 30-08-2025, or a\n"
            '# leading year ("2026 (Jan to Mar)", "2015-2018"); NA when there is no year.\n\n'
            "parse_period <- function(value) {\n"
            "  text <- str_trim(value)\n"
            "  head <- str_sub(text, 1, 10)\n"
            '  as_date <- \\(y, m, d) as.Date(sprintf("%s-%s-%s", y, m, d), format = "%Y-%m-%d")\n'
            "  valid <- \\(year) !is.na(year) & year >= 1800 & year <= 2100\n"
            '  iso <- if_else(str_detect(head, "^\\\\d{4}-\\\\d{2}-\\\\d{2}$"), head, NA_character_)\n'
            f"  quarter <- str_match(text, {pattern(phac._QUARTER)})\n"
            f"  year_month <- str_match(text, {pattern(phac._YEAR_MONTH)})\n"
            f"  day_first <- str_match(text, {pattern(phac._DAY_FIRST)})\n"
            f"  year <- as.integer(str_match(text, {pattern(phac._YEAR)})[, 2])\n"
            "  q_year <- as.integer(quarter[, 2])\n"
            "  ym_year <- as.integer(year_month[, 2])\n"
            "  month <- as.integer(year_month[, 3])\n"
            "  coalesce(\n"
            '    as.Date(iso, format = "%Y-%m-%d"),\n'
            "    if_else(valid(q_year), as_date(q_year, 3L * as.integer(quarter[, 3]) - 2L, 1L), NA),\n"
            "    # 2024-25 is a fiscal or school year: only months 1 to 12 count.\n"
            "    if_else(valid(ym_year) & month >= 1 & month <= 12, as_date(ym_year, month, 1L), NA),\n"
            "    as_date(day_first[, 4], day_first[, 3], day_first[, 2]),\n"
            "    if_else(valid(year), as_date(year, 1L, 1L), NA)\n"
            "  )\n"
            "}\n"
        )
    return "\n".join(blocks)


def _r_read(plan: _Plan, file_name: str) -> Code:
    path = f"data/raw/{file_name}"
    packages = ["dplyr", "httr2", "readr", "stringr"]
    if plan.needs_fold:
        packages.append("stringi")
    fetch = (
        f"url <- {_r_str(plan.url)}\n"
        f"response <- request(url) |>\n  req_perform(path = {_r_str(path)})\n\n"
        f"# A missing file redirects to {constants.NOT_FOUND_PAGE}, which answers HTTP 200.\n\n"
        'stopifnot("The file has moved or been removed" = '
        f"!str_ends(resp_url(response), {_r_str(constants.NOT_FOUND_PAGE)}))\n"
    )
    if plan.kind == "api":
        packages += ["jsonlite", "purrr", "tibble"]
        read = (
            "# A whole CNISP table as a JSON array of records; JSON null is an empty\n"
            "# cell and every value is text, as the tool reads it.\n\n"
            f"records <- fromJSON({_r_str(path)}, simplifyVector = FALSE)\n"
            "columns <- unique(unlist(map(records, names)))\n"
            "data <- columns |>\n"
            '  map(\\(column) map_chr(records, \\(record) str_trim(as.character(record[[column]] %||% "")))) |>\n'
            "  setNames(columns) |>\n"
            "  as_tibble()\n"
        )
        return Code(packages, "\n".join(b for b in (_r_helpers(plan), fetch, read) if b))
    label = _ENCODING_LABELS.get(plan.encoding, plan.encoding)
    source = _r_str(path)
    unzip = ""
    if plan.kind == "zip":
        pick = (
            f"csv_members[str_detect(fold(csv_members), fixed({_r_str(_fold(plan.member))}))][1]"
            if plan.member
            else "csv_members[1]"
        )
        # Read through unz(): zip::unzip cannot find the French member by name
        # outside a UTF-8 locale, and the file it writes is then unreadable by
        # name in a UTF-8 one (both checked with R 4.3); utils::unzip's listing
        # and unz() pass the name through as bytes in either locale.
        unzip = (
            "# The data file inside the ZIP. The French opioid ZIP stores its member name\n"
            "# (DonnéesMéfaitsSubstances.csv) in code page 437 without the UTF-8 flag, so\n"
            "# the accents may not survive here: when the ZIP holds one CSV, that is the\n"
            "# file; otherwise match the catalogue's member name, ignoring case and accents.\n\n"
            f"members <- utils::unzip({source}, list = TRUE)$Name\n"
            'csv_members <- members[grepl("[.]csv$", members, ignore.case = TRUE, useBytes = TRUE)]\n'
            f"member <- if (length(csv_members) == 1) csv_members else {pick}\n"
        )
        source = f"unz({source}, member)"
    read = (
        f"# Every cell as text. The tool decoded this file as {label}: it tries UTF-8\n"
        "# (with or without a byte order mark), falls back to Windows-1252, and the\n"
        "# catalogue names the odd one out (DOS code page 850).\n\n"
        "grid <- read_csv(\n"
        f"  {source},\n"
        "  col_names = FALSE,\n"
        "  col_types = cols(.default = col_character()),\n"
        "  na = character(),\n"
        "  trim_ws = FALSE,\n"
        f"  locale = locale(encoding = {_r_str(_iconv(plan.encoding))})\n"
        ")\n\n"
        "# As the tool reads it: names and cells trimmed, blank rows skipped, columns\n"
        "# with an empty header (R row numbers, trailing blank columns) dropped, and a\n"
        "# repeated name numbered name_2.\n\n"
        'header <- coalesce(str_trim(unlist(grid[1, ], use.names = FALSE)), "")\n'
        "cells <- grid[-1, ] |>\n"
        '  mutate(across(everything(), \\(x) coalesce(str_trim(x), "")))\n'
        'cells <- cells[rowSums(cells != "") > 0, header != ""]\n'
        'kept <- header[header != ""]\n'
        "occurrence <- ave(seq_along(kept), kept, FUN = seq_along)\n"
        'data <- setNames(cells, if_else(occurrence == 1, kept, str_c(kept, "_", occurrence)))\n'
    )
    return Code(packages, "\n".join(b for b in (_r_helpers(plan), fetch, unzip, read) if b))


def _fold(text: str | None) -> str:
    return phac._fold(text or "")


def _r_col(name: str) -> str:
    return f".data[[{_r_str(name)}]]"


def _r_steps(plan: _Plan) -> str:
    conditions = [f"fold({_r_col(c)}) == {_r_str(v)}" for c, v in plan.filters]
    if plan.geography and plan.pruid:
        conditions.append(
            f"place({_r_col(str(plan.geo_column))}) %in% {_r_vector(plan.accepted_places)}"
        )
    elif plan.geography:
        conditions.append(
            f"str_detect(fold({_r_col(str(plan.geo_column))}), fixed({_r_str(plan.geo_needle)}))"
        )
    steps: list[str] = []
    if conditions:
        steps.append("filter(\n    " + ",\n    ".join(conditions) + "\n  )")
    if plan.date_column:
        steps.append(f"mutate(.period = parse_period({_r_col(plan.date_column)}))")
        bounds = []
        if plan.start_date:
            bounds.append(f'.period >= as.Date("{plan.start_date}")')
        if plan.end_date:
            bounds.append(f'.period <= as.Date("{plan.end_date}")')
        if bounds:
            steps.append(f"filter({', '.join(bounds)})")
        steps.append(f'arrange(coalesce(.period, as.Date("{_MIN_DATE}")))')
        steps.append(f"slice_tail(n = {plan.limit})")
        steps.append("select(-.period)")
    else:
        steps.append(f"slice_head(n = {plan.limit})")
    if plan.columns:
        steps.append(f"select(all_of({_r_vector(plan.columns)}))")
    return _steps_comment(plan, "#") + "\ndata <- data |>\n  " + " |>\n  ".join(steps) + "\n"


def _r_summary(plan: _Plan) -> str:
    out = (
        f"# {plan.tool} summarizes the whole file: rows, date coverage and places.\n\n"
        'message(nrow(data), " rows, ", ncol(data), " columns")\n'
    )
    if plan.date_column:
        out += (
            f"periods <- parse_period(data[[{_r_str(plan.date_column)}]])\n"
            f'message({_r_str(plan.date_column + ": ")}, min(periods, na.rm = TRUE), " to ", '
            "max(periods, na.rm = TRUE))\n"
        )
    if plan.geo_column:
        out += (
            f"places <- unique(data[[{_r_str(plan.geo_column)}]])\n"
            f'message({_r_str(plan.geo_column + ": ")}, str_c(places[places != ""], collapse = ", "))\n'
        )
    return out


def _r_numbers(plan: _Plan) -> str:
    convert = (
        'str_replace(na_if(x, ""), ",", ".")'
        if plan.decimal_comma
        else 'str_remove_all(na_if(x, ""), ",")'
    )
    return (
        _numbers_comment(plan, "#") + "\n" + f"number <- {_r_str(_number_pattern(plan))}\n"
        'is_number <- \\(x) any(x != "") && all(str_detect(x[x != ""], number))\n'
        "data <- data |>\n"
        f"  mutate(across(where(is_number), \\(x) as.numeric({convert})))\n"
    )


def _r(plan: _Plan, file_name: str, describe: bool) -> tuple[Code, Code]:
    read = _r_read(plan, file_name)
    steps = _r_summary(plan) if describe else _r_steps(plan)
    body = "\n".join([steps, _markers_comment(plan, "#"), _r_numbers(plan)])
    return read, Code(["dplyr", "stringr"], body)


# Julia ------------------------------------------------------------------------------------


def _jl_str(value: str) -> str:
    """A Julia string literal: JSON escapes are valid Julia; $ must not interpolate."""
    return json.dumps(value, ensure_ascii=False).replace("$", "\\$")


def _jl_vector(values: list[str]) -> str:
    return "[" + ", ".join(_jl_str(v) for v in values) + "]"


def _jl_helpers(plan: _Plan) -> str:
    blocks: list[str] = []
    if plan.needs_fold:
        blocks.append(
            "# fold() and place() repeat phac_infobase's matching rules: lower case, no\n"
            "# accents, typographic apostrophes as ', runs of spaces as one; place names\n"
            '# also ignore periods, hyphens and spaces ("Terre-Neuve et Labrador").\n\n'
            "fold(text) = join(\n"
            "    split(lowercase(Unicode.normalize(\n"
            "        replace(text, '\\u2019' => '\\'', '\\u2018' => '\\'');\n"
            "        compat = true,\n"
            "        stripmark = true,\n"
            "    ))),\n"
            '    " ",\n'
            ")\n"
            f'place(text) = replace(fold(text), r"{_PLACE_STRIP}" => "")\n'
        )
    if plan.needs_periods:

        def pattern(p: re.Pattern[str]) -> str:
            flags = ', "i"' if p.flags & re.IGNORECASE else ""
            return f'Regex(raw"{p.pattern}"{flags})'

        blocks.append(
            "# parse_period() gives the start date of a period cell, as the tool reads\n"
            "# it: 2025-08-30, 2025 Q3 (French files: 2025 T3), 2024-10, 30-08-2025, or a\n"
            '# leading year ("2026 (Jan to Mar)", "2015-2018"); missing when there is no year.\n\n'
            f"const QUARTER = {pattern(phac._QUARTER)}\n"
            f"const YEAR_MONTH = {pattern(phac._YEAR_MONTH)}\n"
            f"const DAY_FIRST = {pattern(phac._DAY_FIRST)}\n"
            f"const YEAR = {pattern(phac._YEAR)}\n"
            "valid_year(year) = 1800 <= year <= 2100\n\n"
            "function parse_period(value)\n"
            "    text = strip(value)\n"
            "    isempty(text) && return missing\n"
            "    head = first(text, 10)\n"
            '    if occursin(r"^\\d{4}-\\d{2}-\\d{2}$", head)\n'
            '        parsed = tryparse(Date, head, dateformat"yyyy-mm-dd")\n'
            "        parsed === nothing || return parsed\n"
            "    end\n"
            "    m = match(QUARTER, text)\n"
            "    if m !== nothing\n"
            "        year = parse(Int, m[1])\n"
            "        return valid_year(year) ? Date(year, 3 * parse(Int, m[2]) - 2, 1) : missing\n"
            "    end\n"
            "    # 2024-25 is a fiscal or school year: only months 1 to 12 count.\n"
            "    m = match(YEAR_MONTH, text)\n"
            "    if m !== nothing && 1 <= parse(Int, m[2]) <= 12\n"
            "        year = parse(Int, m[1])\n"
            "        return valid_year(year) ? Date(year, parse(Int, m[2]), 1) : missing\n"
            "    end\n"
            "    m = match(DAY_FIRST, text)\n"
            "    if m !== nothing\n"
            "        parts = parse.(Int, (m[3], m[2], m[1]))\n"
            "        return Dates.validargs(Date, parts...) === nothing ? Date(parts...) : missing\n"
            "    end\n"
            "    m = match(YEAR, text)\n"
            "    if m !== nothing\n"
            "        year = parse(Int, m[1])\n"
            "        return valid_year(year) ? Date(year, 1, 1) : missing\n"
            "    end\n"
            "    return missing\n"
            "end\n"
        )
    return "\n".join(blocks)


def _jl_read(plan: _Plan, file_name: str) -> Code:
    path = f"data/raw/{file_name}"
    packages = ["DataFrames", "Downloads"]
    if plan.needs_fold:
        packages.append("Unicode")
    if plan.needs_periods:
        packages.append("Dates")
    fetch = (
        f"url = {_jl_str(plan.url)}\n"
        f"response = Downloads.request(url; output = {_jl_str(path)})\n"
        'response.status == 200 || error("$(url) answered HTTP $(response.status)")\n\n'
        f"# A missing file redirects to {constants.NOT_FOUND_PAGE}, which answers HTTP 200.\n\n"
        f'endswith(response.url, {_jl_str(constants.NOT_FOUND_PAGE)}) && error("$(url) has moved or been removed")\n'
    )
    if plan.kind == "api":
        packages.append("JSON3")
        read = (
            "# A whole CNISP table as a JSON array of records; JSON null is an empty\n"
            "# cell and every value is text, as the tool reads it.\n\n"
            f"records = JSON3.read(read({_jl_str(path)}, String))\n"
            "columns = unique(String(key) for record in records for key in keys(record))\n"
            "cell(record, column) = (value = get(record, Symbol(column), nothing);\n"
            '    value === nothing ? "" : String(strip(string(value))))\n'
            "data = DataFrame([column => [cell(record, column) for record in records] for column in columns])\n"
        )
        return Code(packages, "\n".join(b for b in (_jl_helpers(plan), fetch, read) if b))
    packages.append("CSV")
    utf8 = _iconv(plan.encoding) == "UTF-8"
    if not utf8 and plan.kind != "zip":
        packages.append("StringEncodings")
    label = _ENCODING_LABELS.get(plan.encoding, plan.encoding)
    if plan.kind == "zip":
        # ZipArchives, not ZipFile: ZipFile.jl rejects the French archive outright
        # because a member name is not valid UTF-8 (checked with Julia 1.11).
        # Names are decoded as Python's zipfile decodes them (UTF-8 when the entry
        # sets flag 0x0800, code page 437 otherwise) and then matched as the tool
        # matches them: comparing only their ASCII letters missed the accented
        # French member whenever the ZIP held a second CSV.
        packages += ["ZipArchives", "StringEncodings"]
        pick = (
            f"first(i for i in csv_members if occursin({_jl_str(_fold(plan.member))}, fold(member_names[i])))"
            if plan.member
            else "first(csv_members)"
        )
        bytes_code = (
            "# The data file inside the ZIP: the first CSV whose name holds the catalogue's\n"
            "# member name, ignoring case and accents. Names are read as the tool reads\n"
            "# them: UTF-8 when the entry says so, otherwise code page 437 (the French\n"
            "# opioid ZIP stores DonnéesMéfaitsSubstances.csv that way).\n\n"
            f"archive = ZipReader(read({_jl_str(path)}))\n"
            "member_names = [\n"
            "    zip_general_purpose_bit_flag(archive, i) & 0x0800 != 0 ? zip_name(archive, i) :\n"
            '    decode(Vector{UInt8}(codeunits(zip_name(archive, i))), "CP437")\n'
            "    for i in 1:zip_nentries(archive)\n"
            "]\n"
            'csv_members = findall(name -> endswith(lowercase(name), ".csv"), member_names)\n'
            f"member = {pick}\n"
            "bytes = zip_readentry(archive, member)\n"
        )
    else:
        bytes_code = f"bytes = read({_jl_str(path)})\n"
    decode = (
        f'text = decode(bytes, "{_iconv(plan.encoding)}")\n'
        if not utf8
        else 'text = chopprefix(String(bytes), "\\ufeff")\n'
    )
    read = (
        f"{bytes_code}\n"
        f"# The tool decoded this file as {label}: it tries UTF-8 (with or without a\n"
        "# byte order mark), falls back to Windows-1252, and the catalogue names the\n"
        "# odd one out (DOS code page 850).\n\n"
        f"{decode}\n"
        "# Every cell as text, as the tool reads it: names and cells trimmed, blank rows\n"
        "# skipped, columns with an empty header (R row numbers, trailing blank columns)\n"
        "# dropped, and a repeated name numbered name_2.\n\n"
        "grid = CSV.File(IOBuffer(text); header = false, types = String, silencewarnings = true)\n"
        'cells = String.(strip.(coalesce.(Matrix(DataFrame(grid)), "")))\n'
        "header = cells[1, :]\n"
        "body = cells[2:end, :]\n"
        "body = body[vec(any(!isempty, body; dims = 2)), :]\n"
        "keep = findall(!isempty, header)\n"
        "seen = Dict{String, Int}()\n"
        "kept = String[]\n"
        "for name in header[keep]\n"
        "    seen[name] = get(seen, name, 0) + 1\n"
        '    push!(kept, seen[name] == 1 ? name : "$(name)_$(seen[name])")\n'
        "end\n"
        "data = DataFrame(body[:, keep], kept)\n"
    )
    return Code(packages, "\n".join(b for b in (_jl_helpers(plan), fetch, read) if b))


def _jl_steps(plan: _Plan) -> str:
    conditions = [f"fold(row[{_jl_str(c)}]) == {_jl_str(v)}" for c, v in plan.filters]
    if plan.geography and plan.pruid:
        conditions.append(
            f"place(row[{_jl_str(str(plan.geo_column))}]) in {_jl_vector(plan.accepted_places)}"
        )
    elif plan.geography:
        conditions.append(
            f"occursin({_jl_str(plan.geo_needle)}, fold(row[{_jl_str(str(plan.geo_column))}]))"
        )
    out = _steps_comment(plan, "#") + "\n"
    if conditions:
        out += "data = filter(row -> " + " &&\n    ".join(conditions) + ", data)\n"
    if plan.date_column:
        out += f'data[!, "_period"] = parse_period.(data[!, {_jl_str(plan.date_column)}])\n'
        bounds = ['!ismissing(row["_period"])']
        if plan.start_date:
            d = plan.start_date
            bounds.append(f'row["_period"] >= Date({d.year}, {d.month}, {d.day})')
        if plan.end_date:
            d = plan.end_date
            bounds.append(f'row["_period"] <= Date({d.year}, {d.month}, {d.day})')
        if len(bounds) > 1:
            out += f"data = filter(row -> {' && '.join(bounds)}, data)\n"
        out += (
            'data = sort(data, "_period"; by = period -> coalesce(period, Date(1)), alg = MergeSort)\n'
            f"data = last(data, {plan.limit})\n"
            'select!(data, Not("_period"))\n'
        )
    else:
        out += f"data = first(data, {plan.limit})\n"
    if plan.columns:
        out += f"select!(data, {_jl_vector(plan.columns)})\n"
    return out


def _jl_summary(plan: _Plan) -> str:
    out = (
        f"# {plan.tool} summarizes the whole file: rows, date coverage and places.\n\n"
        'println("$(nrow(data)) rows, $(ncol(data)) columns")\n'
    )
    if plan.date_column:
        out += (
            f"periods = collect(skipmissing(parse_period.(data[!, {_jl_str(plan.date_column)}])))\n"
            f'println({_jl_str(plan.date_column + ": ")}, minimum(periods), " to ", maximum(periods))\n'
        )
    if plan.geo_column:
        out += (
            f"places = filter(!isempty, unique(data[!, {_jl_str(plan.geo_column)}]))\n"
            f'println({_jl_str(plan.geo_column + ": ")}, join(places, ", "))\n'
        )
    return out


def _jl_numbers(plan: _Plan) -> str:
    replacement = '"," => "."' if plan.decimal_comma else '"," => ""'
    return (
        _numbers_comment(plan, "#") + "\n" + f'number = Regex(raw"{_number_pattern(plan)}")\n'
        "for name in names(data)\n"
        "    column = data[!, name]\n"
        "    nonempty = filter(!isempty, column)\n"
        "    (isempty(nonempty) || !all(c -> occursin(number, c), nonempty)) && continue\n"
        f"    converted = [isempty(c) ? missing : parse(Float64, replace(c, {replacement})) for c in column]\n"
        "    if all(v -> ismissing(v) || isinteger(v), converted)\n"
        "        converted = [ismissing(v) ? missing : Int(v) for v in converted]\n"
        "    end\n"
        "    data[!, name] = converted\n"
        "end\n"
    )


def _julia(plan: _Plan, file_name: str, describe: bool) -> tuple[Code, Code]:
    read = _jl_read(plan, file_name)
    steps = _jl_summary(plan) if describe else _jl_steps(plan)
    body = "\n".join([steps, _markers_comment(plan, "#"), _jl_numbers(plan)])
    return read, Code([], body)


# Spec -------------------------------------------------------------------------------------


def _spec(plan: _Plan, describe: bool) -> Spec:
    title = plan.dataset.title_fr if plan.lang == "fr" else plan.dataset.title_en
    file_name = _file_name(plan.url, plan.kind)
    py_read, py_prepare = _python(plan, describe)
    r_read, r_prepare = _r(plan, file_name, describe)
    jl_read, jl_prepare = _julia(plan, file_name, describe)
    label = _ENCODING_LABELS.get(plan.encoding, "JSON" if plan.kind == "api" else plan.encoding)
    file_line = f"File:    {plan.file_lang.upper()} file, {label}"
    if plan.kind == "zip" and plan.member:
        file_line += f", ZIP member matching {plan.member}"
    if plan.decimal_comma:
        file_line += ", decimal commas"
    if plan.last_modified:
        file_line += f"; last modified {plan.last_modified}"
    details = [
        f"Dataset: {plan.dataset.id} (PHAC Health Infobase catalogue)",
        f"Query:   {plan.tool}({json.dumps(plan.arguments, ensure_ascii=False)})",
        file_line,
    ]
    notes: list[str] = []
    if plan.counts:
        returned, matching, total = plan.counts
        notes.append(
            f"The tool returned {returned} of {matching} matching rows ({total} in the file); "
            "the scripts repeat its filters, province match, date bounds, ordering and limit, "
            "so they keep the same rows."
        )
    else:
        notes.append(
            "The scripts read the whole file as the tool does and print its summary "
            "(rows, date coverage, places)."
        )
    notes += [
        (
            "Cells are read as text, as the tool reads them, and compared ignoring case, accents "
            "and apostrophe style; Python repeats the tool's rules exactly, R (stringi) and "
            "Julia (Unicode.normalize) fold accents the same way for Latin text."
        ),
        (
            "Suppression markers stay as published; the scripts list PHAC's markers and "
            "their meaning. Numbers become numeric only after the tool's steps, in columns "
            "with no marker."
        ),
    ]
    if plan.kind == "zip" and plan.member:
        notes.append(
            "R takes the ZIP's only CSV when there is one, since the French member name is "
            "stored in code page 437 without the UTF-8 flag; Python and Julia decode the "
            "names as the tool does and match the member name."
        )
    return Spec(
        kind="json" if plan.kind == "api" else ("zip_csv" if plan.kind == "zip" else "csv"),
        url=plan.url,
        file_name=file_name,
        method=_METHOD,
        title=f"PHAC Health Infobase: {title}",
        details=details,
        native={"python": py_read, "r": r_read, "julia": jl_read},
        prepare={
            "python": py_prepare,
            "r": r_prepare,
            "julia": jl_prepare,
            "stata": Code([], _markers_comment(plan, "*")),
        },
        notes=notes,
    )


async def query(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    return _spec(await _plan("phac_infobase_query", args, describe=False), describe=False)


async def describe(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    plan = await _plan("phac_infobase_describe_dataset", args, describe=True)
    return _spec(plan, describe=True)


async def list_datasets(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    lang = "fr" if str(args.get("lang", "en")) == "fr" else "en"
    listing = phac.list_datasets(args.get("topic"), args.get("query"), lang)
    files = "; ".join(f"{d.id}: {d.file_url}" for d in listing.datasets)
    return Spec(
        kind="none",
        url=constants.BASE_URL,
        file_name="",
        method="none",
        notes=[
            (
                "phac_infobase_list_datasets reads MapleStats' curated catalogue of Health "
                "Infobase files, not a source download, so there is nothing to fetch. "
                "Reproduce phac_infobase_query or phac_infobase_describe_dataset with one of "
                "these dataset ids for a script that downloads and reads its file."
            ),
            f"Files listed ({listing.total_count}): {files or 'none'}.",
        ],
    )
