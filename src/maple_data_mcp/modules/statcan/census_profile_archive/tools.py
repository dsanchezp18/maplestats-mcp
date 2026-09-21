"""MCP tools for archived (pre-2021) Census Profile bulk downloads."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.statcan.census_profile_archive import client
from maple_data_mcp.modules.statcan.census_profile_archive.schemas import (
    DownloadLink,
    GeographyLevelList,
)

CensusYear = Literal[2001, 2006, 2011, 2016]


@tool
async def statcan_census_profile_archive_list_geography_levels(
    year: CensusYear,
) -> GeographyLevelList:
    """List geography levels and file formats available for an archived census year.

    Use for: discovering what level keys (needed by
    statcan_census_profile_archive_get_download_link) and file formats
    exist for one archived census (2001, 2006, 2011, or 2016) before
    the 2021 Census Profile (covered by statcan_census_profile_*
    instead). Coverage genuinely narrows going back in time: 2016 has
    34 geography groupings, 2011 has 14, 2006 and 2001 each have 5.
    Keywords: census, archive, historical, 2001, 2006, 2011, 2016,
    bulk download, comprehensive download file.
    Mots-clés : recensement, archive, historique, téléchargement en
    bloc, fichier de téléchargement global.
    """
    return await client.list_geography_levels(year)


@tool
async def statcan_census_profile_archive_get_download_link(
    year: CensusYear, level: str, file_format: str
) -> DownloadLink:
    """Get the direct bulk-download URL for one archived census year/level/format.

    Use for: resolving the actual downloadable file (a compressed
    CSV or TAB archive covering every geography at that level, for all
    topics) for a pre-2021 census, given a level key from
    statcan_census_profile_archive_list_geography_levels. Files can be
    large (tens to hundreds of megabytes for fine-grained levels like
    dissemination areas). Only CSV and TAB formats are covered -- IVT
    (a proprietary Beyond 20/20 format) uses a different, separate
    resolver not implemented here. Keywords: census, archive,
    historical, download, CSV, TAB, comprehensive download file.
    Mots-clés : recensement, archive, historique, téléchargement,
    fichier de téléchargement global.
    """
    return await client.get_download_link(year, level, file_format)
