"""Typed responses for Borealis IVT search."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class IvtFile(BaseModel):
    file_id: str
    file_name: str
    dataset: str
    dataset_url: str
    download_url: str
    size_bytes: int | None = None
    restricted: bool = Field(description="True when the file needs a Borealis login.")
    published: str | None = None
    other_formats: list[str] = Field(
        default_factory=list,
        description="Other data files in the same dataset (e.g. a CSV twin readable without canivt).",
    )
    r_snippet: str = Field(description="R code that downloads the file and reads it with canivt.")


class IvtSearchResult(BaseModel):
    files: list[IvtFile] = Field(default_factory=list)
    returned_count: int
    datasets_matched: int = Field(description="Datasets whose title or description matched.")
    query: str
    provenance: Provenance


class OdesiDataset(BaseModel):
    title: str
    persistent_id: str = Field(
        description="DOI as 'doi:10.5683/SP3/...', for the other odesi tools."
    )
    url: str
    collection: str | None = Field(
        default=None, description="Borealis sub-collection holding it (e.g. a CORA poll series)."
    )
    description: str | None = Field(default=None, description="Abstract, shortened.")
    keywords: list[str] = Field(default_factory=list)
    producers: list[str] = Field(default_factory=list)
    file_count: int | None = None
    published: str | None = None


class OdesiSearchResult(BaseModel):
    query: str
    collection: str
    datasets: list[OdesiDataset] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    access_note: str
    provenance: Provenance


class OdesiFile(BaseModel):
    file_id: str
    name: str
    content_type: str | None = None
    size_bytes: int | None = None
    download_url: str


class OdesiDatasetDetail(BaseModel):
    title: str
    persistent_id: str
    url: str
    alt_titles: list[str] = Field(default_factory=list)
    series: str | None = None
    producers: list[str] = Field(default_factory=list)
    version: str | None = None
    abstract: str | None = None
    keywords: list[str] = Field(default_factory=list)
    topic: str | None = None
    time_period: str | None = None
    geographic_coverage: str | None = None
    analysis_unit: str | None = None
    universe: str | None = None
    sampling: str | None = None
    collection_mode: str | None = None
    terms_of_use: str | None = Field(
        default=None, description="Restriction statement and licence from the DDI record."
    )
    citation: str | None = None
    public_files: list[OdesiFile] = Field(
        default_factory=list, description="Files anyone can download without a login."
    )
    restricted_file_names: list[str] = Field(
        default_factory=list,
        description="Names only. They need a login at a DLI-member institution; no link is given.",
    )
    access_summary: str
    provenance: Provenance


class OdesiVariable(BaseModel):
    name: str
    label: str | None = None
    file_name: str | None = None
    categories: int = Field(default=0, description="Number of coded categories listed.")


class OdesiVariableResult(BaseModel):
    persistent_id: str
    query: str
    variables: list[OdesiVariable] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    total_variables: int
    note: str | None = Field(
        default=None, description="Set when the dataset has no variable-level DDI."
    )
    provenance: Provenance
