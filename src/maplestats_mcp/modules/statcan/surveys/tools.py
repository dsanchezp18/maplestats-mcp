"""MCP tools for StatCan's survey directory and IMDB survey metadata."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.surveys import client, constants
from maplestats_mcp.modules.statcan.surveys.schemas import (
    RdcSearchResult,
    RtraSearchResult,
    SurveyListResult,
    SurveyMetadata,
)


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
    StatCan, survey, statistical program, survey directory, survey ID,
    Statistics Canada, data source, survey list.
    Mots-clés : Statistique Canada, enquête, programme statistique,
    répertoire des enquêtes, numéro d'enquête, source de données, liste des
    enquêtes, enquêtes statistiques.
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
    méthodologie, population cible, statut de l'enquête, fréquence,
    description de l'enquête.
    """
    return await client.get_survey_metadata(survey_id, lang=lang)


@tool
async def statcan_surveys_search_rdc_holdings(
    query: str = "", lang: Literal["en", "fr"] = "en", limit: int = constants.SEARCH_LIMIT_DEFAULT
) -> RdcSearchResult:
    """Search the microdata held at StatCan's Research Data Centres (RDCs).

    Use for: "is survey X available in a Research Data Centre, and
    which cycles?" -- the official holdings list (about 350 rows: survey
    or linked file, cycles or years held, acronym, IMDB record number).
    The record number is the id of statcan_surveys_get_survey_metadata,
    so each holding links to its survey record (detail_url); several
    linked files share the generic number 8006, which names no survey.
    This lists what exists, not data: RDC use needs an approved project
    and security clearance. query needs every word to appear in the
    name, acronym, cycles or record number (accents ignored). For the
    remote option see statcan_surveys_search_rtra_datasets; public
    files are statcan_pumf_search.
    Keywords: Research Data Centre, RDC, Canadian RDC Network, microdata
    holdings, restricted microdata, linked data, secure access, survey
    cycles, T1 Family File, Canadian Community Health Survey, record number.
    Mots-clés : Centre de données de recherche, CDR, microdonnées
    détaillées, fichiers couplés, accès sécurisé, cycles d'enquête,
    numéro d'enregistrement, Statistique Canada, données de recherche,
    enquête.
    """
    return await client.search_rdc_holdings(query, lang=lang, limit=limit)


@tool
async def statcan_surveys_search_rtra_datasets(
    query: str = "",
    lang: Literal["en", "fr"] = "en",
    deleted_variable: str | None = None,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
) -> RtraSearchResult:
    """Search datasets offered through StatCan's Real Time Remote Access (RTRA).

    Use for: the settings of each RTRA dataset (about 360 rows from 70
    surveys and administrative sources): tag name used in the RTRA
    program, dataset name, rounding base for counts, weight variable,
    and the variables deleted from the remote version, plus links to the
    IMDB survey records (sdds_id is the id of
    statcan_surveys_get_survey_metadata; instance_id is one cycle's
    page). deleted_variable keeps datasets that remove a given variable
    code (e.g. "PROVBIR"). query needs every word to appear in the
    survey, cycle, tag, dataset or weight name. RTRA lets registered
    users run SAS or Stata code on StatCan's server and get rounded
    output; this lists the setup, not data. For secure on-site access
    see statcan_surveys_search_rdc_holdings.
    Keywords: Real Time Remote Access, RTRA, remote access, rounding
    base, weight variable, deleted variables, disclosure control,
    microdata, tag name, Canadian Community Health Survey, Canadian
    Cancer Registry.
    Mots-clés : Système d'accès à distance en temps réel, ADTR, accès à
    distance, base d'arrondissement, variable de pondération, variables
    supprimées, contrôle de la divulgation, microdonnées, préfixe,
    Statistique Canada.
    """
    return await client.search_rtra_datasets(
        query, lang=lang, deleted_variable=deleted_variable, limit=limit
    )
