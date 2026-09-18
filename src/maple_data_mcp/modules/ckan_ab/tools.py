"""MCP tools for Open Alberta."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ckan_ab import client
from maple_data_mcp.modules.ckan_ab.constants import SEARCH_ROWS_DEFAULT
from maple_data_mcp.modules.ckan_ab.schemas import (
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
async def ckan_ab_search_datasets(
    query: str = "",
    fq: str | None = None,
    rows: int = SEARCH_ROWS_DEFAULT,
    start: int = 0,
    sort: str | None = None,
    lang: Lang = "en",
) -> PackageSearchResult:
    """Search Alberta's open-data catalogue.

    Use for: finding Alberta datasets by topic, publisher, tag, format, or
    free-text query. Keywords: Alberta, open data, CKAN, dataset search,
    catalogue, package_search, government, province, organization, tags.
    Mots-clés: Alberta, données ouvertes, CKAN, recherche de jeux de
    données, catalogue, gouvernement, province, organisme, étiquettes.
    """
    return await client.search_datasets(query, fq=fq, rows=rows, start=start, sort=sort, lang=lang)


@tool
async def ckan_ab_get_dataset(dataset_id: str, lang: Lang = "en") -> PackageDetail:
    """Get one Alberta dataset with its metadata and resources.

    Use for: inspecting a dataset found with ckan_ab_search_datasets.
    Keywords: Alberta, CKAN, dataset detail, package_show, resources,
    downloads, metadata, licence, publisher, open data.
    Mots-clés: Alberta, CKAN, détail du jeu de données, package_show,
    ressources, téléchargements, métadonnées, licence, organisme, données
    ouvertes.
    """
    return await client.get_dataset(dataset_id, lang)


@tool
async def ckan_ab_list_organizations(lang: Lang = "en") -> OrganizationList:
    """List Alberta organizations that publish datasets.

    Use for: discovering departments and agencies before filtering search.
    Keywords: Alberta, CKAN, organizations, publishers, departments,
    agencies, ministries, catalogue, open data, organization_list.
    Mots-clés: Alberta, CKAN, organismes, éditeurs, ministères, agences,
    départements, catalogue, données ouvertes, organization_list.
    """
    return await client.list_organizations(lang)


@tool
async def ckan_ab_get_organization(organization_id: str, lang: Lang = "en") -> OrganizationDetail:
    """Get one Alberta publishing organization.

    Use for: resolving an organization name, description, or dataset count.
    Keywords: Alberta, CKAN, organization detail, publisher, ministry,
    agency, organization_show, catalogue, metadata, government.
    Mots-clés: Alberta, CKAN, détail de l'organisme, éditeur, ministère,
    agence, organization_show, catalogue, métadonnées, gouvernement.
    """
    return await client.get_organization(organization_id, lang)


@tool
async def ckan_ab_get_resource(resource_id: str, lang: Lang = "en") -> ResourceDetail:
    """Get metadata for one Alberta dataset resource.

    Use for: checking a file's format, URL, size, or datastore status.
    Keywords: Alberta, CKAN, resource, file, download, format, URL,
    resource_show, datastore, open data.
    Mots-clés: Alberta, CKAN, ressource, fichier, téléchargement, format,
    URL, resource_show, entrepôt de données, données ouvertes.
    """
    return await client.get_resource(resource_id, lang)


@tool
async def ckan_ab_list_licenses(lang: Lang = "en") -> LicenseList:
    """List licenses used in Alberta's open-data catalogue.

    Use for: resolving license identifiers and usage terms. Keywords:
    Alberta, CKAN, license, licence, open government licence, terms,
    rights, reuse, attribution, license_list.
    Mots-clés: Alberta, CKAN, licence, licence de gouvernement ouvert,
    conditions d'utilisation, droits, réutilisation, attribution,
    license_list.
    """
    return await client.list_licenses(lang)


@tool
async def ckan_ab_list_tags(lang: Lang = "en") -> TagList:
    """List Alberta's free-text dataset tags.

    Use for: discovering exact tag values for the fq filter. Keywords:
    Alberta, CKAN, tags, tag_list, keywords, subjects, vocabulary,
    catalogue, search, discover.
    Mots-clés: Alberta, CKAN, étiquettes, tag_list, mots-clés, sujets,
    vocabulaire, catalogue, recherche, découvrir.
    """
    return await client.list_tags(lang)
