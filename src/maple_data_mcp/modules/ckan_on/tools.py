"""MCP tools for the Ontario Data Catalogue."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ckan_on import client
from maple_data_mcp.modules.ckan_on.constants import (
    DATASTORE_ROWS_DEFAULT,
    SEARCH_ROWS_DEFAULT,
)
from maple_data_mcp.modules.ckan_on.schemas import (
    DatastoreSearchResult,
    GroupList,
    LicenseList,
    OrganizationDetail,
    OrganizationList,
    PackageDetail,
    PackageSearchResult,
    ResourceDetail,
    TagList,
)

Lang = Literal["en", "fr"]


@tool
async def ckan_on_search_datasets(
    query: str = "",
    fq: str | None = None,
    rows: int = SEARCH_ROWS_DEFAULT,
    start: int = 0,
    sort: str | None = None,
    lang: Lang = "en",
) -> PackageSearchResult:
    """Search Ontario's bilingual open-data catalogue.

    Use for: finding Ontario datasets by topic, publisher, tag, format, or
    free-text query. Keywords: Ontario, open data, CKAN, dataset search,
    catalogue, package_search, government, province, organization, tags.
    Mots-clés: Ontario, données ouvertes, CKAN, recherche de jeux de
    données, catalogue, package_search, gouvernement, province, organisme,
    étiquettes.
    """
    return await client.search_datasets(query, fq=fq, rows=rows, start=start, sort=sort, lang=lang)


@tool
async def ckan_on_get_dataset(dataset_id: str, lang: Lang = "en") -> PackageDetail:
    """Get one Ontario dataset with translated metadata and resources.

    Use for: inspecting a dataset found with ckan_on_search_datasets.
    Keywords: Ontario, CKAN, dataset detail, package_show, resources,
    downloads, metadata, licence, publisher, bilingual, open data.
    Mots-clés: Ontario, CKAN, détail du jeu de données, package_show,
    ressources, téléchargements, métadonnées, licence, éditeur, bilingue,
    données ouvertes.
    """
    return await client.get_dataset(dataset_id, lang)


@tool
async def ckan_on_list_organizations(lang: Lang = "en") -> OrganizationList:
    """List Ontario organizations that publish datasets.

    Use for: discovering ministries and agencies before filtering search.
    Keywords: Ontario, CKAN, organizations, publishers, ministries,
    agencies, departments, catalogue, open data, organization_list.
    Mots-clés: Ontario, CKAN, organismes, éditeurs, ministères, agences,
    directions, catalogue, données ouvertes, organization_list.
    """
    return await client.list_organizations(lang)


@tool
async def ckan_on_get_organization(organization_id: str, lang: Lang = "en") -> OrganizationDetail:
    """Get one Ontario publishing organization.

    Use for: resolving an organization name, description, or dataset count.
    Keywords: Ontario, CKAN, organization detail, publisher, ministry,
    agency, organization_show, catalogue, metadata, government.
    Mots-clés: Ontario, CKAN, détail de l'organisme, éditeur, ministère,
    agence, organization_show, catalogue, métadonnées, gouvernement.
    """
    return await client.get_organization(organization_id, lang)


@tool
async def ckan_on_get_resource(resource_id: str, lang: Lang = "en") -> ResourceDetail:
    """Get metadata for one Ontario dataset resource.

    Use for: checking a file's format, URL, date range, or datastore status.
    Keywords: Ontario, CKAN, resource, file, download, format, URL,
    resource_show, datastore, date range.
    Mots-clés: Ontario, CKAN, ressource, fichier, téléchargement, format,
    URL, resource_show, entrepôt de données, plage de dates.
    """
    return await client.get_resource(resource_id, lang)


@tool
async def ckan_on_list_licenses(lang: Lang = "en") -> LicenseList:
    """List licenses used in Ontario's open-data catalogue.

    Use for: resolving license identifiers and bilingual usage terms.
    Keywords: Ontario, CKAN, license, licence, open government licence,
    terms, rights, reuse, attribution, license_list.
    Mots-clés: Ontario, CKAN, licence, licence du gouvernement ouvert,
    conditions d'utilisation, droits, réutilisation, attribution,
    license_list.
    """
    return await client.list_licenses(lang)


@tool
async def ckan_on_list_tags(lang: Lang = "en") -> TagList:
    """List Ontario's free-text dataset tags.

    Use for: discovering exact tag values for the fq filter. Keywords:
    Ontario, CKAN, tags, tag_list, keywords, subjects, vocabulary,
    catalogue, search, discover.
    Mots-clés: Ontario, CKAN, étiquettes, tag_list, mots-clés, sujets,
    vocabulaire, catalogue, recherche, découvrir.
    """
    return await client.list_tags(lang)


@tool
async def ckan_on_list_groups(lang: Lang = "en") -> GroupList:
    """List Ontario's CKAN dataset groups.

    Use for: browsing the catalogue's curated subject collections.
    Keywords: Ontario, CKAN, groups, group_list, subjects, collections,
    taxonomy, catalogue, browse, discover.
    Mots-clés: Ontario, CKAN, groupes, group_list, sujets, collections,
    taxonomie, catalogue, parcourir, découvrir.
    """
    return await client.list_groups(lang)


@tool
async def ckan_on_datastore_search(
    resource_id: str,
    filters: dict[str, str] | None = None,
    query: str | None = None,
    sort: str | None = None,
    fields: str | None = None,
    limit: int = DATASTORE_ROWS_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> DatastoreSearchResult:
    """Query actual row data from one DataStore-active Ontario resource, not just its metadata.

    Use for: filtering or paging through a resource's real rows without
    downloading the whole file first. Most resources here are plain
    files, not DataStore tables -- check `datastore_active` on the
    resource (from ckan_on_get_dataset or ckan_on_get_resource) before
    calling this; a resource_id that is not DataStore-active raises a
    not-found error the same as an unknown one. `filters` is an
    exact-match column/value dict; `query` instead runs a full-text
    search across the resource.
    Keywords: ckan, datastore, datastore_search, row query, filter,
    Ontario, open data.
    Mots-clés : ckan, datastore, datastore_search, requête de lignes,
    filtre, Ontario, données ouvertes.
    """
    return await client.datastore_search(
        resource_id,
        filters=filters,
        query=query,
        sort=sort,
        fields=fields,
        limit=limit,
        offset=offset,
        lang=lang,
    )
