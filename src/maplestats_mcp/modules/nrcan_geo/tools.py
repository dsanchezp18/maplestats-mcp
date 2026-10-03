"""MCP tools for NRCan's Geolocator and Canadian Geographical Names Database."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.nrcan_geo import client, constants
from maplestats_mcp.modules.nrcan_geo.schemas import LocationResult, PlaceNameResult

Lang = Literal["en", "fr"]


@tool
async def nrcan_geo_locate(
    query: str, limit: int = constants.LIMIT_DEFAULT, lang: Lang = "en"
) -> LocationResult:
    """Geocode a Canadian place, street address, or postal code to coordinates (NRCan Geolocator).

    Use for: turning "111 Wellington St Ottawa", "K1A 0A9", or
    "Parliament Hill" into latitude/longitude, province, and bounding
    box, e.g. before a spatial query elsewhere. `lang="fr"` returns
    French names and categories. The Geolocator matches loosely and has
    no relevance score: a query it cannot match still returns nearby
    spellings or unrelated places, so check the returned name.
    Keywords: geocode, geolocation, address lookup, postal code, FSA,
    coordinates, latitude longitude, NRCan, geo.ca, place search.
    Mots-clés : géocodage, géolocalisation, adresse, code postal, RTA,
    coordonnées, latitude longitude, RNCan, recherche de lieu.
    """
    return await client.locate(query, limit=limit, lang=lang)


@tool
async def nrcan_geo_search_names(
    query: str | None = None,
    province: str | None = None,
    feature_type: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    bbox: list[float] | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: Lang = "en",
) -> PlaceNameResult:
    """Search the Canadian Geographical Names Database for official place names.

    Use for: official names and locations of cities, towns, lakes,
    rivers, mountains, parks and other features. Combine `query` (name
    text), `province` ("AB" or SGC code "48"), `feature_type` (e.g.
    "CITY", "TOWN", "LAKE", "RIV", "MTN"), a point with `radius_km`
    (whole kilometres; default 10), or
    `bbox` [west, south, east, north]. `lang="fr"` returns French feature
    types. `province` in results is the SGC code ("48" for Alberta).
    Keywords: place names, toponymy, gazetteer, geographical names, lake,
    river, mountain, official name, NRCan, CGNDB.
    Mots-clés : noms géographiques, toponymie, répertoire toponymique,
    lac, rivière, montagne, nom officiel, RNCan, BDTC.
    """
    return await client.search_names(
        query,
        province=province,
        feature_type=feature_type,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        bbox=bbox,
        limit=limit,
        lang=lang,
    )
