"""MCP tools for the MSC GeoMet-OGC-API (Environment and Climate Change Canada).

Every tool returns a typed Pydantic model (see schemas.py) - FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.

`lang` is passed to GeoMet as its `lang` query parameter, which sets the
language of collection titles and descriptions (confirmed live
2026-10-03). Item properties are not translated by it: bilingual content
comes as separate `_en`/`_fr` properties in every response (e.g.
weather-alerts' alert_text_en/alert_text_fr). With lang="fr" the errors,
notes and provenance text this module writes are in French, and a note
names the French (`_fr`) properties present in the returned rows.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.eccc import client
from maplestats_mcp.modules.eccc.schemas import CollectionDetail, CollectionList, ItemsResult

Lang = Literal["en", "fr"]


@tool
async def eccc_search_collections(query: str, limit: int = 25, lang: Lang = "en") -> CollectionList:
    """Search MSC GeoMet's ~100 weather/climate/water OGC API collections by keyword.

    Use for: finding a collection id when you only know a topic - e.g.
    "alert", "aqhi", "climate normal", "hydrometric", "swob", "marine",
    "snowfall". The query matches English and French text ("alerte"
    finds weather-alerts); lang="fr" returns French titles. Read
    docs://eccc/well-known-collections first - it already lists the
    collection ids that matter most, with example filters for each.
    Keywords: environment canada, eccc, msc, geomet, weather, climate,
    collection, search, find, discover, dataset, catalogue.
    Mots-clés : Environnement et Changement climatique Canada, ECCC,
    Environnement Canada, Service météorologique du Canada (SMC),
    GeoMet, météo, climat, collection, recherche, trouver, jeu de
    données, catalogue.
    """
    return await client.search_collections(query, limit=limit, lang=lang)


@tool
async def eccc_list_collections(lang: Lang = "en") -> CollectionList:
    """List every MSC GeoMet OGC API collection (~100).

    Use for: a full inventory scan. Prefer eccc_search_collections for
    a topic search, or docs://eccc/well-known-collections for the
    collections that matter most - this returns the entire catalogue,
    including the downscaled-climate-projection families (`climate:*`),
    which are gridded coverages read with eccc_coverages_get_data.
    Keywords: environment canada, eccc, msc, geomet, weather, climate,
    list, inventory, all collections, catalogue, full list.
    Mots-clés : Environnement et Changement climatique Canada, ECCC,
    Environnement Canada, Service météorologique du Canada (SMC),
    GeoMet, météo, climat, liste, inventaire, toutes les collections,
    catalogue, liste complète.
    """
    return await client.list_collections(lang)


@tool
async def eccc_get_collection(collection_id: str, lang: Lang = "en") -> CollectionDetail:
    """Get one MSC GeoMet collection's description, spatial extent, and queryable properties.

    Use for: confirming what a collection covers and which property
    names you can filter/sort/select by (e.g. `province` and
    `alert_type` for weather-alerts, `STATION_NUMBER` for
    hydrometric-realtime) before calling eccc_query_items - an unknown
    property name is silently ignored upstream and returns zero rows
    rather than an error, so checking here first avoids that trap.
    Keywords: environment canada, eccc, msc, geomet, collection, detail,
    metadata, queryables, properties, schema, extent, bbox.
    Mots-clés : Environnement et Changement climatique Canada, ECCC,
    Environnement Canada, Service météorologique du Canada (SMC),
    GeoMet, collection, détail, métadonnées, propriétés interrogeables,
    schéma, étendue géographique.
    """
    return await client.get_collection(collection_id, lang)


@tool
async def eccc_query_items(
    collection_id: str,
    bbox: list[float] | None = None,
    datetime_filter: str | None = None,
    filters: dict[str, str] | None = None,
    fields: list[str] | None = None,
    sortby: str | None = None,
    limit: int = 10,
    offset: int = 0,
    lang: Lang = "en",
) -> ItemsResult:
    """Query rows (GeoJSON features) from one MSC GeoMet collection.

    Use for: fetching actual weather alerts, current surface
    observations (SWOB), AQHI readings/forecasts, climate normals or
    daily/hourly observations, hydrometric water level/flow, or any
    other MSC GeoMet collection's data - one generic query works across
    every collection (see docs://eccc/well-known-collections for good
    starting `collection_id` values and example filters).
    `bbox` is `[west, south, east, north]` in decimal degrees (WGS84).
    `datetime_filter` accepts a single RFC3339 date or datetime or an
    interval (`"start/end"`, `".."` for an open end) - support genuinely varies
    by collection and is not predictable from the collection's own
    metadata (confirmed: hydrometric-realtime supports it,
    weather-alerts does not and raises an error) - omit it and filter
    by `filters`/`bbox` instead if it fails.
    `filters` are exact-match property=value pairs (e.g.
    `{"province": "ON"}` or `{"STATION_NUMBER": "05BL023"}`) combined
    with AND. `fields` limits which properties come back (omit for
    all). `sortby` is a property name, prefixed with `-` for descending
    (e.g. `"-publication_datetime"`). `limit` is capped at 1000 per
    request and rows stop at about 1 MB (`note` gives the next offset) -
    several collections here have hundreds of thousands of rows, so page
    with `offset`. Read docs://eccc/gotchas before relying on `datetime_filter`
    or on `climate-stations`' LATITUDE/LONGITUDE properties.
    Keywords: environment canada, eccc, msc, geomet, weather alert,
    weather forecast, snow, rain, temperature, tomorrow, current
    conditions, swob, observation, aqhi, air quality, climate
    normal, hydrometric, water level, flow, marine forecast, query,
    data, filter, bbox, station.
    Mots-clés : Environnement Canada, Environnement et Changement
    climatique Canada, ECCC, Service météorologique du Canada (SMC),
    GeoMet, météo, prévisions météo, prévisions, alerte météo, alertes
    météorologiques, conditions actuelles, observation, cote air santé
    (CAS), qualité de l'air, normale climatique, hydrométrique, rivière,
    cours d'eau, hydrogramme, niveau d'eau, débit, débit journalier,
    prévision maritime, requête, données, filtre, station.
    """
    return await client.query_items(
        collection_id,
        bbox=bbox,
        datetime_filter=datetime_filter,
        filters=filters,
        fields=fields,
        sortby=sortby,
        limit=limit,
        offset=offset,
        lang=lang,
    )
