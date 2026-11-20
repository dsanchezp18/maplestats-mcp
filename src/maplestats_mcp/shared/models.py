"""The base response contract every module's typed models build on.

A lightweight source/url envelope combined with a richer provenance
vocabulary (as-of date, freshness, coverage, limits, schema name),
so every result documents where it came from and how complete it is.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Whether the publisher's terms let anyone reuse the data commercially without
# asking. "not_allowed" covers both non-commercial-only terms and terms that need
# written permission first; "varies" is a platform whose datasets or feeds each
# carry their own licence; "unknown" is terms that are silent, conflicting or not
# found. Set from shared/licences.COMMERCIAL_USE, never parsed from the text.
CommercialUse = Literal["allowed", "not_allowed", "varies", "unknown"]


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
    lang: str | None = Field(
        default=None,
        description=(
            "The language MapleStats wrote this result's own text in ('en' or 'fr'): notes, "
            "limits, caveats, labels. Values and the publisher's own text are as published."
        ),
    )
    schema_name: str = Field(
        description="Name of this result's schema, e.g. 'statcan.CubeSummary'."
    )
    licence: str | None = Field(
        default=None,
        description=(
            "Licence and attribution the upstream publisher requires, when it has one "
            "(set for every Statistics Canada result)."
        ),
    )
    commercial_use: CommercialUse | None = Field(
        default=None,
        description=(
            "Whether the licence allows commercial reuse without asking the publisher: "
            "'allowed', 'not_allowed' (non-commercial use only, or written permission needed), "
            "'varies' (each dataset or feed has its own licence: read licence) or 'unknown' "
            "(terms silent, conflicting or not found). Null when no licence applies. The "
            "conditions themselves are in licence."
        ),
    )
    caveats: list[str] = Field(
        default_factory=list,
        description=(
            "Fitness-for-use cautions for this table or source, from MapleStats' rules "
            "(docs://planner/fitness-rules)."
        ),
    )
    substituted_for: str | None = Field(
        default=None,
        # Left out of the output while null, so an ordinary result is byte for byte what it
        # was before this field existed.
        exclude_if=lambda value: value is None,
        description=(
            "Set only when this result came from another official source because the tool's "
            "own one was blocked or paused (for example 'wds' for a Statistics Canada Web Data "
            "Service tool answered from the Bank of Canada, the CCEI SDMX space or the Alberta "
            "dashboard). `source` and `url` then name the host that answered and `caveats` say "
            "why, in the call's language. Null for every ordinary result."
        ),
    )
    reproduce: str = Field(
        default="For scripts, call reproduce_code with this tool's name and arguments.",
        description="How to get retrieval and cleaning code for this result.",
    )


# ---- SQL over an SDMX dataset's slice (shared/sdmx_query.py) ----

SdmxQueryCell = str | int | float | bool | None


class SdmxQueryResult(BaseModel):
    """The result of one read-only SQL query over a slice of an SDMX dataset."""

    sql: str = Field(description="The SQL as run against the table `obs`.")
    columns: list[str] = Field(description="Result column names, in order.")
    column_types: list[str] = Field(description="DuckDB type of each result column.")
    rows: list[list[SdmxQueryCell]] = Field(
        description="Result rows (dates as YYYY-MM-DD), at most the row cap in provenance.limits."
    )
    row_count: int = Field(description="Rows in `rows`.")
    truncated: bool = Field(description="True when the query returned more rows than the cap.")
    input_rows: int = Field(description="Observations of the slice loaded into `obs`.")
    dataset: str
    dataset_title: str
    citation: str = Field(description="Quote it with the result, with the periods used.")
    dimension_columns: dict[str, str] = Field(
        description="Each dimension and the `obs` column holding its codes; the column "
        "with the same name plus '_label' holds their labels."
    )
    filters: dict[str, list[str]] = Field(
        default_factory=dict, description="The codes kept per dimension (all where absent)."
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="What the query does with the numbers that is easy to misread, measured "
        "on the data: say these with the result.",
    )
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
