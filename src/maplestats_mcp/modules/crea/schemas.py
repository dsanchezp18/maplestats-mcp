from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class CreaPage(BaseModel):
    key: str = Field(description="hpi_tool, national_statistics, quarterly_forecasts, ...")
    title: str
    url: str


class OpenAlternative(BaseModel):
    name: str
    measure: str = Field(description="What it measures, and how it differs from the MLS® HPI.")
    tools: list[str] = Field(description="MapleStats tools that return it.")
    table_id: str | None = None


class CreaHpiLinks(BaseModel):
    release_month: str = Field(description="Release month looked for, YYYY-MM.")
    zip_url: str | None = Field(
        description="The MLS® HPI monthly zip, when a HEAD request confirmed it; never read."
    )
    zip_confirmed: bool
    zip_last_modified: str | None = None
    zip_size_bytes: int | None = None
    download_from: str = Field(description="Where to download the data yourself.")
    pages: list[CreaPage]
    release_timing: str
    attribution: str
    terms_summary: list[str]
    open_alternatives: list[OpenAlternative]
    provenance: Provenance
