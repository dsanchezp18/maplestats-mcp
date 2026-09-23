"""MCP tools for DFO/CHS tides and water levels (IWLS API)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.dfo_iwls import client, constants
from maple_data_mcp.modules.dfo_iwls.schemas import (
    Resolution,
    StationDetail,
    StationSearchResult,
    WaterLevelSeries,
)

Lang = Literal["en", "fr"]


@tool
async def dfo_iwls_search_stations(
    query: str = "",
    operating_only: bool = True,
    series_code: str | None = None,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> StationSearchResult:
    """Search Canada's ~1,575 tide and water-level stations (Fisheries and Oceans Canada).

    Use for: finding a station's five-digit code (e.g. "07120" Victoria
    Harbour) before fetching tides or water levels. `query` matches the
    station name, alternative name, or exact code; `series_code`
    narrows to stations publishing that series ("wlo" observed, "wlp"
    predicted, "wlp-hilo" high/low tides). `lang="fr"` returns French
    series names.
    Keywords: DFO, Canadian Hydrographic Service, tide station, tides,
    water level, harbour, port, coast, marine, tide gauge.
    Mots-clés : MPO, Pêches et Océans, Service hydrographique du Canada,
    station marégraphique, marées, niveau d'eau, port, côte, marégraphe.
    """
    return await client.search_stations(
        query, operating_only=operating_only, series_code=series_code, limit=limit, lang=lang
    )


@tool
async def dfo_iwls_get_station(station_code: str, lang: Lang = "en") -> StationDetail:
    """Get one DFO tide station's details: location, region, datums, and available series.

    Use for: checking whether a station is tidal or a tide-table
    reference port and converting its chart-datum levels to CGVD2013 or
    CGVD28 with the datum offsets.
    Keywords: DFO, tide station, chart datum, CGVD2013, geodetic datum,
    station metadata, hydrographic, reference port.
    Mots-clés : MPO, station marégraphique, zéro des cartes, CGVD2013,
    niveau de référence géodésique, métadonnées, port de référence.
    """
    return await client.get_station(station_code, lang)


@tool
async def dfo_iwls_get_water_levels(
    station_code: str,
    series_code: str = "wlp-hilo",
    start: str | None = None,
    end: str | None = None,
    resolution: Resolution | None = None,
    lang: Lang = "en",
) -> WaterLevelSeries:
    """Get tide times, predicted water levels, or observed water levels for one station.

    Use for: high and low tide times ("wlp-hilo", the default),
    predicted levels ("wlp"), or official observed levels ("wlo") in
    metres above chart datum. `start`/`end` are ISO dates or UTC
    datetimes (default: now to +24 h); the window is capped at 7 days.
    Set `resolution` (e.g. "SIXTY_MINUTES") to thin minute-level
    series; it is ignored for high/low tides.
    Keywords: tides, tide table, high tide, low tide, water level,
    prediction, observed, DFO, harbour, marine forecast.
    Mots-clés : marées, table des marées, pleine mer, basse mer, niveau
    d'eau, prédiction, observé, MPO, port, prévision maritime.
    """
    return await client.get_water_levels(
        station_code, series_code, start=start, end=end, resolution=resolution, lang=lang
    )
