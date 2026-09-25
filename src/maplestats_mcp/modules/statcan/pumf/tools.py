"""MCP tools for StatCan public use microdata files (PUMFs)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.pumf import client, constants, tabulate
from maplestats_mcp.modules.statcan.pumf.schemas import (
    Codebook,
    PumfFileList,
    PumfSearchResult,
    WeightedTable,
    ZipContents,
)


@tool
async def statcan_pumf_search(
    query: str = "", limit: int = 25, lang: Literal["en", "fr"] = "en"
) -> PumfSearchResult:
    """Find Statistics Canada public use microdata files (PUMFs) by topic.

    Use for: which surveys publish respondent-level microdata on a topic
    (e.g. "health", "labour", "spending"), with catalogue numbers such as
    71M0001X (Labour Force Survey) or 98M0001X (Census). Next:
    statcan_pumf_list_files for the downloads.
    Keywords: PUMF, microdata, public use microdata file, survey
    microdata, respondent records, Labour Force Survey, CCHS, census.
    Mots-clés : FMGD, microdonnées, fichier de microdonnées à grande
    diffusion, données d'enquête, EPA, ESCC, recensement.
    """
    return await client.search(query, lang=lang, limit=limit)


@tool
async def statcan_pumf_list_files(
    catalogue_number: str, lang: Literal["en", "fr"] = "en"
) -> PumfFileList:
    """List a PUMF's free ZIP downloads (years, files and formats).

    Use for: the download links for one PUMF, e.g. 71M0001X (monthly
    LFS files by year) or 98M0001X (Census individuals and hierarchical
    files, 1991-2021). Next: statcan_pumf_get_codebook with a ZIP url.
    Keywords: PUMF download, microdata file, ZIP, survey year, edition,
    catalogue number, Statistics Canada.
    Mots-clés : téléchargement FMGD, fichier de microdonnées, ZIP,
    année d'enquête, numéro de catalogue.
    """
    return await client.list_files(catalogue_number, lang=lang)


@tool
async def statcan_pumf_list_zip(url: str) -> ZipContents:
    """List what is inside a PUMF ZIP without downloading it.

    Use for: seeing the data files, user guides and codebook files in a
    StatCan PUMF ZIP (read with HTTP range requests, a few KB), and
    their uncompressed sizes. lang does not apply.
    Keywords: ZIP contents, PUMF files, user guide, record layout,
    codebook, data file size.
    Mots-clés : contenu du ZIP, fichiers FMGD, guide de l'utilisateur,
    dictionnaire de données, taille.
    """
    return await client.list_zip(url)


@tool
async def statcan_pumf_get_codebook(
    url: str,
    query: str | None = None,
    limit: int = constants.VARIABLES_DEFAULT,
    lang: Literal["en", "fr"] = "en",
) -> Codebook:
    """Read a PUMF's variables, labels, value codes and weight variables.

    Use for: which variable measures something (query matches names,
    labels and value labels, e.g. "tenure", "smok"), what each code
    means, column positions for fixed-width files, and which weights to
    use (final and bootstrap/replicate). Reads only the codebook files
    inside the ZIP. url comes from statcan_pumf_list_files.
    Keywords: codebook, data dictionary, variables, value labels, survey
    weights, bootstrap weights, record layout, PUMF.
    Mots-clés : dictionnaire de données, variables, étiquettes de
    valeurs, poids d'enquête, poids bootstrap, FMGD, disposition.
    """
    return await client.get_codebook(url, query=query, lang=lang, limit=limit)


@tool
async def statcan_pumf_tabulate(
    url: str,
    rows: list[str],
    statistic: Literal["total", "share", "mean"] = "total",
    value_variable: str | None = None,
    filters: dict[str, list[str]] | None = None,
    weight: str | None = None,
    data_file: str | None = None,
    min_count: int = 30,
    lang: Literal["en", "fr"] = "en",
) -> WeightedTable:
    """Compute a weighted table from PUMF microdata (totals, shares or means).

    Use for: population estimates from survey microdata, e.g. labour
    force status by province from the LFS, or mean hourly earnings. rows
    are up to 3 codebook variables to group by; filters keep only the
    listed codes (e.g. {"PROV": ["48"]}); share gives percentages within
    each group of all but the last row variable. Uses the survey weight
    (default: the codebook's main weight) and returns unweighted counts,
    flagging small cells. Standard errors and CVs come from the survey's
    documented replicate weights where verified (2021 Census individuals).
    The first call downloads the file (may take a minute or two; retry
    if it times out).
    Keywords: weighted estimate, tabulation, crosstab, microdata
    analysis, survey weight, population estimate, PUMF, LFS.
    Mots-clés : estimation pondérée, totalisation, tableau croisé,
    microdonnées, poids d'enquête, estimation de population, FMGD.
    """
    return await tabulate.tabulate(
        url,
        rows=rows,
        statistic=statistic,
        value_variable=value_variable,
        filters=filters,
        weight=weight,
        data_file=data_file,
        min_count=min_count,
        lang=lang,
    )
