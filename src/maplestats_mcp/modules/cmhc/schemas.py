"""Typed response models for CMHC's Housing Market Information Portal (HMIP).

Field names and shapes confirmed live this session against
https://www03.cmhc-schl.gc.ca/hmip-pimh/ -- see client.py's module
docstring for the full list of what was verified, including two real
quirks modelled explicitly here rather than smoothed over:

1. A data cell can be a suppressed/not-applicable marker ("**" or "++")
   instead of a number -- TableCell.value is `float | None`, with the
   marker preserved in `flag` rather than silently dropped.
2. HMIP's own resolved-table JSON model uses the key "GeograghyName"
   (a genuine typo in CMHC's own payload, confirmed live) -- client.py
   reads that key but this schema exposes the corrected `geography_name`
   field name, so the typo does not leak into this module's public
   contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class CategoryOption(BaseModel):
    """One (category_level_1, category_level_2) pair from TableMapChart's navigation."""

    category_level_1: str
    category_level_2: str


class CategoryList(BaseModel):
    geography_type: str
    geography_id: str
    categories: list[CategoryOption]
    total_count: int
    provenance: Provenance


class TableFieldOption(BaseModel):
    """One resolvable (column_field, row_field) combination for a category.

    `label` is HMIP's own human-readable name for this breakdown (e.g.
    "Bedroom Type", "Historical Time Periods") -- pass `column_field`/
    `row_field` straight through to `get_table_data`. `breakdown` says
    which axis the label names: HMIP lists column breakdowns under "By:"
    and row breakdowns under "Display Options:".
    """

    label: str
    column_field: str
    row_field: str
    breakdown: Literal["column", "row"] | None = Field(
        default=None,
        description='Which axis `label` names: "column" (HMIP\'s "By:" list, e.g. Bedroom '
        'Type) or "row" (its "Display Options:" list, e.g. Historical Time Periods).',
    )


class TableOptions(BaseModel):
    category_level_1: str
    category_level_2: str
    field_options: list[TableFieldOption]
    provenance: Provenance


class ProvinceOption(BaseModel):
    id: str
    name: str
    type_code: str


class ProvinceList(BaseModel):
    provinces: list[ProvinceOption]
    provenance: Provenance


class MetroAreaOption(BaseModel):
    """One HMIP metropolitan major area: a CMA, a census agglomeration or a smaller centre."""

    id: str = Field(
        description='Pass as geography_id with geography_type="MetropolitanMajorArea". '
        'Keep it as text: some ids start with zero ("0120").'
    )
    name: str
    province_id: str
    province_name: str


class MetroAreaList(BaseModel):
    geography_type: str = Field(
        default="MetropolitanMajorArea",
        description="The geography_type to pass with these ids.",
    )
    areas: list[MetroAreaOption]
    total_count: int
    provenance: Provenance


class TableCell(BaseModel):
    """One value in a table row.

    `value` is `None` when the cell held a suppressed/not-applicable
    marker ("**"/"++") rather than a number -- see constants.py's
    SUPPRESSED_VALUE_TOKENS. `flag` is CMHC's reliability code
    (a/b/c/d: Excellent/Very good/Good/Poor) or the raw marker text,
    kept alongside the value rather than discarded.
    """

    value: float | None
    flag: str | None = None


class TableDataRow(BaseModel):
    period: str
    values: dict[str, TableCell]


class FilterOption(BaseModel):
    """One extra filter dimension a table can be narrowed by (e.g. season,
    dwelling type) - confirmed live these change the actual returned
    values, not just a display label (e.g. national rental vacancy rate
    for "Row" dwellings differs from "Apartment"). `key` is what goes in
    `get_table_data`'s `filters` dict; `values` are the only valid values
    for that key."""

    key: str
    label: str | None = None
    values: list[str]


class TableDataResult(BaseModel):
    table_id: str
    table_name: str
    geography_name: str
    reference_period: str | None = Field(
        default=None,
        description='The period the values refer to, in CMHC\'s words: "October 2025" for a '
        'cross-tab, "January 1990 to September 2026" for a time series. Null when the '
        "export did not state one.",
    )
    citation: str = Field(
        default="",
        description="A source line to carry with any reuse of the values: publisher, table, "
        "geography and reference period.",
    )
    category_level_1: str
    category_level_2: str
    column_field: str
    row_field: str
    columns: list[str]
    rows: list[TableDataRow]
    provenance: Provenance
    notes: list[str] = Field(
        default_factory=list,
        description="CMHC's own reliability-code legend and source line from the CSV export.",
    )
    available_filters: list[FilterOption] = Field(
        default_factory=list,
        description="Extra filters this table supports - pass a subset as get_table_data's filters.",
    )
    applied_filters: dict[str, str] = Field(
        default_factory=dict,
        description="The filters actually applied to this result: those passed in `filters`, "
        "plus CMHC's own default for any filter key not passed (see default_filters).",
    )
    default_filters: dict[str, str] = Field(
        default_factory=dict,
        description="Filters CMHC applied by default because `filters` did not set them, e.g. "
        '{"dwelling_type_desc_en": "Row / Apartment"} for a Rental Market Survey table: '
        "row and apartment structures combined, not apartments only.",
    )
    filter_notes: list[str] = Field(
        default_factory=list,
        description="One line per filter dimension: the value applied, whether it is CMHC's "
        "default, and the other values that can be passed in `filters`.",
    )
    aggregate: Literal["annual", "ytd"] | None = Field(
        default=None,
        description='The aggregation MapleStats applied to monthly rows: "annual" (calendar-'
        'year totals) or "ytd" (January to the latest month, for every year). Null: CMHC\'s '
        "rows as published.",
    )
    aggregation_note: str | None = Field(
        default=None,
        description="How the rows were summed from CMHC's monthly values, and which years "
        "were left out as incomplete.",
    )
    flag_legend: dict[str, str] = Field(
        default_factory=dict,
        description="What each cell flag in this result means (a/b/c/d reliability, ** "
        "suppressed, ++ not significant); CMHC's thresholds and release rules are in "
        "docs://cmhc/rms-methodology.",
    )
