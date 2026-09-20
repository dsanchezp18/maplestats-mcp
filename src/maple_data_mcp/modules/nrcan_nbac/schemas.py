"""Typed responses for NRCan's National Burned Area Composite (NBAC)."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class FireRecord(BaseModel):
    """One mapped fire event/polygon from NBAC.

    Field meanings confirmed live against a real feature: `hs_sdate`/
    `hs_edate` are the "hotspot" (satellite-detection) start/end dates,
    `ag_sdate`/`ag_edate` are the "agency" (reported-by-fire-agency)
    start/end dates -- NBAC uses whichever pair is available per fire,
    so both can be present, and either pair can be null. `poly_ha` is
    the raw mapped polygon area; `adj_ha` is NBAC's own adjusted burned
    area (its recommended figure for area-burned analysis), which can
    differ from `poly_ha` when `adj_flag` records a correction.
    """

    year: int
    fire_id: int = Field(description="`nfireid`: fire event id, unique within a year, not overall.")
    admin_area: str | None = Field(default=None, description="Province/territory code, e.g. 'BC'.")
    burn_source: str | None = Field(default=None, description="`basrc`: mapping data source.")
    fire_cause: str | None = Field(default=None, description="`firecaus`: e.g. 'Natural', 'Human'.")
    hotspot_start_date: date | None = None
    hotspot_end_date: date | None = None
    agency_start_date: date | None = None
    agency_end_date: date | None = None
    capture_date: date | None = Field(default=None, description="`capdate`: when this was mapped.")
    polygon_area_ha: float | None = None
    adjusted_area_ha: float | None = None
    adjustment_flag: str | None = None
    national_park: str | None = None
    prescribed: str | None = Field(
        default=None,
        description="Non-null when this was a prescribed (planned) burn, not wildfire.",
    )
    version: str | None = None
    geometry: dict[str, Any] | None = Field(
        default=None, description="GeoJSON MultiPolygon, only present when include_geometry=True."
    )


class FireQueryResult(BaseModel):
    fires: list[FireRecord]
    returned_count: int
    total_matched: int
    limit: int
    offset: int
    cql_filter: str | None = None
    provenance: Provenance
