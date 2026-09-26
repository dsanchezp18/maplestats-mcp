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
