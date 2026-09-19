"""Typed response models for the MSC GeoMet-OGC-API module.

Confirmed live this session against https://api.weather.gc.ca: every
collection (weather-alerts, climate-stations, hydrometric-realtime,
swob-realtime, aqhi-observations-realtime, and ~95 others) follows the
same OGC API - Features shapes modelled below — a single
/collections?f=json inventory, one /collections/{id}?f=json detail
document per collection (title/description/keywords/extent/itemType/
links), a /collections/{id}/queryables?f=json property schema, and a
/collections/{id}/items?f=json GeoJSON FeatureCollection for actual
data. What is NOT modelled here on purpose: per-collection item
*properties*. A feature's properties dict is genuinely different for
every collection — weather-alerts carries alert_code/alert_text_en/
province; climate-stations carries STN_ID/LATITUDE/LONGITUDE (the
latter two as integers scaled by 1e7, not decimal degrees — confirmed
live, see client.py); swob-realtime carries ~150 raw meteorological
variables named in WMO-style shorthand, each as a -value/-uom/-qa
triplet. Modelling ~100 distinct property schemas as separate typed
models would not be proportionate to this module's scope (see
AGENTS.md/PROJECT_GUIDE.md's rule against bespoke tools where a common
discovery/resource/metadata abstraction is sufficient) — Feature.
properties is deliberately dict[str, Any], the same choice already
made for modules/arcgis_*'s FeatureQueryResult.rows.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from maple_data_mcp.shared.models import Provenance


class CollectionSummary(BaseModel):
    """One entry from /collections?f=json."""

    id: str
    title: str
    description: str
    keywords: list[str] = Field(default_factory=list)
    item_type: str


class CollectionList(BaseModel):
    collections: list[CollectionSummary]
    total_count: int
    provenance: Provenance


class Queryable(BaseModel):
    """One entry from /collections/{id}/queryables?f=json's "properties" object."""

    name: str
    type: str | None = None


class CollectionDetail(BaseModel):
    id: str
    title: str
    description: str
    keywords: list[str] = Field(default_factory=list)
    item_type: str
    bbox: list[float] | None = Field(
        default=None, description="[west, south, east, north] in CRS84 (WGS84 lon/lat)."
    )
    queryables: list[Queryable]
    canonical_url: str | None = Field(
        default=None, description="Human-readable documentation/landing page for this collection."
    )
    download_url: str | None = Field(
        default=None, description="Bulk-download link, when this collection publishes one."
    )
    provenance: Provenance


class Feature(BaseModel):
    """One GeoJSON feature from a collection's /items response.

    `properties` is intentionally untyped — see this module's docstring.
    """

    id: str | None = None
    geometry: dict[str, Any] | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class ItemsResult(BaseModel):
    collection_id: str
    items: list[Feature]
    number_matched: int = Field(
        description="Total rows matching the filter, before limit/offset pagination."
    )
    number_returned: int
    limit: int
    offset: int
    provenance: Provenance
