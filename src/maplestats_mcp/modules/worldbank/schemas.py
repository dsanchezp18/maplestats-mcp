"""Typed response models for the World Bank module.

Field names follow the API's JSON as read live on 2026-10-03: indicator
entries carry `id`, `name`, `unit` (always "" in WDI), `sourceNote`,
`sourceOrganization` and `topics` (a list of {id, value} with trailing
spaces in some values, empty for 134 of 1,498 indicators); data rows carry
`countryiso3code`, `country`, `date` (a year as a string), `value` (null for
a year with no data) and `decimal`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class Topic(BaseModel):
    id: str
    name: str


class TopicList(BaseModel):
    topics: list[Topic]
    provenance: Provenance


class IndicatorSummary(BaseModel):
    id: str = Field(description="WDI indicator code, e.g. NY.GDP.MKTP.KD.ZG.")
    name: str
    topics: list[str] = Field(default_factory=list)


class IndicatorSearchResult(BaseModel):
    query: str | None
    topic: str | None
    indicators: list[IndicatorSummary]
    total_matches: int
    provenance: Provenance


class IndicatorDetail(BaseModel):
    id: str
    name: str
    definition: str = Field(description="The World Bank's source note (English only upstream).")
    source_organization: str
    topics: list[str] = Field(default_factory=list)
    provenance: Provenance


class Observation(BaseModel):
    year: int
    value: float


class CountrySeries(BaseModel):
    country_code: str = Field(description="ISO3 code, or OED for the OECD members aggregate.")
    country_name: str
    observations: list[Observation] = Field(description="Years with a value, oldest first.")
    latest_year: int | None = None
    latest_value: float | None = None


class CanadaSeriesResult(BaseModel):
    indicator_id: str
    indicator_name: str
    countries: list[CountrySeries] = Field(description="Canada first, then the comparisons.")
    canada_rank: int | None = Field(
        default=None,
        description=(
            "Canada's rank (1 = highest value) among the compared countries in "
            "rank_year, the latest of Canada's years that the most of them report; "
            "the OECD aggregate is not ranked. None without comparisons."
        ),
    )
    rank_year: int | None = None
    ranked_countries: int | None = None
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
