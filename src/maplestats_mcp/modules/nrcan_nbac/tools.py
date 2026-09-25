"""MCP tools for NRCan's National Burned Area Composite (NBAC)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.nrcan_nbac import client
from maplestats_mcp.modules.nrcan_nbac.constants import ROWS_LIMIT_DEFAULT
from maplestats_mcp.modules.nrcan_nbac.schemas import FireQueryResult

Lang = Literal["en", "fr"]


@tool
async def nrcan_nbac_query_fires(
    cql_filter: str | None = None,
    include_geometry: bool = False,
    sort_by: str | None = None,
    limit: int = ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FireQueryResult:
    """Query mapped fire polygons/records from Natural Resources Canada's NBAC.

    Use for: wildfire start/end dates, adjusted burned area (hectares),
    fire cause, and (optionally) fire polygon geometry, for any fire
    event mapped in Canada since 1972. Filter with a standard OGC CQL
    expression against NBAC's own field names, e.g. "admin_area = 'BC'
    AND year >= 2017 AND year <= 2024" to get every mapped BC fire from
    2017 to 2024. Leave include_geometry false (the default) unless you
    specifically need the fire polygons -- NBAC's geometry can be large.
    Keywords: NRCan, National Burned Area Composite, NBAC, wildfire,
    forest fire, burned area, fire polygon, hectares burned, CWFIS,
    fire perimeter, fire season, prescribed burn.
    Mots-clés : RNCan, Composite national des zones brûlées, CNZB,
    feu de forêt, incendie, superficie brûlée, polygone d'incendie,
    hectares brûlés, SCIF, périmètre d'incendie, saison des feux,
    brûlage dirigé.
    """
    return await client.query_fires(
        cql_filter=cql_filter,
        include_geometry=include_geometry,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
        lang=lang,
    )
