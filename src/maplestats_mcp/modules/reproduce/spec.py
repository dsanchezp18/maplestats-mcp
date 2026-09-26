"""What a reproduction script fetches, how to read it, and what to keep.

A Spec is language-neutral: render.py turns it into R, Python, Stata and
Julia. Filters name columns as the source file spells them and run right
after loading, before any renaming, so the same filter works in every
language whatever each one's name cleaning produces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal[
    "csv",  # delimited text (see Spec.delimiter)
    "zip_csv",  # a ZIP holding a delimited data file
    "zip",  # a ZIP whose contents the user picks
    "xlsx",
    "json",
    "html_table",
    "feed",  # RSS or Atom
    "ivt",  # Beyond 20/20, read only by canivt in R
    "file",  # downloaded as is (fixed-width text, SDMX-ML, GTFS-RT); notes say how to read it
    "none",  # nothing a script can fetch; notes say why
]

Op = Literal["contains", "terms", "is", "starts", "eq", "ge", "le"]


@dataclass
class Filter:
    """Keep rows where `columns` satisfy `op` against `value`.

    contains: the text appears in the first column (case-insensitive).
    terms: every word of the text appears somewhere in the columns.
    is: the first column equals the text, ignoring case and outer spaces.
    starts: the first column starts with the text.
    eq, ge, le: compare the first column with a number or ISO date text.
    """

    op: Op
    columns: list[str]
    value: Any


@dataclass
class Code:
    """Language-specific code: packages or import lines, then the body."""

    imports: list[str]
    body: str


@dataclass
class Spec:
    kind: Kind
    url: str
    file_name: str
    method: str
    title: str = ""
    delimiter: str = ","
    # Literal cell text meaning missing (IP Horizons writes "NULL").
    na_values: list[str] = field(default_factory=list)
    # A header row starting with this is stripped of it (FDSN's "#EventID").
    header_prefix: str = ""
    # JSON: where the rows sit, whether each item holds its own rows (WDS
    # vectors), and a per-row sub-object to unwrap (ArcGIS "attributes",
    # GeoJSON "properties").
    records_path: list[str] = field(default_factory=list)
    each_item: bool = False
    record_field: str = ""
    single_object: bool = False
    # {"col": [...], ...}: one list per column (StatCan's SDG data files).
    columnar: bool = False
    # [[{"Name": col, "Value": {"Literal": v}}, ...], ...] (Transport Canada).
    name_value: bool = False
    # {"FXUSDCAD": {...}, "V39079": {...}}: records keyed by name (Valet lists).
    records_dict: bool = False
    post_json: Any = None
    post_form: dict[str, str] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    # zip_csv: the data file's name must contain this (default: the first
    # CSV that is not metadata).
    member_pattern: str = ""
    html_table_index: int = 0
    # xlsx: the sheet to read and how many rows sit above its header.
    sheet: str = ""
    skip_rows: int = 0
    filters: list[Filter] = field(default_factory=list)
    sort_by: str = ""
    sort_descending: bool = False
    # Whole retrieval code per language, replacing the generic loader.
    native: dict[str, Code] = field(default_factory=dict)
    languages: tuple[str, ...] = ("r", "python", "stata", "julia")
    notes: list[str] = field(default_factory=list)
    source: str = ""  # key into cleaning.SPECIFIC
