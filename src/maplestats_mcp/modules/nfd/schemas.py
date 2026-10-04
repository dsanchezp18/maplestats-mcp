"""Typed responses for the National Forestry Database."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class NfdTableSummary(BaseModel):
    table_id: str = Field(description="NFD table number, e.g. '3.2.1' or '5.1'.")
    section: str = Field(description="Topic heading, e.g. 'Forest Fires'.")
    title: str
    csv_url: str
    xlsx_url: str | None = None
    dictionary_url: str | None = None
    comments_url: str | None = Field(
        default=None, description="Agencies' comments and footnotes (.xls), when listed."
    )


class NfdTableList(BaseModel):
    tables: list[NfdTableSummary]
    count: int
    sections: list[str]
    provenance: Provenance


class NfdDimension(BaseModel):
    key: str = Field(description="Name to use in `filters` and `group_by`, e.g. 'tenure'.")
    label: str = Field(description="The CSV column heading in the requested language.")
    values: list[str]
    n_values: int
    values_truncated: bool = False


class NfdJurisdiction(BaseModel):
    iso: str
    name: str
    first_year: int
    last_year: int


class NfdTableDescription(BaseModel):
    table_id: str
    section: str
    title: str
    dictionary_title: str | None = Field(
        default=None, description="Title in the table's data dictionary."
    )
    source: str | None = Field(default=None, description="Data source named in the dictionary.")
    last_updated: date | None = Field(
        default=None, description="'Last update' date in the data dictionary."
    )
    value_label: str = Field(description="Heading of the value column.")
    unit: str | None = Field(
        default=None,
        description="Unit of the value; null when the table's own Unit of Measure column sets it.",
    )
    first_year: int
    last_year: int
    n_rows: int
    jurisdictions: list[NfdJurisdiction]
    dimensions: list[NfdDimension]
    qualifiers: dict[str, str] = Field(
        description="Data-quality codes that occur in this table, with their meaning."
    )
    quirks: list[str] = Field(description="Checked oddities of this table's file.")
    csv_url: str
    dictionary_url: str | None = None
    comments_url: str | None = None
    provenance: Provenance


class NfdRow(BaseModel):
    year: int | None = None
    iso: str | None = None
    jurisdiction: str | None = None
    dimensions: dict[str, str] = Field(default_factory=dict)
    value: float | None = Field(
        description=(
            "Null when the agency gave no figure (see `qualifiers`: usually u, U or n, "
            "occasionally another code such as a)."
        )
    )
    unit: str | None = None
    qualifiers: list[str] = Field(
        default_factory=list,
        description="Data-quality code(s); several when `group_by` sums rows.",
    )
    n_rows: int = Field(default=1, description="Source rows behind this value.")
    n_missing: int = Field(default=0, description="Of those, rows with no figure.")
    footnotes: list[str] = Field(
        default_factory=list,
        description="Footnote letters on the row's labels; text via nfd_table_comments.",
    )


class NfdQueryResult(BaseModel):
    table_id: str
    title: str
    unit: str | None = None
    rows: list[NfdRow]
    returned_count: int
    matched_count: int
    limit: int
    group_by: list[str] = Field(default_factory=list)
    qualifiers: dict[str, str] = Field(description="Meaning of the codes in `rows`.")
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class NfdComment(BaseModel):
    iso: str
    jurisdiction: str
    years: list[int]
    comment: str
    footnotes: str | None = None
    context: str | None = Field(
        default=None, description="Extra columns of the comments sheet, e.g. Protection Zone."
    )


class NfdCommentsResult(BaseModel):
    table_id: str
    title: str
    comments: list[NfdComment]
    returned_count: int
    matched_count: int
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
