"""MCP tools for Beyond 20/20 files on Borealis."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.borealis import client, constants
from maplestats_mcp.modules.borealis.schemas import (
    IvtSearchResult,
    OdesiDatasetDetail,
    OdesiSearchResult,
    OdesiVariableResult,
)

Lang = Literal["en", "fr"]


@tool
async def borealis_search_ivt(
    query: str = "",
    limit: int = constants.LIMIT_DEFAULT,
    lang: Lang = "en",
) -> IvtSearchResult:
    """Find Beyond 20/20 (.ivt) statistical tables on Borealis, with R code to read them.

    Use for: Statistics Canada tables that exist only as Beyond 20/20
    files and were deposited on Borealis (the Canadian Dataverse) by
    university libraries: historical censuses 1665-1871, Census of
    Population tabulations 1996-2021, Census of Agriculture 2001, the
    Labour Force Historical Review 1997-2008, Canadian Business Patterns
    and Business Counts, justice surveys, HART housing tabulations. Every
    word of the query must match the dataset or file. Each hit gives the
    download URL, size, whether a Borealis login is needed, and an R
    snippet using canivt (mountainMath), the only maintained IVT reader.
    An empty query lists IVT files by relevance. `lang="fr"` gives
    notes, errors and provenance in French; dataset titles are as
    deposited (English or French).
    Keywords: Beyond 20/20, IVT, Borealis, Dataverse, Data Liberation
    Initiative, historical census, Canadian Business Patterns, Labour
    Force Historical Review, canivt, custom tabulation, research data
    repository, university data library.
    Mots-clés : Beyond 20/20, IVT, Borealis, Dataverse, Initiative de
    démocratisation des données, recensement historique, Structure des
    industries canadiennes, Revue chronologique de la population active,
    totalisation personnalisée.
    """
    return await client.search_ivt(query, limit=limit, lang=lang)


OdesiCollection = Literal[
    "all_public", "pumfs", "polls", "aggregate", "census", "other", "international"
]


@tool
async def borealis_odesi_search_datasets(
    query: str = "",
    collection: OdesiCollection = "all_public",
    limit: int = constants.LIMIT_DEFAULT,
    start: int = 0,
    lang: Lang = "en",
) -> OdesiSearchResult:
    """Search ODESI on Borealis for StatCan public use microdata files (PUMFs), polls and census data.

    Use for: finding microdata described in DDI by Canadian
    university libraries: StatCan PUMFs (Labour Force, Canadian
    Community Health, General Social, Census PUMFs), Canadian public opinion polls (CORA: Environics Focus
    Canada, Gallup), StatCan aggregate tables, census collections and
    international data. collection narrows to "pumfs", "polls",
    "aggregate", "census", "other" or "international"; the default
    "all_public" covers all of them. Every word of the query must match
    the title, description or keywords; page with `start`. The DLI-licensed collection
    (about 414 datasets, e.g. the Postal Code Conversion File) is
    skipped on purpose: its data files are restricted to DLI-member
    institutions. A hit does not say which files are open; call
    borealis_odesi_get_dataset with its persistent_id for that. `lang="fr"`
    gives notes, errors and provenance in French; titles are as deposited.
    Keywords: ODESI, Borealis, Dataverse, DDI, PUMF, public use
    microdata file, Labour Force microdata, public opinion poll,
    CORA, Data Liberation Initiative, codebook, social science data.
    Mots-clés : ODESI, Borealis, Dataverse, DDI, FMGD, fichier de
    microdonnées à grande diffusion, microdonnées d'enquête, sondage
    d'opinion publique, Initiative de démocratisation des données,
    livre de codes, données des sciences sociales.
    """
    return await client.search_odesi_datasets(
        query, collection=collection, limit=limit, start=start, lang=lang
    )


@tool
async def borealis_odesi_get_dataset(persistent_id: str, lang: Lang = "en") -> OdesiDatasetDetail:
    """Get an ODESI dataset's DDI study description and which files are public or restricted.

    Use for: the full description of one dataset found with
    borealis_odesi_search_datasets: abstract, time period, geography,
    unit of analysis, universe, sampling, terms of use, citation, and
    the files with download links. Says plainly how many files anyone can download
    without a login (public_files, with size and link) and how many are
    restricted to DLI-member institutions (names only, no link
    given). Public here means no Borealis login; the terms of use can still limit
    redistribution (many PUMFs are for non-profit research and
    teaching). persistent_id is a DOI such as "doi:10.5683/SP3/TVVQPG".
    For variable names and labels use borealis_odesi_search_variables.
    `lang="fr"` gives the access summary, errors and provenance in
    French; the DDI text is as deposited.
    Keywords: ODESI, DDI, codebook, PUMF download, dataset metadata,
    terms of use, restricted files, DLI licence, Borealis, DOI, poll.
    Mots-clés : ODESI, DDI, livre de codes, téléchargement FMGD,
    métadonnées du jeu de données, conditions d'utilisation, fichiers
    restreints, licence IDD, Borealis, DOI.
    """
    return await client.get_odesi_dataset(persistent_id, lang=lang)


@tool
async def borealis_odesi_search_variables(
    persistent_id: str,
    query: str = "",
    limit: int = constants.VARIABLES_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> OdesiVariableResult:
    """List or search the variables (names and labels) in one ODESI dataset's DDI codebook.

    Use for: checking whether a PUMF or poll holds a variable
    ("unemployment", "union", "province") before downloading it, from the
    variable-level DDI that Borealis builds for tabular data files. Every
    word of the query must match the variable name or label; an empty
    query lists the first variables. Datasets whose data were not
    ingested as tabular files have no variable-level DDI: the result is
    empty with a note saying so, not an error. persistent_id is a DOI
    from borealis_odesi_search_datasets. `lang="fr"` gives notes, errors
    and provenance in French; labels are as deposited.
    Keywords: ODESI, DDI, variable list, variable labels, codebook,
    PUMF variables, poll questions, microdata dictionary, Borealis,
    Dataverse, microdata variables.
    Mots-clés : ODESI, DDI, liste des variables, étiquettes de
    variables, livre de codes, variables FMGD, questions de sondage,
    dictionnaire de données, microdonnées, Borealis.
    """
    return await client.search_odesi_variables(persistent_id, query, limit=limit, lang=lang)
