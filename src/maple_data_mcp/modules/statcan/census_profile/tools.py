"""MCP tools for the 2021 Census Profile SDMX API."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.statcan.census_profile import client, constants
from maple_data_mcp.modules.statcan.census_profile.schemas import (
    CensusProfileDataResult,
    CharacteristicSearchResult,
    GeographySearchResult,
)

GeographyLevel = Literal[
    "canada_provinces_territories",
    "census_divisions",
    "census_subdivisions",
    "dissolved_census_subdivisions",
    "census_metro_areas",
    "census_tracts",
    "dissemination_areas",
    "aggregate_dissemination_areas",
    "designated_places",
    "economic_regions",
    "federal_electoral_districts",
    "forward_sortation_areas",
    "health_regions",
    "population_centres",
]
Gender = Literal["total", "men", "women"]
Statistic = Literal["counts", "rate"]


@tool
async def statcan_census_profile_search_geography(
    level: GeographyLevel,
    query: str = "",
    limit: int = constants.GEOGRAPHY_SEARCH_LIMIT_DEFAULT,
    lang: Literal["en", "fr"] = "en",
) -> GeographySearchResult:
    """Search 2021 Census Profile geography names for one geography level.

    Use for: finding a geography's DGUID code (needed by
    statcan_census_profile_get_data) by place name substring, at a
    chosen level (province, census division, census subdivision/
    municipality, census metro area, census tract, dissemination area,
    forward sortation area, health region, economic region, federal
    electoral district, population centre, designated place). An empty
    query returns every geography at that level. Keywords: census,
    geography, DGUID, place name, municipality, province, census
    subdivision, census tract, forward sortation area, FSA.
    Mots-clés : recensement, géographie, DGUID, nom de lieu,
    municipalité, province, subdivision de recensement, secteur de
    recensement, région de tri d'acheminement.
    """
    return await client.search_geography(level, query, limit=limit, lang=lang)


@tool
async def statcan_census_profile_search_characteristic(
    query: str = "",
    limit: int = constants.CHARACTERISTIC_SEARCH_LIMIT_DEFAULT,
    lang: Literal["en", "fr"] = "en",
) -> CharacteristicSearchResult:
    """Search the 2021 Census Profile's 2,631 characteristics (variables) by name.

    Use for: finding a characteristic code (needed by
    statcan_census_profile_get_data) by keyword, e.g. "population",
    "median household income", "dwelling", "commute". An empty query
    returns every characteristic. Each match includes parent_code when
    the characteristic is a sub-item of a broader one in the profile
    table's own hierarchy (e.g. "0 to 4 years" is a child of "0 to 14
    years", itself a child of "Total - Age groups of the population") --
    use this to tell a summary row from its breakdown rows rather than
    treating all 2,631 characteristics as a flat list. Keywords: census,
    characteristic,
    variable, population, income, dwelling, age, language, education,
    housing, commuting.
    Mots-clés : recensement, caractéristique, variable, population,
    revenu, logement, âge, langue, éducation, navettage.
    """
    return await client.search_characteristic(query, limit=limit, lang=lang)


@tool
async def statcan_census_profile_get_data(
    level: GeographyLevel,
    geography_codes: list[str],
    characteristic_codes: list[str],
    gender: Gender = "total",
    statistic: Statistic = "counts",
    lang: Literal["en", "fr"] = "en",
) -> CensusProfileDataResult:
    """Get 2021 Census Profile values for geographies and characteristics.

    Use for: retrieving actual census data (counts or rates) for one or
    more geographies (by DGUID, from
    statcan_census_profile_search_geography) crossed with one or more
    characteristics (by code, from
    statcan_census_profile_search_characteristic), for a given gender
    breakdown. Multiple geography_codes or characteristic_codes are
    combined (every geography x every characteristic). Returns each
    value alongside its data-quality flag and confidence interval when
    the upstream API supplies one -- do not drop a flagged or
    interval-bounded value silently. Keywords: census, population,
    dwelling, income, age, demographics, statistics Canada, 2021
    census, SDMX.
    Mots-clés : recensement, population, logement, revenu, âge,
    démographie, Statistique Canada, recensement de 2021.
    """
    return await client.get_data(
        level,
        geography_codes,
        characteristic_codes,
        gender=gender,
        statistic=statistic,
        lang=lang,
    )
