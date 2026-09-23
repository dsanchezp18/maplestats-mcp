"""MCP tools for British Columbia's BC Geographic Warehouse (BCGW)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.bcgw import client
from maple_data_mcp.modules.bcgw.constants import ROWS_LIMIT_DEFAULT
from maple_data_mcp.modules.bcgw.schemas import (
    LayerQueryResult,
    MiningTenureQueryResult,
    WildfireQueryResult,
)

Lang = Literal["en", "fr"]


@tool
async def bcgw_get_active_wildfires(
    status: str | None = None,
    fire_year: int | None = None,
    min_size_hectares: float | None = None,
    include_geometry: bool = False,
    limit: int = ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> WildfireQueryResult:
    """Query current BC wildfire perimeters and status from the BC Wildfire
    Service's mapped fire layer.

    Use for: checking active/recent wildfire status, size in hectares,
    and mapped perimeter for any fire tracked by the BC Wildfire Service.
    status is free text matched against real values like "Out of
    Control", "Being Held", "Under Control", "Out" -- there is no fixed
    enum. Leave include_geometry false unless the fire polygon itself is
    needed.
    Keywords: British Columbia, BC, wildfire, forest fire, fire
    perimeter, fire status, fire centre, hectares burned, BC Wildfire
    Service, active fire, out of control, being held.
    Mots-clés: Colombie-Britannique, feu de forêt, incendie, périmètre
    d'incendie, statut du feu, hectares brûlés, service des incendies de
    forêt, feu actif, hors de contrôle, maîtrisé.
    """
    return await client.get_active_wildfires(
        status=status,
        fire_year=fire_year,
        min_size_hectares=min_size_hectares,
        include_geometry=include_geometry,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def bcgw_get_mining_tenure(
    tenure_type: str | None = None,
    owner_name: str | None = None,
    min_area_hectares: float | None = None,
    include_geometry: bool = False,
    limit: int = ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> MiningTenureQueryResult:
    """Query acquired BC mineral/placer mining tenure (claims) by type,
    owner, or minimum area.

    Use for: mining rights research, resource-extraction analysis, and
    prospecting-zone identification -- claim name, tenure type
    (mineral/placer), owner, area in hectares, issue/expiry dates.
    tenure_type is "mineral" or "placer". owner_name does a substring
    match (case-insensitive from the caller's side).
    Keywords: British Columbia, BC, mining, mineral tenure, placer
    claim, mining claim, prospecting, mining rights, owner, hectares,
    tenure number, resource extraction.
    Mots-clés: Colombie-Britannique, exploitation minière, titre
    minier, claim de placer, droits miniers, propriétaire, hectares,
    numéro de titre, prospection, extraction de ressources.
    """
    return await client.get_mining_tenure(
        tenure_type=tenure_type,
        owner_name=owner_name,
        min_area_hectares=min_area_hectares,
        include_geometry=include_geometry,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def bcgw_query_layer(
    type_name: str,
    cql_filter: str | None = None,
    property_names: str | None = None,
    include_geometry: bool = False,
    sort_by: str | None = None,
    limit: int = ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> LayerQueryResult:
    """Query any BC Geographic Warehouse (BCGW) layer directly by its
    type_name (e.g. "WHSE_LAND_AND_NATURAL_RESOURCE.PROT_RESTRICTED_AREAS_SP"),
    for any dataset not covered by a curated bcgw_* tool.

    Discover a layer's type_name via ckan_search_datasets/
    ckan_get_dataset (portal="bc") -- a WFS/WMS-queryable BC dataset's package
    carries a resource whose URL embeds the type_name right after
    "openmaps.gov.bc.ca/geo/pub/". Filter with a standard OGC CQL
    expression against that layer's own field names.
    Keywords: British Columbia, BC, BCGW, BC Geographic Warehouse,
    WFS, geospatial, layer, feature, CQL filter, data catalogue,
    generic query, openmaps.
    Mots-clés: Colombie-Britannique, entrepôt géographique, WFS,
    géospatial, couche, entité, filtre CQL, catalogue de données,
    requête générique.
    """
    return await client.query_layer(
        type_name,
        cql_filter=cql_filter,
        property_names=property_names,
        include_geometry=include_geometry,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
        lang=lang,
    )
