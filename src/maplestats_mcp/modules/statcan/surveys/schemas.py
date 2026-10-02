"""Typed responses for StatCan's survey directory and IMDB survey metadata."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class SurveyListing(BaseModel):
    survey_id: int
    name: str


class SurveyListResult(BaseModel):
    query: str
    surveys: list[SurveyListing] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    provenance: Provenance


class SurveyMetadata(BaseModel):
    survey_id: int
    name: str
    status: str | None = None
    frequency: str | None = None
    description: str | None = None
    subjects: list[str] = Field(default_factory=list)
    detail_url: str
    provenance: Provenance


class RdcHolding(BaseModel):
    record_numbers: list[int] = Field(
        default_factory=list,
        description=(
            "IMDB record numbers (SDDS), the ids of statcan_surveys_get_survey_metadata. "
            "Linked files list several; 8006 is a generic bucket shared by about a hundred "
            "unrelated holdings, so it does not identify a survey."
        ),
    )
    name: str
    acronym: str | None = None
    cycles: list[str] = Field(
        default_factory=list, description="Cycles, years or files held, as StatCan lists them."
    )
    detail_url: str | None = Field(
        default=None, description="IMDB survey record or other StatCan page; None when unlinked."
    )


class RdcSearchResult(BaseModel):
    query: str
    holdings: list[RdcHolding] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    provenance: Provenance


class SurveyLink(BaseModel):
    name: str
    url: str
    sdds_id: int | None = Field(
        default=None, description="IMDB record number when the link is a survey (SDDS) page."
    )
    instance_id: int | None = Field(
        default=None, description="IMDB instance id when the link is a single cycle (Id=) page."
    )


class RtraDataset(BaseModel):
    category: str | None = Field(
        default=None, description="Page section, e.g. 'Social data' or 'Administrative data'."
    )
    survey: str
    table_label: str | None = Field(
        default=None, description="Caption of the dataset's table, usually the cycle."
    )
    tag_name: str
    dataset_name: str | None = None
    rounding_base: int | None = Field(
        default=None, description="Unweighted counts are rounded to a multiple of this."
    )
    weight_name: str | None = None
    deleted_variables: list[str] = Field(
        default_factory=list, description="Variables removed from the RTRA version."
    )
    survey_links: list[SurveyLink] = Field(default_factory=list)


class RtraSearchResult(BaseModel):
    query: str
    datasets: list[RtraDataset] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    provenance: Provenance
