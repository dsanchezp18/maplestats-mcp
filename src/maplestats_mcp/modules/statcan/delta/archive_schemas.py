"""Typed responses for reading the inside of a Delta File and listing the archive."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class DeltaMember(BaseModel):
    member_id: int
    name_en: str | None = None
    name_fr: str | None = None
    terminated: bool | None = None


class DeltaDimension(BaseModel):
    position_id: int
    name_en: str | None = None
    name_fr: str | None = None
    member_count: int
    members: list[DeltaMember] | None = Field(
        default=None, description="Only with detail=True and one product_id."
    )


class DeltaCorrection(BaseModel):
    correction_id: int | None = None
    date: str | None = None
    note: str | None = Field(default=None, description="HTML removed; in the requested language.")


class DeltaTable(BaseModel):
    product_id: int
    cansim_id: str | None = Field(
        default=None, description="Legacy CANSIM number, absent for tables created after 2013."
    )
    title_en: str | None = None
    title_fr: str | None = None
    frequency_code: int | None = None
    frequency: str | None = None
    release_time: str | None = Field(default=None, description="Local Ottawa time, ISO 8601.")
    series_count: int | None = Field(default=None, description="nbSeriesCube: series in the cube.")
    datapoint_count: int | None = Field(default=None, description="nbDatapointsCube.")
    start_date: str | None = None
    end_date: str | None = None
    archive_status_code: int | None = None
    archive_status: str | None = None
    correction_count: int = 0
    corrections: list[DeltaCorrection] | None = Field(
        default=None, description="Only with detail=True and one product_id."
    )
    dimensions: list[DeltaDimension] = Field(default_factory=list)


class DeltaTableList(BaseModel):
    date: str
    zip_url: str
    zip_size_bytes: int | None = None
    last_modified: str | None = None
    etag: str | None = None
    table_count: int = Field(description="Tables in the release, before any filter.")
    returned: int
    truncated: bool = False
    tables: list[DeltaTable]
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class DeltaRow(BaseModel):
    vector_id: int
    coordinate: str
    ref_period: str
    ref_period_end: str | None = Field(
        default=None, description="End of the reference period (refPer2), for ranges."
    )
    value: float | None = Field(
        default=None, description="Raw value; the scalar factor is NOT applied."
    )
    symbol_code: int
    status_code: int
    security_level_code: int
    scalar_factor_code: int
    decimals: int
    frequency_code: int
    release_time: str


class DeltaLegend(BaseModel):
    """What the codes in the rows mean, decoded from the file's codeSet.xml."""

    symbols: dict[int, str] = Field(default_factory=dict)
    statuses: dict[int, str] = Field(default_factory=dict)
    security_levels: dict[int, str] = Field(default_factory=dict)
    scalar_factors: dict[int, str] = Field(default_factory=dict)
    frequencies: dict[int, str] = Field(default_factory=dict)


class DeltaTableData(BaseModel):
    date: str
    product_id: int
    cansim_id: str | None = None
    title_en: str | None = None
    title_fr: str | None = None
    release_time: str | None = None
    series_count: int | None = None
    zip_url: str
    vector_filter: list[int] | None = None
    row_count: int
    truncated: bool = Field(
        description="True when more matching rows exist than max_rows; raise max_rows or filter."
    )
    csv_rows_found: bool = Field(
        description="False when the table is in the release's metadata but has no CSV rows."
    )
    compressed_bytes_scanned: int
    rows: list[DeltaRow]
    legend: DeltaLegend
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class DeltaFileEntry(BaseModel):
    date: str
    weekday: str
    url: str
    size_bytes: int | None = None
    last_modified: str | None = None
    etag: str | None = None


class DeltaFileList(BaseModel):
    files: list[DeltaFileEntry]
    count: int
    oldest: str | None = None
    newest: str | None = None
    requested_date: str | None = None
    requested_status: str | None = Field(
        default=None,
        description="available, no release that day, past retention or not yet published.",
    )
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class RealTimeTable(BaseModel):
    real_time_product_id: int
    real_time_table: str = Field(description="Hyphenated table number, e.g. 36-10-0491.")
    real_time_title_en: str
    real_time_title_fr: str | None = None
    regular_product_id: int
    regular_table: str
    regular_title_en: str
    regular_title_fr: str | None = None
    wds_available: bool = Field(
        description="False when WDS getCubeMetadata answered CUBE_NOT_AVAILABLE on 2026-10-02."
    )
    note: str | None = None


class RealTimeTableList(BaseModel):
    count: int
    tables: list[RealTimeTable]
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
