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
    real_time: bool = Field(
        default=False,
        description=(
            "True for StatCan's real-time tables: revision-history (vintage) tables that "
            "keep every past release of a series. They are ordinary WDS tables, read like "
            "any other."
        ),
    )


class CubeSummaryList(BaseModel):
    cubes: list[CubeSummary]
    total_count: int = Field(
        description="Tables matching the query (or all tables) before limit/offset."
    )
    returned_count: int = Field(default=0, description="Tables in `cubes`.")
    offset: int = 0
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
    member_count: int = Field(default=0, description="All members of this dimension.")
    members_matched: int = Field(
        default=0, description="Members matching `member_query` (all when none was given)."
    )
    members: list[DimensionMember] = Field(
        description="The members returned, capped by `member_limit` (see provenance.limits)."
    )


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
    footnote_count: int = 0
    dimensions: list[CubeDimension]
    provenance: Provenance


class SeriesInfo(BaseModel):
    product_id: int
    coordinate: str
    vector_id: int
    series_title_en: str | None = None
    series_title_fr: str | None = None
    frequency_code: int | None = None
    scalar_factor_code: int | None = None
    decimals: int | None = None
    terminated: bool | None = None
    member_uom_code: int | None = None
    provenance: Provenance


class ObservationRow(BaseModel):
    """One data point. `value`/`decimals` already reflect StatCan's own
    rounding; `scalar_factor_code` is deliberately NOT applied to `value`
    here — WDS never auto-applies it either. Multiply `value` by
    `scale_multiplier` (10 ** scalar_factor_code) for the scaled figure.
    """

    ref_period: date
    value: float | None
    decimals: int
    scalar_factor_code: int
    scale_multiplier: int = 1
    symbol_code: int
    status_code: int
    security_level_code: int
    release_time: datetime | None = None


class VectorSeries(BaseModel):
    product_id: int
    coordinate: str
    vector_id: int
    observations: list[ObservationRow]


class VectorData(VectorSeries):
    provenance: Provenance


class FailedVector(BaseModel):
    vector_id: int
    reason: str


class VectorDataSet(BaseModel):
    """Several series from one call, one provenance for all of them. Vectors
    WDS could not serve are listed in `failed` instead of failing the call."""

    series: list[VectorSeries]
    failed: list[FailedVector] = Field(default_factory=list)
    provenance: Provenance


class CodeSetEntry(BaseModel):
    code: int
    # Nullable: uom code 0 ("no unit") legitimately has no description in
    # either language — confirmed live, not a parsing failure.
    description_en: str | None
    description_fr: str | None


class CodeSets(BaseModel):
    counts: dict[str, int] = Field(
        default_factory=dict, description="Total entries per category before `limit`."
    )
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
