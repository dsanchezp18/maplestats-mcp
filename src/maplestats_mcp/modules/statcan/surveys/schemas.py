"""Typed responses for StatCan's survey directory and IMDB survey metadata."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

# The methodology sections of an IMDB survey record; the field names of
# SurveyMethodology and the values of get_survey_metadata's `section` argument.
SurveySection = Literal[
    "target_population",
    "instrument_design",
    "sampling",
    "data_sources",
    "error_detection",
    "imputation",
    "estimation",
    "quality_evaluation",
    "disclosure_control",
    "revisions_and_seasonal_adjustment",
    "data_accuracy",
]


class SurveyListing(BaseModel):
    survey_id: int
    name: str


class SurveyListResult(BaseModel):
    query: str
    surveys: list[SurveyListing] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    provenance: Provenance


class SurveyMethodology(BaseModel):
    """The "Data sources and methodology" and "Data accuracy" sections of an IMDB
    record, as text (paragraphs separated by blank lines). A section the record does
    not have, or one left out by the `section` argument, is None."""

    target_population: str | None = None
    instrument_design: str | None = None
    sampling: str | None = None
    data_sources: str | None = None
    error_detection: str | None = None
    imputation: str | None = None
    estimation: str | None = None
    quality_evaluation: str | None = None
    disclosure_control: str | None = None
    revisions_and_seasonal_adjustment: str | None = None
    data_accuracy: str | None = None


class SurveyMetadata(BaseModel):
    survey_id: int
    name: str
    status: str | None = None
    frequency: str | None = None
    description: str | None = None
    subjects: list[str] = Field(default_factory=list)
    reference_period: str | None = Field(
        default=None, description="The record's 'Reference period', as IMDB states it."
    )
    collection_period: str | None = Field(
        default=None, description="The record's 'Collection period', as IMDB states it."
    )
    response: str | None = Field(
        default=None,
        description=(
            "Whether responding is mandatory or voluntary ('mandatory', 'voluntary'; "
            "'obligatoire', 'volontaire' in French), read from the Data sources section; "
            "None when the record does not say, or says both."
        ),
    )
    collection_methods: str | None = Field(
        default=None,
        description=(
            "IMDB's standard line on how data are obtained, e.g. 'Data are collected "
            "directly from survey respondents.' or 'Data are extracted from administrative "
            "files.'"
        ),
    )
    survey_design: str | None = Field(
        default=None,
        description=(
            "IMDB's standard line on the design, e.g. 'This is a sample survey with a "
            "cross-sectional design.' or 'This survey is a census ...'."
        ),
    )
    sample_size: list[str] = Field(
        default_factory=list,
        description=(
            "Sentences of the Sampling section that give a number for the sample (e.g. "
            "households per month, 1 in 4 dwellings). Picked by a text rule: read "
            "methodology.sampling for the context."
        ),
    )
    methodology: SurveyMethodology = Field(default_factory=SurveyMethodology)
    trimmed_sections: list[str] = Field(
        default_factory=list,
        description=(
            "Sections shortened to keep the result small (they end with '[...]'); ask for "
            "them with section=[...] to get their full text."
        ),
    )
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
