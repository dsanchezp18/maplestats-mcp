"""Guided-workflow MCP prompts for the StatCan module."""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp.prompts import prompt

Lang = Annotated[Literal["en", "fr"], "Language: 'en' or 'fr'"]


@prompt
def find_and_fetch_series(topic: str, lang: Lang = "en") -> str:
    """Guided workflow: find a StatCan series on a topic and fetch its latest data."""
    return (
        f"To find and fetch StatCan data about '{topic}':\n"
        "1. Call wds_search_cubes(query=<topic>) to find a candidate productId.\n"
        "2. Call wds_get_cube_metadata(product_id=...) to see its dimensions and "
        "member ids.\n"
        "3. Build a coordinate from the member ids you want (10 dot-separated "
        "positions, pad unused with '0'), then call "
        "wds_get_series_info_from_cube_pid_coord to resolve it to a vectorId.\n"
        "4. Call wds_get_data_from_vectors(vector_ids=[...]) for the latest "
        "observations, or sdmx_get_vector_data for a filtered SDMX query."
    )


@prompt
def look_up_classification(topic: str, lang: Lang = "en") -> str:
    """Guided workflow: look up a StatCan classification (e.g. NAICS) for a topic."""
    return (
        f"To look up a StatCan classification related to '{topic}':\n"
        "1. Call rdaas_search_classifications(query=<topic>) to find candidate "
        "classifications.\n"
        "2. Call rdaas_get_classification(classification_id=...) for its "
        "background, version, and level structure.\n"
        "3. Call rdaas_get_classification_categories_detailed(classification_id=...) "
        "for the full code/category tree.\n"
        "4. If converting between two classification versions, use "
        "rdaas_search_concordances then rdaas_get_concordance_maps."
    )


@prompt
def build_sdmx_or_key(product_id: int, dimension_position: int, lang: Lang = "en") -> str:
    """Guided workflow: build a complete SDMX OR key for a large dimension."""
    return (
        f"To query every code of dimension {dimension_position} on productId "
        f"{product_id} without StatCan's wildcard sparse-sample problem:\n"
        "1. Call sdmx_get_structure(product_id=...) to see all dimensions and "
        "their positions.\n"
        "2. Call sdmx_get_key_for_dimension(product_id=..., "
        f"dimension_position={dimension_position}) to get a complete leaf-code "
        "OR key for that dimension.\n"
        "3. Splice that or_key into the dot-separated SDMX key at this "
        "dimension's position (other positions can stay wildcarded if they "
        "have fewer than ~30 codes).\n"
        "4. Call sdmx_get_data(product_id=..., key=<spliced key>) with the "
        "completed key."
    )
