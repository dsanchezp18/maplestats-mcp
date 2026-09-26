"""MCP tools for the 2016 Census Profile Web Data Service."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.census_profile_2016 import client
from maplestats_mcp.modules.statcan.census_profile_2016.schemas import (
    Census2016DataResult,
    Census2016GeographyList,
)

GeographyLevel = Literal[
    "canada_provinces_territories",
    "census_divisions",
    "census_subdivisions",
    "census_metro_areas",
    "census_tracts",
    "dissemination_areas",
    "designated_places",
    "economic_regions",
    "federal_electoral_districts",
    "forward_sortation_areas",
    "health_regions",
    "population_centres",
]
ProvinceTerritory = Literal[
    "all",
    "newfoundland_and_labrador",
    "prince_edward_island",
    "nova_scotia",
    "new_brunswick",
    "quebec",
    "ontario",
    "manitoba",
    "saskatchewan",
    "alberta",
    "british_columbia",
    "yukon",
    "northwest_territories",
    "nunavut",
]
Topic = Literal[
    "all_topics",
    "aboriginal_peoples",
    "education",
    "ethnic_origin",
    "families_households_and_marital_status",
    "housing",
    "immigration_and_citizenship",
    "income",
    "journey_to_work",
    "labour",
    "language",
    "language_of_work",
    "mobility",
    "population",
    "visible_minority",
]
Statistic = Literal["counts", "rate"]


@tool
async def statcan_census_profile_2016_list_geographies(
    level: GeographyLevel,
    province_territory: ProvinceTerritory = "all",
    lang: Literal["en", "fr"] = "en",
) -> Census2016GeographyList:
    """List 2016 Census geographies (with their DGUIDs) for one geography level.

    Use for: finding a geography's DGUID code (needed by
    statcan_census_profile_2016_get_data) for the 2016 census, at a
    chosen level (province, census division, census subdivision,
    census metro area, census tract, dissemination area, forward
    sortation area, health region, economic region, federal electoral
    district, population centre, designated place). Optionally filter
    to one province/territory. Each result also carries global
    non-response rates and a data-quality flag. Keywords: census 2016,
    geography, DGUID, place name, municipality, census subdivision, CMA,
    geographic code.
    Mots-clés : recensement 2016, géographie, DGUID, nom de lieu,
    municipalité, subdivision de recensement, RMR, code géographique.
    """
    return await client.list_geographies(level, province_territory=province_territory, lang=lang)


@tool
async def statcan_census_profile_2016_get_data(
    dguid: str,
    topic: Topic = "all_topics",
    statistic: Statistic = "counts",
    include_notes: bool = False,
    lang: Literal["en", "fr"] = "en",
) -> Census2016DataResult:
    """Get 2016 Census Profile data for one geography (by DGUID).

    Use for: retrieving 2016 census values (counts or rates) for a
    geography found via statcan_census_profile_2016_list_geographies,
    optionally scoped to one topic (population, income, housing,
    labour, education, language, mobility, immigration and
    citizenship, ethnic origin, visible minority, Aboriginal peoples,
    journey to work, language of work, families/households/marital
    status). Values include separate total/male/female breakdowns and
    any suppression/quality symbol alongside the numeric value -- do
    not drop a flagged value silently. Set include_notes=True for the
    full explanatory footnote text. This is distinct from
    statcan_census_profile_* (2021) and covers only the 2016 census.
    Keywords: census 2016, population, dwelling, income, age, demographics,
    statistics Canada, census profile.
    Mots-clés : recensement 2016, population, logement, revenu, âge,
    démographie, Statistique Canada, profil du recensement.
    """
    return await client.get_data(
        dguid, topic=topic, statistic=statistic, include_notes=include_notes, lang=lang
    )
