"""Typed response models for the StatCan RDaaS submodule.

Every field name below is verified against live RDaaS responses fetched
this session, including categories/detailed, exclusions, indexes,
index-entry, and term-exclusion — all five initially looked
unreachable (HTTP 200, zero-byte body) against the NAICS classification
id (MJRdRiFsfmJAprtT). Retrying against smaller/other classifications
(a 3-code abbreviations list, an 840-code NOC variant) proved the
endpoints work correctly and return rich data; NAICS specifically
returns a genuine empty body for these two sub-resources — see
client.py's docstring on `_empty_body_quirk` for how that's handled.
`indexes`/`exclusions` worked against NAICS directly (19,130 and a
large exclusion set respectively).

Several fields differ from the OpenAPI spec's declared schema (checked
directly against the live JSON, not just the spec): term-exclusion's
"code" field is actually named "source" and is a URL, not a bare code;
index entries carry a "primaryTerm" field the spec does not list at
all. Field names below follow the live response, not the spec, where
they disagree.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class ClassificationSummary(BaseModel):
    id: str = Field(description="RDaaS resource URL, e.g. .../classification/MJRdRiFsfmJAprtT")
    name: str
    abbreviation: str | None = None
    audience: str
    status: str
    version_number: str | None = None
    valid_from: str | None = None
    last_updated: str | None = None
    code_count: int | None = None
    level_count: int | None = None


class SearchFacets(BaseModel):
    status: dict[str, int] = Field(default_factory=dict)
    audience: dict[str, int] = Field(default_factory=dict)


class ClassificationSearchResult(BaseModel):
    results: list[ClassificationSummary]
    found: int
    start: int
    limit: int
    facets: SearchFacets
    provenance: Provenance


class ClassificationLevel(BaseModel):
    id: str
    level_depth: int
    name: str
    code_count: int


class ClassificationDetail(BaseModel):
    id: str
    name: str
    abbreviation: str | None = None
    audience: str
    status: str
    standard_status: str | None = None
    is_harmonized: bool | None = None
    catalogue_number: str | None = None
    version_name: str | None = None
    valid_from: str | None = None
    release_date: str | None = None
    last_updated: str | None = None
    background: str | None = None
    related_classification_ids: list[str] = Field(default_factory=list)
    levels: list[ClassificationLevel] = Field(default_factory=list)
    provenance: Provenance


class ConcordanceSummary(BaseModel):
    id: str
    name: str
    version_number: str | None = None
    audience: str
    status: str
    last_updated: str | None = None
    source_id: str
    source_name: str
    source_version_number: str | None = None
    target_id: str
    target_name: str
    target_version_number: str | None = None


class ConcordanceSearchResult(BaseModel):
    results: list[ConcordanceSummary]
    found: int
    start: int
    limit: int
    facets: SearchFacets
    provenance: Provenance


class ConcordanceDetail(BaseModel):
    id: str
    name: str
    version_number: str | None = None
    audience: str
    status: str
    source_id: str
    source_name: str
    target_id: str
    target_name: str
    provenance: Provenance


class CodeMapEntry(BaseModel):
    id: str
    map_type: str
    source_code: str
    source_descriptor: str
    source_since_version: str | None = None
    target_code: str
    target_descriptor: str
    target_since_version: str | None = None


class CodeMapList(BaseModel):
    concordance_id: str
    maps: list[CodeMapEntry]
    provenance: Provenance


class FilterOption(BaseModel):
    parameter: str
    values: list[str]


class SearchFilters(BaseModel):
    """Valid filter values for the `audience`/`status` search parameters.

    Real shape is a list of {parameter, values} objects — verified
    live; not a dict keyed by parameter name as might be assumed.
    """

    filters: list[FilterOption]
    provenance: Provenance


class ClassificationCategory(BaseModel):
    """The most detailed (leaf) categories of a classification — verified
    against a live 840-code classification's response."""

    id: str
    code: str
    descriptor: str
    definition: str | None = None
    level_depth: int | None = None
    main_duties: list[str] = Field(default_factory=list)
    employment_requirements: list[str] = Field(default_factory=list)


class ClassificationCategoriesDetailed(BaseModel):
    classification_id: str
    categories: list[ClassificationCategory]
    provenance: Provenance


class ClassificationExclusion(BaseModel):
    """A term excluded from one code and pointed at its correct code
    instead — verified against a live response. Note the live field is
    `source`/`target` (both resource URLs), not `code` as the OpenAPI
    spec's schema names it."""

    id: str
    source_id: str
    source_code_value: str
    term: str
    target_id: str
    target_code_value: str


class ClassificationExclusions(BaseModel):
    classification_id: str
    exclusions: list[ClassificationExclusion]
    provenance: Provenance


class ClassificationIndexEntry(BaseModel):
    """One index entry (an alternate term mapped to a code) — verified
    against a live response. `index_id` is a small integer, not a URL
    fragment; it's what /indexes/entry/{indexId} expects as its path
    parameter."""

    id: str
    index_id: int
    primary_term: str | None = None
    other_examples: list[str] = Field(default_factory=list)
    illustrative_examples: list[str] = Field(default_factory=list)
    inclusions: list[str] = Field(default_factory=list)
    internal_examples: list[str] = Field(default_factory=list)
    index_code_id: str | None = None
    index_code_value: str | None = None
    index_code_descriptor: str | None = None


class ClassificationIndexes(BaseModel):
    classification_id: str
    entries: list[ClassificationIndexEntry]
    provenance: Provenance


class TermExclusion(BaseModel):
    """Same shape as ClassificationExclusion — verified live via both
    /classification/{id}/exclusions and the standalone
    /termexclusion/{id} endpoint, which return identical fields."""

    id: str
    source_id: str
    source_code_value: str
    term: str
    target_id: str
    target_code_value: str
    provenance: Provenance
