"""Typed responses for StatCan PUMF tools."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class PumfProduct(BaseModel):
    catalogue_number: str
    title: str
    url: str
    release_date: str | None = None
    description: str | None = None


class PumfSearchResult(BaseModel):
    query: str
    products: list[PumfProduct]
    total_matched: int
    provenance: Provenance


class PumfFile(BaseModel):
    label: str = Field(description="Link text on StatCan's page, e.g. 'Individuals file, 2021'.")
    url: str = Field(description="Direct ZIP download; pass to statcan_pumf_get_codebook.")
    page_url: str


class PumfFileList(BaseModel):
    catalogue_number: str
    files: list[PumfFile]
    pages_read: list[str]
    provenance: Provenance


class ZipEntry(BaseModel):
    name: str
    size_bytes: int


class ZipContents(BaseModel):
    url: str
    archive_bytes: int
    entries: list[ZipEntry]
    codebook_files: list[str] = Field(description="Entries statcan_pumf_get_codebook can read.")
    provenance: Provenance


class ValueLabel(BaseModel):
    code: str
    label: str


class PumfVariable(BaseModel):
    name: str
    label: str | None = None
    position: int | None = Field(
        default=None, description="1-based start column, fixed-width files."
    )
    width: int | None = None
    values: list[ValueLabel] = Field(description="Value labels; truncated past 60.")
    values_truncated: bool = False


class Codebook(BaseModel):
    url: str
    source_files: list[str] = Field(description="Codebook files inside the ZIP this was read from.")
    variables: list[PumfVariable]
    total_variables: int
    matched_variables: int
    weight_variables: list[str] = Field(
        description="Likely survey weights (final and bootstrap/replicate). Use them: unweighted "
        "PUMF counts are not population estimates."
    )
    provenance: Provenance


class TableGroup(BaseModel):
    variable: str
    code: str
    label: str | None = None


class TableCell(BaseModel):
    groups: list[TableGroup]
    estimate: float | None = Field(
        description="Weighted total, weighted mean, or percent share, per `statistic`."
    )
    unweighted_n: int = Field(description="Respondents in the cell (sample, not population).")
    low_count: bool


class WeightedTable(BaseModel):
    url: str
    data_file: str
    statistic: str
    weight: str
    value_variable: str | None = None
    filters: dict[str, list[str]]
    cells: list[TableCell]
    truncated: bool
    unweighted_n: int
    weighted_total: float
    notes: list[str]
    provenance: Provenance
