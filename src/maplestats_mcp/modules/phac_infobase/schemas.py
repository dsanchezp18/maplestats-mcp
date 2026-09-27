"""Typed responses for PHAC Health Infobase data files."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class DatasetSummary(BaseModel):
    id: str = Field(description="Pass to phac_infobase_describe_dataset or phac_infobase_query.")
    title: str
    topic: str
    topic_label: str
    description: str
    frequency: str = Field(description="Update cadence, or 'archived'.")
    archived: bool
    languages: list[str] = Field(description="File languages: ['en'] or ['en', 'fr'].")
    file_url: str = Field(description="The file read for the requested language.")
    dashboard_url: str


class TopicCount(BaseModel):
    key: str = Field(description="Pass as `topic` to phac_infobase_list_datasets.")
    label: str
    datasets: int


class DatasetList(BaseModel):
    datasets: list[DatasetSummary]
    topics: list[TopicCount] = Field(description="Every topic in the catalogue.")
    total_count: int
    provenance: Provenance


class ColumnSummary(BaseModel):
    name: str
    distinct_values: int
    empty_cells: int
    sample_values: list[str] = Field(
        description="Most common values (up to 12), for choosing exact filters."
    )
    numeric: bool = Field(description="Every non-empty, non-marker value parses as a number.")


class Marker(BaseModel):
    value: str = Field(description="The cell text, e.g. 'Suppr.'.")
    meaning: str
    count: int


class DatasetDescription(BaseModel):
    id: str
    title: str
    topic: str
    description: str
    notes: str | None = None
    frequency: str
    file_url: str
    file_language: str = Field(description="Language of the file read ('en' or 'fr').")
    dashboard_url: str
    last_modified: str | None = Field(
        default=None, description="The file's HTTP Last-Modified date, or the API's updatedAt."
    )
    encoding: str
    row_count: int
    columns: list[ColumnSummary]
    date_column: str | None = None
    date_start: str | None = Field(default=None, description="Earliest parsed date (ISO).")
    date_end: str | None = Field(default=None, description="Latest parsed date (ISO).")
    geo_column: str | None = None
    geo_values: list[str] = Field(default_factory=list)
    markers: list[Marker] = Field(
        default_factory=list, description="Suppression and missing-value markers in the file."
    )
    decimal_comma: bool = Field(
        default=False, description="Numbers use a decimal comma (French files), e.g. 12,2."
    )
    provenance: Provenance


class QueryResult(BaseModel):
    id: str
    title: str
    file_url: str
    columns: list[str]
    rows: list[dict[str, str]]
    total_rows: int = Field(description="Rows in the file.")
    matching_rows: int = Field(description="Rows passing every filter.")
    returned_count: int
    date_column: str | None = None
    geo_column: str | None = None
    markers: list[Marker] = Field(
        default_factory=list, description="Suppression or missing-value markers in these rows."
    )
    decimal_comma: bool = False
    provenance: Provenance
