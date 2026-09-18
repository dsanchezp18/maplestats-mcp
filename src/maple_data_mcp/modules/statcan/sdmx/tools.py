"""MCP tools for StatCan's SDMX REST API.

Filtered, server-side-sliced queries — request only the dimension
values you need rather than downloading a full table.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.statcan.sdmx import client
from maple_data_mcp.modules.statcan.sdmx.schemas import SdmxData, SdmxOrKey, SdmxStructure

Lang = Literal["en", "fr"]


@tool
async def sdmx_get_structure(product_id: int, lang: Lang = "en") -> SdmxStructure:
    """Get the SDMX dimension structure for a StatCan table: each
    non-time dimension's codelist, with parent/child code relationships.

    Use for: understanding a table's dimensions before building an SDMX
    query key, or before calling sdmx_get_key_for_dimension on a large
    dimension.
    Keywords: statcan, sdmx, structure, dimensions, codelist, dsd, keys.
    Mots-clés: statcan, sdmx, structure, dimensions, liste de codes,
    dsd, clés, classification.
    """
    return await client.get_structure(product_id)


@tool
async def sdmx_get_key_for_dimension(
    product_id: int, dimension_position: int, lang: Lang = "en"
) -> SdmxOrKey:
    """Build a complete OR key covering every leaf code of one dimension.

    Use for: querying a dimension with more than ~30 codes (e.g.
    detailed geography or occupation) — StatCan's SDMX API returns a
    sparse, unpredictable sample if that dimension is left wildcarded
    instead. Splice the returned or_key into the dot-separated key at
    this dimension's position before calling sdmx_get_data.
    Keywords: statcan, sdmx, wildcard, or key, large dimension, leaf
    codes, sparse sample, geography, occupation.
    Mots-clés: statcan, sdmx, caractère générique, clé or, grande
    dimension, codes terminaux, échantillon partiel, géographie,
    profession.
    """
    return await client.get_key_for_dimension(product_id, dimension_position)


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
    wildcard on a >30-code dimension). `last_n_observations` cannot be
    combined with `start_period`/`end_period` — StatCan rejects that
    combination.
    Keywords: statcan, sdmx, data, filtered, key, dimensions, query,
    observations, slice.
    Mots-clés: statcan, sdmx, données, filtré, clé, dimensions, requête,
    observations, découpage.
    """
    return await client.get_data(
        product_id,
        key,
        start_period=start_period,
        end_period=end_period,
        last_n_observations=last_n_observations,
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
    Keywords: statcan, sdmx, vector, data, observations, series, query.
    Mots-clés: statcan, sdmx, vecteur, données, observations, série,
    requête, identifiant de vecteur.
    """
    return await client.get_vector_data(
        vector_id,
        start_period=start_period,
        end_period=end_period,
        last_n_observations=last_n_observations,
    )
