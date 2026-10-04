from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Cell = int | float | str | None
FileFormat = Literal["xml", "xlsx", "zip", "other"]


class OebFile(BaseModel):
    index: int = Field(description="1-based position on the dataset page; pass it as `file`.")
    name: str = Field(description="File name as published.")
    caption: str | None = Field(
        default=None, description="Text the page gives the file (table or project label)."
    )
    release: str = Field(
        description="'current', or the ISO date of an archived release ('Data published ...')."
    )
    format: FileFormat
    readable: bool = Field(description="Whether oeb_query_dataset can read the rows.")
    url: str


class DatasetSummary(BaseModel):
    slug: str = Field(description="Dataset id; pass it as `dataset`.")
    title: str
    description: str
    update_frequency: str | None = None
    last_updated: date | None = Field(
        default=None, description="'Last updated' date the page states, when it states one."
    )
    file_types: list[str] = Field(default_factory=list, description="Types the page lists.")
    current_files: int
    archived_files: int
    readable: bool = Field(description="True when at least one file has readable rows.")
    note: str | None = Field(default=None, description="Why files are not read, if any.")
    page_url: str


class DatasetList(BaseModel):
    query: str | None
    total: int
    datasets: list[DatasetSummary]
    provenance: Provenance


class FieldInfo(BaseModel):
    name: str
    filled: int = Field(description="Records with a non-empty value.")
    numeric: bool = Field(description="Every filled value is a number.")
    examples: list[str] = Field(default_factory=list)


class DatasetDetail(BaseModel):
    dataset: DatasetSummary
    files: list[OebFile]
    selected_file: OebFile | None = Field(
        default=None, description="The file whose fields are described below."
    )
    sheet: str | None = Field(default=None, description="Worksheet read (Excel files).")
    sheets: list[str] = Field(default_factory=list, description="Worksheets (Excel files).")
    record_count: int | None = None
    fields: list[FieldInfo] = Field(default_factory=list)
    years: list[str] = Field(default_factory=list, description="Distinct years in the file.")
    distributor_count: int | None = None
    distributors: list[str] = Field(
        default_factory=list, description="Distinct company names (first ones, sorted)."
    )
    provenance: Provenance


class QueryResult(BaseModel):
    dataset: str
    title: str
    file: OebFile
    sheet: str | None = None
    columns: list[str]
    rows: list[dict[str, Cell]]
    total_matched: int
    returned: int
    truncated: bool
    matched_distributors: list[str] = Field(
        default_factory=list, description="Company names the distributor filter matched."
    )
    provenance: Provenance


class RateField(BaseModel):
    name: str
    description: str | None = None
    unit: str | None = None


class RatesTable(BaseModel):
    table: str
    title: str
    fields: list[RateField]
    rows: list[dict[str, Cell]]
    total_matched: int
    returned: int
    truncated: bool
    provenance: Provenance
