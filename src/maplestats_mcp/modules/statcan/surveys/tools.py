"""MCP tools for StatCan's survey directory and IMDB survey metadata."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.surveys import client, constants
from maplestats_mcp.modules.statcan.surveys.schemas import SurveyListResult, SurveyMetadata


@tool
async def statcan_surveys_search_surveys(
    query: str = "", lang: Literal["en", "fr"] = "en", limit: int = constants.SEARCH_LIMIT_DEFAULT
) -> SurveyListResult:
    """Search StatCan's A-Z directory of surveys and statistical programs (~899 confirmed live).

    Use for: finding a survey's numeric ID (needed by
    statcan_surveys_get_survey_metadata) by name -- covers both active
    and inactive/discontinued surveys and statistical programs.
    Distinct from statcan_reference_search_documents/search_analysis
    (documents about surveys) and from statcan_daily_* (release
    bulletin) -- this is the master list of the surveys/programs
    themselves. An empty query returns the full directory. Keywords:
    StatCan, survey, statistical program, survey directory, survey ID.
    Mots-clés : Statistique Canada, enquête, programme statistique,
    répertoire des enquêtes.
    """
    return await client.search_surveys(query, lang=lang, limit=limit)


@tool
async def statcan_surveys_get_survey_metadata(
    survey_id: int, lang: Literal["en", "fr"] = "en"
) -> SurveyMetadata:
    """Get a survey's IMDB metadata: status, frequency, description, and subjects.

    Use for: the genuine "Definitions, data sources and methods"
    content for one specific survey or statistical program -- its
    active/inactive status, collection frequency, a plain-language
    description, and its subject classifications -- found via
    statcan_surveys_search_surveys. This comes from IMDB (Integrated
    Metadata Base), a separate, older system from the Reference/
    Analysis catalogues; its full methodology sections (target
    population, sampling, data sources, data accuracy) are linked via
    detail_url rather than fully parsed here, since they are long
    prose sections better read directly than flattened into fields.
    Keywords: StatCan, IMDB, survey metadata, methodology, target
    population, data quality, survey status, survey frequency.
    Mots-clés : Statistique Canada, BMDI, métadonnées d'enquête,
    méthodologie, population cible, statut de l'enquête.
    """
    return await client.get_survey_metadata(survey_id, lang=lang)
