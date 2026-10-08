"""Guided-workflow MCP prompts for the StatCan module.

Each prompt picks its body by ``lang``; the French bodies are written for a
francophone analyst, not translated line by line.
"""

# No `from __future__ import annotations`: FastMCP resolves a prompt's
# parameter types by name, and the stringified `Lang` alias does not resolve.
from typing import Annotated, Literal

from fastmcp.prompts import prompt

Lang = Annotated[Literal["en", "fr"], "Language: 'en' or 'fr'"]

_FIND_AND_FETCH = {
    "en": (
        "To find and fetch StatCan data about '{topic}':\n"
        "1. Call wds_search_cubes(query=<topic>) to find a candidate productId.\n"
        "2. Call wds_get_cube_metadata(product_id=...) to see its dimensions and "
        "member ids.\n"
        "3. Build a coordinate from the member ids you want (10 dot-separated "
        "positions, pad unused with '0'), then call "
        "wds_get_series_info(product_id=..., coordinate=...) to resolve it to a "
        "vectorId.\n"
        "4. Call wds_get_data_from_vectors(vector_ids=[...]) for the latest "
        "observations, or sdmx_get_vector_data for a filtered SDMX query."
    ),
    "fr": (
        "Pour trouver et obtenir des données de Statistique Canada sur "
        "« {topic} » :\n"
        "1. Appelez wds_search_cubes(query=<sujet>, lang='fr') pour repérer un "
        "productId candidat.\n"
        "2. Appelez wds_get_cube_metadata(product_id=...) pour voir les "
        "dimensions du tableau et les identifiants de leurs membres.\n"
        "3. Composez une coordonnée à partir des identifiants de membres "
        "voulus (10 positions séparées par des points, les positions "
        "inutilisées étant remplies par '0'), puis appelez "
        "wds_get_series_info(product_id=..., coordinate=...) pour obtenir le "
        "vectorId correspondant.\n"
        "4. Appelez wds_get_data_from_vectors(vector_ids=[...]) pour les "
        "observations les plus récentes, ou sdmx_get_vector_data pour une "
        "requête SDMX filtrée."
    ),
}

_CLASSIFICATION = {
    "en": (
        "To look up a StatCan classification related to '{topic}':\n"
        "1. Call rdaas_search_classifications(query=<topic>) to find candidate "
        "classifications.\n"
        "2. Call rdaas_get_classification(classification_id=...) for its "
        "background, version, and level structure.\n"
        "3. Call rdaas_get_classification_categories_detailed(classification_id=...) "
        "for the full code/category tree.\n"
        "4. If converting between two classification versions, use "
        "rdaas_search_concordances then rdaas_get_concordance_maps."
    ),
    "fr": (
        "Pour chercher une classification de Statistique Canada liée à "
        "« {topic} » (par exemple le SCIAN) :\n"
        "1. Appelez rdaas_search_classifications(query=<sujet>, lang='fr') "
        "pour repérer les classifications candidates.\n"
        "2. Appelez rdaas_get_classification(classification_id=...) pour "
        "son contexte, sa version et la structure de ses niveaux.\n"
        "3. Appelez "
        "rdaas_get_classification_categories_detailed(classification_id=...) "
        "pour l'arborescence complète des codes et des catégories.\n"
        "4. Pour passer d'une version de la classification à une autre, "
        "utilisez rdaas_search_concordances, puis rdaas_get_concordance_maps."
    ),
}

_SDMX_OR_KEY = {
    "en": (
        "To query every code of dimension {dimension_position} on productId "
        "{product_id} without StatCan's wildcard sparse-sample problem:\n"
        "1. Call sdmx_get_structure(product_id=...) to see all dimensions and "
        "their positions.\n"
        "2. Call sdmx_get_key_for_dimension(product_id=..., "
        "dimension_position={dimension_position}) to get a complete leaf-code "
        "OR key for that dimension.\n"
        "3. Splice that or_key into the dot-separated SDMX key at this "
        "dimension's position (other positions can stay wildcarded if they "
        "have fewer than ~30 codes).\n"
        "4. Call sdmx_get_data(product_id=..., key=<spliced key>) with the "
        "completed key."
    ),
    "fr": (
        "Pour interroger tous les codes de la dimension {dimension_position} "
        "du productId {product_id} sans tomber sur l'échantillon partiel que "
        "renvoie le caractère générique de Statistique Canada :\n"
        "1. Appelez sdmx_get_structure(product_id=...) pour voir toutes les "
        "dimensions et leur position.\n"
        "2. Appelez sdmx_get_key_for_dimension(product_id=..., "
        "dimension_position={dimension_position}) pour obtenir une clé OR "
        "complète des codes de dernier niveau de cette dimension.\n"
        "3. Insérez cette clé or_key dans la clé SDMX (séparée par des "
        "points) à la position de cette dimension ; les autres positions "
        "peuvent rester génériques si elles comptent moins d'une trentaine "
        "de codes.\n"
        "4. Appelez sdmx_get_data(product_id=..., key=<clé complétée>) avec "
        "la clé ainsi obtenue."
    ),
}


@prompt
def find_and_fetch_series(topic: str, lang: Lang = "en") -> str:
    """Guided workflow: find a StatCan series on a topic and fetch its latest data.
    Use lang="fr" for the French version."""
    return _FIND_AND_FETCH[lang].format(topic=topic)


@prompt
def look_up_classification(topic: str, lang: Lang = "en") -> str:
    """Guided workflow: look up a StatCan classification (e.g. NAICS) for a topic.
    Use lang="fr" for the French version."""
    return _CLASSIFICATION[lang].format(topic=topic)


@prompt
def build_sdmx_or_key(product_id: int, dimension_position: int, lang: Lang = "en") -> str:
    """Guided workflow: build a complete SDMX OR key for a large dimension.
    Use lang="fr" for the French version."""
    return _SDMX_OR_KEY[lang].format(product_id=product_id, dimension_position=dimension_position)
