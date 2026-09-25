"""MCP tools for CMHC's "Data Tables" document catalogue (www.cmhc-schl.gc.ca).

Every tool returns a typed Pydantic model (see schemas.py). A raised
exception (see shared/errors.py) becomes a real MCP isError:true
result; tools never return an error-shaped dict.

This is a separate sub-API from the rest of modules/cmhc/ (the
`cmhc_*` tools in ../tools.py query CMHC's live HMIP portal for a
time series or current cross-tab; these `cmhc_dt_*` tools instead find
CMHC's officially-published Excel table files, one download per
survey edition — useful when the deliverable itself, not just the
numbers, is what's needed, and for surveys HMIP doesn't cover (the
Canadian Housing Survey, household income/equity/core-housing-need
breakdowns). `lang` is accepted for interface consistency but this
site's category/table URL slugs are language-neutral (unlike the rest
of modules/cmhc/, where lang changes the category name strings
themselves).
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.cmhc.data_tables import client
from maplestats_mcp.modules.cmhc.data_tables.schemas import DownloadLink, TableDetail, TableList

Lang = Literal["en", "fr"]


@tool
async def cmhc_dt_list_tables(category: str, lang: Lang = "en") -> TableList:
    """List CMHC's officially-published data tables in a category.

    Use for: browsing what official Excel table publications CMHC has
    for a topic, before fetching one table's detail or download link.
    `category` must be one of "rental-market", "household-
    characteristics", or "canadian-housing-survey-data-tables" (the
    last currently returns no tables - its own tables live elsewhere
    and are not yet mapped). Read docs://cmhc/well-known-categories for
    a sample of well-known table slugs in the first two categories.
    Keywords: cmhc, housing, data tables, publications, excel,
    download, rental market, household characteristics, canadian
    housing survey, catalogue, list.
    Mots-clés : schl, logement, tableaux de données, publications,
    excel, téléchargement, marché locatif, caractéristiques des
    ménages, enquête canadienne sur le logement, catalogue, liste.
    """
    return await client.list_tables(category, lang=lang)


@tool
async def cmhc_dt_get_table(category: str, slug: str, lang: Lang = "en") -> TableDetail:
    """Get one CMHC data table's description, geography/edition options, and default download link.

    Use for: confirming what a table covers and which `geography_id`/
    `edition_id` values cmhc_dt_get_download_url will accept for it,
    before requesting a specific historical edition or geography.
    `slug` comes from cmhc_dt_list_tables.
    Keywords: cmhc, housing, data table, detail, description,
    geography, edition, publication date, document type, metadata.
    Mots-clés : schl, logement, tableau de données, détail,
    description, géographie, édition, date de publication, type de
    document, métadonnées.
    """
    return await client.get_table(category, slug, lang=lang)


@tool
async def cmhc_dt_get_download_url(
    category: str,
    slug: str,
    geography_id: str | None = None,
    edition_id: str | None = None,
    lang: Lang = "en",
) -> DownloadLink:
    """Resolve one CMHC data table's official Excel download link for a geography/edition.

    Use for: getting the direct, official download URL for a specific
    published edition of a CMHC data table (e.g. October 2022 rather
    than the current default) - `geography_id`/`edition_id` come from
    cmhc_dt_get_table's `geographies`/`editions` lists; omit either to
    get the most recent edition / first geography option. Raises a
    clear error if the id is not one of that table's known options,
    rather than silently returning nothing.
    Keywords: cmhc, housing, download link, excel file, data table,
    historical edition, geography, publication, direct link, xlsx.
    Mots-clés : schl, logement, lien de téléchargement, fichier excel,
    tableau de données, édition historique, géographie, publication,
    lien direct.
    """
    return await client.get_download_url(
        category, slug, geography_id=geography_id, edition_id=edition_id, lang=lang
    )
