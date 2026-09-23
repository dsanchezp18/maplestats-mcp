"""Typed responses for Canada Energy Regulator open data."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class CerFile(BaseModel):
    name: str
    url: str = Field(description="Pass to cer_query_file.")
    language: str | None = None


class CerDataset(BaseModel):
    id: str
    title: str
    files: list[CerFile]


class CerDatasetList(BaseModel):
    datasets: list[CerDataset]
    total_count: int
    provenance: Provenance


class CerRows(BaseModel):
    url: str
    columns: list[str]
    rows: list[dict[str, str]]
    total_rows: int = Field(description="Rows in the file.")
    matching_rows: int = Field(description="Rows passing the filters and date range.")
    returned_count: int
    date_column: str | None = None
    provenance: Provenance
