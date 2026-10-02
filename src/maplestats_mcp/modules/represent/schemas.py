from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Level = Literal["federal", "provincial", "municipal"]


class Office(BaseModel):
    type: str | None = Field(default=None, description="e.g. constituency or legislature.")
    postal: str | None = None
    tel: str | None = None
    fax: str | None = None


class Representative(BaseModel):
    name: str
    first_name: str | None = None
    last_name: str | None = None
    elected_office: str | None = Field(default=None, description="MP, MLA, Mayor, Councillor...")
    district_name: str | None = None
    party_name: str | None = None
    level: Level | None = Field(
        default=None, description="Derived from the representative set, not given by the source."
    )
    representative_set: str | None = Field(
        default=None, description="Set slug, e.g. house-of-commons."
    )
    representative_set_name: str | None = None
    boundary: str | None = Field(
        default=None, description="Path of the boundary this person represents."
    )
    email: str | None = None
    url: str | None = Field(default=None, description="Official page of the representative.")
    personal_url: str | None = None
    photo_url: str | None = None
    source_url: str | None = Field(
        default=None, description="Official page the record was scraped from; check it."
    )
    gender: str | None = None
    offices: list[Office] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class BoundaryRef(BaseModel):
    name: str
    boundary_set: str = Field(description="Boundary set slug.")
    boundary_set_name: str | None = None
    external_id: str | None = Field(default=None, description="Machine id, when the set has one.")
    path: str = Field(description="Represent path of the boundary.")
    matched_by: Literal["centroid", "concordance", "point"] = Field(
        description="How it matched: the postal code's centre point, the official "
        "postal code concordance, or an exact latitude/longitude."
    )


class BoundarySetInfo(BaseModel):
    slug: str
    name: str | None = None
    domain: str | None = Field(default=None, description="e.g. Canada, Alberta, 'Edmonton, AB'.")
    authority: str | None = None
    licence_url: str | None = None
    source_url: str | None = None
    last_updated: date | None = None
    age_years: float | None = Field(
        default=None, description="Years between last_updated and the query date."
    )
    possibly_stale: bool | None = Field(
        default=None, description="True when last_updated is more than 5 years old."
    )
    start_date: date | None = None
    end_date: date | None = None
    notes: str | None = None
    detail_loaded: bool = Field(
        default=True,
        description="False when only the list fields (name, domain) were read.",
    )


class PostcodeLookup(BaseModel):
    postcode: str
    city: str | None = None
    province: str | None = None
    centroid_latitude: float | None = None
    centroid_longitude: float | None = None
    boundaries: list[BoundaryRef]
    representatives: list[Representative]
    boundary_sets: list[BoundarySetInfo] = Field(
        description="Licence and last-updated date of each boundary set that matched."
    )
    oldest_boundary_update: date | None = None
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class PointLookup(BaseModel):
    latitude: float
    longitude: float
    boundaries: list[BoundaryRef]
    representatives: list[Representative]
    boundaries_total: int
    representatives_total: int
    boundary_sets: list[BoundarySetInfo]
    oldest_boundary_update: date | None = None
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class RepresentativeSearchResult(BaseModel):
    representatives: list[Representative]
    total_count: int
    offset: int
    limit: int
    has_more: bool
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class BoundarySetList(BaseModel):
    sets: list[BoundarySetInfo]
    total_count: int
    offset: int
    limit: int
    has_more: bool
    oldest_last_updated: date | None = None
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance


class RepresentativeSetInfo(BaseModel):
    slug: str
    name: str
    level: Level
    boundary_set: str | None = Field(
        default=None, description="Slug of the boundary set its districts come from."
    )
    data_url: str | None = Field(default=None, description="Scraper feed the records come from.")


class RepresentativeSetList(BaseModel):
    sets: list[RepresentativeSetInfo]
    total_count: int
    notes: list[str] = Field(default_factory=list)
    provenance: Provenance
