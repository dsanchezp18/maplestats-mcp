"""MCP tools for StatCan's SDMX REST API.

Filtered, server-side-sliced queries — request only the dimension
values you need rather than downloading a full table.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.sdmx import client
from maplestats_mcp.modules.statcan.sdmx.schemas import SdmxData, SdmxOrKey, SdmxStructure

Lang = Literal["en", "fr"]


@tool
async def sdmx_get_structure(
    product_id: int,
    dimension_position: int | None = None,
    code_query: str = "",
    limit: int = 100,
    offset: int = 0,
    lang: Lang = "en",
) -> SdmxStructure:
    """Get the SDMX dimension structure for a StatCan table: each
    non-time dimension's codelist, with parent/child code relationships.

    Use for: understanding a table's dimensions before building an SDMX
    query key, or before calling sdmx_get_key_for_dimension on a large
    dimension. Codes are paged per dimension (`limit` default 100,
    `offset`); `code_query` keeps codes whose name contains the text and
    `dimension_position` returns a single dimension; each dimension's
    `code_count` is its full size and provenance.limits says what was
    left out. If StatCan's SDMX structure document is empty or cut off
    (some Labour Force Survey tables), the structure is built from WDS
    metadata instead, with identical member ids.
    Keywords: statcan, sdmx, structure, dimensions, codelist, dsd, keys,
    Statistics Canada.
    Mots-clés : statcan, sdmx, structure, dimensions, liste de codes, dsd,
    clés, classification.
    """
    return await client.get_structure(
        product_id,
        dimension_position=dimension_position,
        code_query=code_query,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def sdmx_get_key_for_dimension(
    product_id: int, dimension_position: int, lang: Lang = "en"
) -> SdmxOrKey:
    """Build a complete OR key covering every leaf code of one dimension.

    Use for: querying a dimension with more than ~30 codes (e.g.
    detailed geography or industry) — StatCan's SDMX API returns a
    sparse, unpredictable sample if that dimension is left wildcarded
    instead. Splice the returned or_key into the dot-separated key at
    this dimension's position before calling sdmx_get_data.
    Keywords: statcan, sdmx, wildcard, or key, large dimension, leaf
    codes, sparse sample, geography, wildcard dimension.
    Mots-clés : statcan, sdmx, caractère générique, clé OR, grande
    dimension, codes terminaux, échantillon partiel, géographie,
    wildcard.
    """
    return await client.get_key_for_dimension(product_id, dimension_position, lang=lang)


@tool
async def sdmx_get_data(
    product_id: int,
    key: str,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n_observations: int | None = None,
    lang: Lang = "en",
) -> SdmxData:
    """Get filtered, server-side-sliced observations for a StatCan table.

    Use for: fetching only the dimension combination you need rather
    than the full table. `key` is a dot-separated string of member ids,
    one per non-time dimension, in dimension-position order (empty
    segment = wildcard; use sdmx_get_key_for_dimension instead of a
    wildcard on a >30-code dimension). With no period arguments the
    LATEST 100 observations per series are returned (not the oldest);
    pass `last_n_observations` for another count or
    `start_period`/`end_period` (e.g. 2024-01) for a range -- the two
    cannot be combined. Each series keeps at most 500 newest rows and a
    response at most 200 series; provenance.limits records any cut.
    Keywords: statcan, sdmx, data, filtered, key, dimensions, query,
    observations, slice.
    Mots-clés : statcan, sdmx, données, filtré, clé, dimensions, requête,
    observations, découpage.
    """
    return await client.get_data(
        product_id,
        key,
        start_period=start_period,
        end_period=end_period,
        last_n_observations=last_n_observations,
        lang=lang,
    )


@tool
async def sdmx_get_vector_data(
    vector_id: int,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n_observations: int | None = None,
    lang: Lang = "en",
) -> SdmxData:
    """Get filtered SDMX observations for a known vector ID.

    Use for: fetching one specific series via SDMX when you already
    have its vector ID (resolves the vector to a productId/coordinate
    internally, then builds the matching SDMX key).
    Keywords: statcan, sdmx, vector, data, observations, series, query,
    Statistics Canada.
    Mots-clés : statcan, sdmx, vecteur, données, observations, série,
    requête, identifiant de vecteur.
    """
    return await client.get_vector_data(
        vector_id,
        start_period=start_period,
        end_period=end_period,
        last_n_observations=last_n_observations,
        lang=lang,
    )
