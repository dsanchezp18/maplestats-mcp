"""Typed responses for the Job Bank wages module."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

WageUnit = Literal["hourly", "annual"]
GeographyLevel = Literal["national", "provincial", "economic_region"]


class WageRelease(BaseModel):
    """Which yearly Job Bank release a result was read from, and how to cite it."""

    release_year: int = Field(description="Year in the resource name, e.g. 2025 for '2025 Wages'.")
    resource_id: str = Field(description="open.canada.ca DataStore resource id of that release.")
    dataset_url: str = Field(description="The dataset's page on the Open Government Portal.")
    job_bank_url: str = Field(description="Job Bank's own wage search for the same estimates.")
    methodology_url: str
    citation: str = Field(description="A citation for the release, in the call's language.")
    available_years: list[int] = Field(
        description="Releases this module can read (NOC 2021, 2023 on), newest first."
    )
    note: str | None = Field(
        default=None,
        description="Set when the release could not be found in the package and a pinned one "
        "was used instead.",
    )


class WageRow(BaseModel):
    """One occupation's wages in one geography, as Job Bank publishes it."""

    noc_code: str = Field(description="Five-digit NOC 2021 code, e.g. '21231'.")
    occupation: str = Field(description="NOC title in the call's language.")
    region_code: str = Field(
        description="Job Bank geography code: ER00 Canada, ER35 Ontario, "
        "ER3530 the Toronto economic region."
    )
    region_name: str
    province: str | None = Field(
        description="Province or territory code as the dataset gives it (NL, PEI, NS, NB, QC, "
        "ON, MB, SK, AB, BC, YK, NWT, NU); null for Canada."
    )
    geography_level: GeographyLevel
    wage_unit: WageUnit = Field(
        description="Whether the wages are dollars per hour or per year. Job Bank shows annual "
        "wages for occupations with many self-employed workers (physicians, lawyers)."
    )
    low_wage: float | None = Field(description="In most cases the 10th percentile.")
    median_wage: float | None
    high_wage: float | None = Field(description="In most cases the 90th percentile.")
    average_wage: float | None = None
    quartile_1_wage: float | None = None
    quartile_3_wage: float | None = None
    published: bool = Field(
        description="False when Job Bank published no wage for this cell (suppressed for data "
        "quality or confidentiality); the comment then says where to look instead."
    )
    data_source: str | None = Field(
        description="The data source Job Bank names for the cell, e.g. 'Labour Force Survey', "
        "'Small Area Estimation', '2021 Census', 'Employment Insurance Survey Data'."
    )
    reference_period: str | None = Field(
        description="Period of the source data, e.g. '2023-2024' or '2021' (null when not "
        "published)."
    )
    source_detail: str | None = Field(
        default=None,
        description="Job Bank's detailed source code for the cell when the release has one "
        "(2025: e.g. 'LFS 2023-24 ER NOC5'); its CAN/PR/ER part is the geography the estimate "
        "was made for.",
    )
    estimate_geography: GeographyLevel | None = Field(
        default=None,
        description="Geography the estimate was actually made for, read from source_detail. "
        "An economic region with estimate_geography 'provincial' shows the province's wage.",
    )
    revision_date: date | None = None
    comment: str | None = Field(default=None, description="Job Bank's note on the cell.")
    employees_with_non_wage_benefits_pct: float | None = Field(
        default=None,
        description="Percentage of employees with non-wage benefits, as published (2024 on).",
    )


class OccupationMatch(BaseModel):
    noc_code: str
    title_en: str
    title_fr: str
    national_median_wage: float | None
    wage_unit: WageUnit
    reference_period: str | None
    data_source: str | None


class OccupationSearchResult(BaseModel):
    query: str
    matches: list[OccupationMatch]
    total_matching: int
    returned_count: int
    release: WageRelease
    provenance: Provenance


class EconomicRegion(BaseModel):
    region_code: str
    name: str
    province: str | None
    geography_level: GeographyLevel


class EconomicRegionList(BaseModel):
    regions: list[EconomicRegion]
    returned_count: int
    release: WageRelease
    provenance: Provenance


class OccupationWages(BaseModel):
    noc_code: str
    occupation: str
    rows: list[WageRow] = Field(
        description="Canada first, then provinces with their economic regions, as Job Bank "
        "orders them."
    )
    returned_count: int
    published_count: int
    unpublished_count: int
    release: WageRelease
    provenance: Provenance


class OccupationComparison(BaseModel):
    region_code: str
    region_name: str
    rows: list[WageRow] = Field(description="One row per occupation found, in the order asked.")
    not_found: list[str] = Field(description="NOC codes the release does not have.")
    mixed_units: bool = Field(
        description="True when some occupations are hourly and others annual: do not compare "
        "those figures directly."
    )
    release: WageRelease
    provenance: Provenance
