"""The base response contract every module's typed models build on.

A lightweight source/url envelope combined with a richer provenance
vocabulary (as-of date, freshness, coverage, limits, schema name),
so every result documents where it came from and how complete it is.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    """Where a result came from and how fresh/complete it is.

    Embedded in every module's response models (composition, not
    inheritance) so a tool can return `MyResult(provenance=..., ...)`
    without fighting Pydantic's model-inheritance rules for extra fields.
    """

    source: str = Field(description="Short name of the upstream API, e.g. 'statcan-wds'.")
    url: str = Field(description="The exact upstream URL this result was fetched from.")
    queried_at: datetime = Field(description="When MapleStats made the upstream request.")
    as_of: datetime | None = Field(
        default=None,
        description="The upstream data's own reference/release date, when the source states one.",
    )
    freshness: str | None = Field(
        default=None,
        description="Update cadence in plain language, e.g. 'daily at 8:30am ET'.",
    )
    coverage: str | None = Field(
        default=None,
        description="What the result does NOT include, e.g. 'first 100 of 3,204 cubes'.",
    )
    limits: str | None = Field(
        default=None,
        description="Any cap or truncation applied, e.g. 'rows capped at 500'.",
    )
    cached: bool = Field(description="Whether this result was served from MapleStats's cache.")
    schema_name: str = Field(
        description="Name of this result's schema, e.g. 'statcan.CubeSummary'."
    )
    reproduce: str = Field(
        default=(
            "For R, Python, Stata and Julia scripts that fetch and clean this data, call "
            "reproduce_code with this tool's name and arguments."
        ),
        description="How to get retrieval and cleaning code for this result.",
    )


class ErrorPayload(BaseModel):
    """The shape carried by a raised error before it becomes an MCP isError result."""

    code: str
    message: str
    lang: str = "en"
    extra: dict[str, Any] = Field(default_factory=dict)
