"""Typed response for reproduce_code."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance

Language = Literal["r", "python", "stata", "julia"]
LanguageChoice = Literal["all", "r", "python", "stata", "julia"]


class Script(BaseModel):
    language: Language
    code: str = Field(description="Retrieval, then source-specific and standard cleaning.")
    packages: list[str] = Field(description="Packages the code needs.")


class ReproductionCode(BaseModel):
    tool: str
    scripts: list[Script] = Field(description="One script per language that can fetch this source.")
    source_url: str = Field(description="The URL the scripts fetch.")
    method: str = Field(
        description="How the request was rebuilt: from the tool's arguments (exact) or from "
        "the result's provenance URL (may omit filters)."
    )
    notes: list[str]
    provenance: Provenance
