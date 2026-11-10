"""MCP tools for StatCan's survey directory and IMDB survey metadata."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.lang import use_lang
from maplestats_mcp.modules.statcan.surveys import client, constants
from maplestats_mcp.modules.statcan.surveys.schemas import (
    RdcSearchResult,
    RtraSearchResult,
    SurveyListResult,
    SurveyMetadata,
    SurveySection,
)


@tool
async def statcan_surveys_search_surveys(
    query: str = "", lang: Literal["en", "fr"] = "en", limit: int = constants.SEARCH_LIMIT_DEFAULT
) -> SurveyListResult:
    """Search StatCan's A-Z directory of surveys and statistical programs (~899 confirmed live).

    Use for: finding a survey's numeric IMDB ID (needed by
    statcan_surveys_get_survey_metadata) by name or acronym, instead of
    guessing it -- covers both active and inactive/discontinued surveys
    and statistical programs. query matches whole words of the name
    (accents ignored) or its acronym: 'IPPI' gives 2318, 'RMPI' 2306,
    'LFS' 3701, 'EICS' 4428 (French ones too: EPA, IPMB, ECAE).
    Distinct from statcan_reference_search_documents/search_analysis
    (documents about surveys) and from statcan_daily_* (release
    bulletin) -- this is the master list of the surveys/programs
    themselves. An empty query returns the full directory. Keywords:
    StatCan, survey, surveys Statistics Canada runs, statistical program,
    survey directory, survey ID, survey number, IMDB id, acronym,
    Statistics Canada, data source, survey list, Raw Materials Price
    Index, Employment Insurance Coverage Survey.
    Mots-clés : Statistique Canada, enquête, programme statistique,
    répertoire des enquêtes, numéro d'enquête, numéro BMDI, acronyme,
    source de données, liste des enquêtes, enquêtes statistiques,
    Enquête sur la couverture de l'assurance-emploi.
    """
    use_lang(lang)
    return await client.search_surveys(query, lang=lang, limit=limit)


@tool
async def statcan_surveys_get_survey_metadata(
    survey_id: int,
    lang: Literal["en", "fr"] = "en",
    section: SurveySection | list[SurveySection] | None = None,
) -> SurveyMetadata:
    """Get a survey's IMDB record: status, frequency, description, and its methodology.

    Use for: the "Definitions, data sources and methods" record of one
    survey or statistical program (id from statcan_surveys_search_surveys):
    status, frequency, description, subjects, reference and collection
    periods, whether response is mandatory or voluntary, how data are
    obtained (respondents, administrative files), the design (sample
    survey or census) and sample size, and the methodology sections:
    target_population, instrument_design, sampling, data_sources,
    error_detection, imputation, estimation, quality_evaluation,
    disclosure_control, revisions_and_seasonal_adjustment and
    data_accuracy. Without `section` every section comes back shortened
    to about 900 characters (trimmed_sections names them); pass one
    name or a list, e.g. section=["sampling", "data_sources"], for
    those sections in full and no others. IMDB (Integrated Metadata
    Base) is separate from the Reference/Analysis catalogues. Concepts
    and definitions (LFS involuntary part-time, CPI hedonic quality
    adjustment) are in each survey's guide, not here: read them with
    statcan_reference_get_section_text (publication='71-543-G', the Guide
    to the Labour Force Survey, or '62-553-X', the CPI Reference Paper,
    with query=<the concept>).
    Keywords: StatCan, IMDB, survey metadata, definitions, methodology,
    target population, sampling, sample size, mandatory or voluntary
    survey, collection method, imputation, disclosure control,
    seasonal adjustment, data accuracy, data quality.
    Mots-clés : Statistique Canada, BMDI, métadonnées d'enquête,
    définitions, méthodologie, population cible, échantillonnage,
    taille de l'échantillon, enquête obligatoire, mode de collecte,
    imputation, contrôle de la divulgation, désaisonnalisation,
    exactitude des données, temps partiel involontaire, ajustement
    hédonique.
    """
    use_lang(lang)
    return await client.get_survey_metadata(survey_id, lang=lang, section=section)


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
    use_lang(lang)
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
    use_lang(lang)
    return await client.search_rtra_datasets(
        query, lang=lang, deleted_variable=deleted_variable, limit=limit
    )
