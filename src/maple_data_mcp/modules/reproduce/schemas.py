"""Typed response for reproduce_code."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance

Language = Literal["r", "python", "stata", "julia"]


class ReproductionCode(BaseModel):
    tool: str
    language: Language
    code: str
    source_url: str = Field(description="The URL the code fetches.")
    method: str = Field(
        description="How the request was rebuilt: from the tool's arguments (exact) or from "
        "the result's provenance URL (may omit filters)."
    )
    packages: list[str] = Field(description="Packages the code needs.")
    notes: list[str]
    provenance: Provenance
