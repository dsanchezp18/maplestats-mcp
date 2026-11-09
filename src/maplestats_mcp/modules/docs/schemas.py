"""Typed results of the docs_ tools."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class DocsPage(BaseModel):
    """One docs:// page the server serves."""

    uri: str = Field(description="Pass to docs_read_resource as `uri`.")
    description: str | None = None


class DocsPageList(BaseModel):
    pages: list[DocsPage]
    total_count: int
    provenance: Provenance


class DocsPageText(BaseModel):
    uri: str
    text: str = Field(description="The page, as the docs:// resource serves it (Markdown).")
    provenance: Provenance
