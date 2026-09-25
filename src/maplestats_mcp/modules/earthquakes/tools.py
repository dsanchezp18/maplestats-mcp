"""MCP tools for the Earthquakes Canada event catalogue."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.earthquakes import client, constants
from maplestats_mcp.modules.earthquakes.schemas import EarthquakeSearchResult
from maplestats_mcp.shared.errors import InvalidInput


@tool
async def earthquakes_search(
    start: str | None = None,
    end: str | None = None,
    min_magnitude: float | None = None,
    max_magnitude: float | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    bbox: list[float] | None = None,
    event_id: str | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: Literal["en", "fr"] = "en",
) -> EarthquakeSearchResult:
    """Search Earthquakes Canada (NRCan) for earthquakes in and near Canada.

    Use for: recent or historical earthquakes by date range (YYYY-MM-DD,
    default the last 30 days), magnitude, distance from a point
    (latitude, longitude, radius_km, e.g. near Vancouver), or a
    [west, south, east, north] bbox. Pass event_id alone for one event.
    Results are most recent first, with time (UTC), location, depth
    and magnitude. Use nrcan_geo_locate to turn a place into coordinates.
    Keywords: earthquake, seismic event, tremor, quake, magnitude,
    epicentre, Earthquakes Canada, NRCan, seismology.
    Mots-clés : séisme, tremblement de terre, secousse, magnitude,
    épicentre, Séismes Canada, RNCan, sismologie.
    """
    if bbox is not None and len(bbox) != 4:
        raise InvalidInput("bbox must have 4 numbers: west, south, east, north.")
    return await client.search(
        start=start,
        end=end,
        min_magnitude=min_magnitude,
        max_magnitude=max_magnitude,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        bbox=(bbox[0], bbox[1], bbox[2], bbox[3]) if bbox else None,
        event_id=event_id,
        limit=limit,
        lang=lang,
    )
