"""Typed responses for archived (pre-2021) Census Profile bulk downloads."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class GeographyLevelList(BaseModel):
    year: int
    levels: list[str] = Field(default_factory=list)
    formats: list[str] = Field(default_factory=list)
    provenance: Provenance


class DownloadLink(BaseModel):
    year: int
    level: str
    file_format: str
    language: str = "en"
    url: str
    provenance: Provenance
