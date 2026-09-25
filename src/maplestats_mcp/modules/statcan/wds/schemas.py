"""Typed response models for the StatCan WDS submodule.

Field names verified against live WDS responses fetched this session
(getCubeMetadata, getAllCubesListLite, getDataFromVectorsAndLatestNPeriods,
getCodeSets against productId 18100004 / vectorId 41690973), not guessed
from the user guide prose alone.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class CubeSummary(BaseModel):
    """One row from getAllCubesList/getAllCubesListLite."""

    product_id: int
    cansim_id: str | None = None
    cube_title_en: str
    cube_title_fr: str
    cube_start_date: str
    cube_end_date: str
    release_time: str
    archived: bool
    frequency_code: int
    subject_codes: list[str] = Field(default_factory=list)
    survey_codes: list[str] = Field(default_factory=list)
    dimension_count: int | None = None


class CubeSummaryList(BaseModel):
    cubes: list[CubeSummary]
    total_count: int
    provenance: Provenance


class DimensionMember(BaseModel):
    member_id: int
    parent_member_id: int | None
    member_name_en: str
    member_name_fr: str
    classification_code: str | None = None
    geo_level: int | None = None
    terminated: bool = False


class CubeDimension(BaseModel):
    dimension_position_id: int
    dimension_name_en: str
    dimension_name_fr: str
    has_uom: bool
    members: list[DimensionMember]


class Footnote(BaseModel):
    """A table-level footnote. Real field names are `footnotesEn`/
    `footnotesFr` (plural) — verified live; a plain string list was the
    wrong shape."""

    footnote_id: int
    text_en: str
    text_fr: str


class CubeMetadata(BaseModel):
    product_id: int
    cansim_id: str | None = None
    cube_title_en: str
    cube_title_fr: str
    cube_start_date: str
    cube_end_date: str
    frequency_code: int
    n_series: int
    n_datapoints: int
    release_time: str
    archive_status_en: str
    archive_status_fr: str
    subject_codes: list[str] = Field(default_factory=list)
    survey_codes: list[str] = Field(default_factory=list)
    footnotes: list[Footnote] = Field(default_factory=list)
    dimensions: list[CubeDimension]
    provenance: Provenance


class SeriesInfo(BaseModel):
    product_id: int
    coordinate: str
    vector_id: int
    provenance: Provenance


class ObservationRow(BaseModel):
    """One data point. `value`/`decimals` already reflect StatCan's own
    rounding; `scalar_factor_code` is deliberately NOT applied to `value`
    here — WDS never auto-applies it either. Call apply_scalar_factor()
    with the matching CodeSet entry if a scaled value is needed.
    """

    ref_period: date
    value: float | None
    decimals: int
    scalar_factor_code: int
    symbol_code: int
    status_code: int
    security_level_code: int
    release_time: datetime | None = None


class VectorData(BaseModel):
    product_id: int
    coordinate: str
    vector_id: int
    observations: list[ObservationRow]
    provenance: Provenance


class CodeSetEntry(BaseModel):
    code: int
    # Nullable: uom code 0 ("no unit") legitimately has no description in
    # either language — confirmed live, not a parsing failure.
    description_en: str | None
    description_fr: str | None


class CodeSets(BaseModel):
    scalar: list[CodeSetEntry]
    frequency: list[CodeSetEntry]
    symbol: list[CodeSetEntry]
    status: list[CodeSetEntry]
    uom: list[CodeSetEntry]
    survey: list[CodeSetEntry]
    subject: list[CodeSetEntry]
    classification_type: list[CodeSetEntry]
    security_level: list[CodeSetEntry]
    terminated: list[CodeSetEntry]
    provenance: Provenance


class ChangedCubeEntry(BaseModel):
    product_id: int
    release_time: str


class ChangedCubeList(BaseModel):
    cubes: list[ChangedCubeEntry]
    provenance: Provenance


class ChangedSeriesEntry(BaseModel):
    product_id: int
    coordinate: str
    vector_id: int
    release_time: str


class ChangedSeriesList(BaseModel):
    series: list[ChangedSeriesEntry]
    provenance: Provenance


class FullTableDownloadLink(BaseModel):
    product_id: int
    format: str  # "csv" or "sdmx"
    language: str  # "en" or "fr"
    download_url: str
    provenance: Provenance


def apply_scalar_factor(value: float, scalar_factor_code: int) -> float:
    """Apply the x10^n multiplier WDS documents but never auto-applies.

    scalarFactorCode 0=units,1=tens,2=hundreds,3=thousands,4=tens of
    thousands,5=hundreds of thousands,6=millions, per getCodeSets'
    `scalar` entries — this maps code -> power of ten directly rather
    than requiring a getCodeSets round trip for the common cases.
    """
    return value * (10**scalar_factor_code)
