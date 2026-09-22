"""Typed responses for the BC Geographic Warehouse (BCGW) module."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class WildfireRecord(BaseModel):
    """One current fire perimeter/status record from BCGW.

    Confirmed live: there is no fire-centre/region field on this layer,
    despite that being a natural-seeming filter -- do not assume one
    exists.
    """

    fire_number: str
    fire_year: int
    size_hectares: float | None = None
    status: str | None = Field(
        default=None, description="e.g. 'Out of Control', 'Being Held', 'Out'."
    )
    source: str | None = Field(default=None, description="How the perimeter was mapped.")
    track_date: date | None = None
    load_date: date | None = None
    url: str | None = Field(
        default=None, description="Link to the BC Wildfire Service incident page."
    )
    geometry: dict[str, Any] | None = Field(
        default=None, description="GeoJSON polygon, only present when include_geometry=True."
    )


class WildfireQueryResult(BaseModel):
    wildfires: list[WildfireRecord]
    returned_count: int
    total_matched: int
    limit: int
    offset: int
    provenance: Provenance


class MiningTenureRecord(BaseModel):
    """One acquired mineral/placer tenure (claim) record from BCGW."""

    tenure_number_id: int
    claim_name: str | None = None
    tenure_type_code: str | None = Field(default=None, description="'M' mineral or 'P' placer.")
    tenure_type_description: str | None = None
    tenure_sub_type_description: str | None = None
    title_type_description: str | None = None
    issue_date: date | None = None
    good_to_date: date | None = None
    area_hectares: float | None = None
    owner_name: str | None = None
    percent_ownership: float | None = None
    number_of_owners: int | None = None
    statement_of_work_event_count: int | None = None
    termination_date: date | None = None
    geometry: dict[str, Any] | None = Field(
        default=None, description="GeoJSON polygon, only present when include_geometry=True."
    )


class MiningTenureQueryResult(BaseModel):
    tenures: list[MiningTenureRecord]
    returned_count: int
    total_matched: int
    limit: int
    offset: int
    provenance: Provenance


class LayerQueryResult(BaseModel):
    """Generic result for any BCGW layer -- rows kept as loosely-typed
    dicts since field names/types vary by layer (same idiom as
    ckan_federal's DatastoreSearchResult.records)."""

    type_name: str
    records: list[dict[str, object]]
    returned_count: int
    total_matched: int
    limit: int
    offset: int
    cql_filter: str | None = None
    provenance: Provenance
