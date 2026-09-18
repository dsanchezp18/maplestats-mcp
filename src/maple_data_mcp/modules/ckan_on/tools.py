"""MCP tools for the Ontario Data Catalogue."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ckan_on import client
from maple_data_mcp.modules.ckan_on.constants import SEARCH_ROWS_DEFAULT
from maple_data_mcp.modules.ckan_on.schemas import (
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
    """
    return await client.search_datasets(query, fq=fq, rows=rows, start=start, sort=sort, lang=lang)


@tool
async def ckan_on_get_dataset(dataset_id: str, lang: Lang = "en") -> PackageDetail:
    """Get one Ontario dataset with translated metadata and resources.

    Use for: inspecting a dataset found with ckan_on_search_datasets.
    Keywords: Ontario, CKAN, dataset detail, package_show, resources,
    downloads, metadata, licence, publisher, bilingual, open data.
    """
    return await client.get_dataset(dataset_id, lang)


@tool
async def ckan_on_list_organizations(lang: Lang = "en") -> OrganizationList:
    """List Ontario organizations that publish datasets.

    Use for: discovering ministries and agencies before filtering search.
    Keywords: Ontario, CKAN, organizations, publishers, ministries,
    agencies, departments, catalogue, open data, organization_list.
    """
    return await client.list_organizations(lang)


@tool
async def ckan_on_get_organization(organization_id: str, lang: Lang = "en") -> OrganizationDetail:
    """Get one Ontario publishing organization.

    Use for: resolving an organization name, description, or dataset count.
    Keywords: Ontario, CKAN, organization detail, publisher, ministry,
    agency, organization_show, catalogue, metadata, government.
    """
    return await client.get_organization(organization_id, lang)


@tool
async def ckan_on_get_resource(resource_id: str, lang: Lang = "en") -> ResourceDetail:
    """Get metadata for one Ontario dataset resource.

    Use for: checking a file's format, URL, date range, or datastore status.
    Keywords: Ontario, CKAN, resource, file, download, format, URL,
    resource_show, datastore, data range.
    """
    return await client.get_resource(resource_id, lang)


@tool
async def ckan_on_list_licenses(lang: Lang = "en") -> LicenseList:
    """List licenses used in Ontario's open-data catalogue.

    Use for: resolving license identifiers and bilingual usage terms.
    Keywords: Ontario, CKAN, license, licence, open government licence,
    terms, rights, reuse, attribution, license_list.
    """
    return await client.list_licenses(lang)


@tool
async def ckan_on_list_tags(lang: Lang = "en") -> TagList:
    """List Ontario's free-text dataset tags.

    Use for: discovering exact tag values for the fq filter. Keywords:
    Ontario, CKAN, tags, tag_list, keywords, subjects, vocabulary,
    catalogue, search, discover.
    """
    return await client.list_tags(lang)


@tool
async def ckan_on_list_groups(lang: Lang = "en") -> GroupList:
    """List Ontario's CKAN dataset groups.

    Use for: browsing the catalogue's curated subject collections.
    Keywords: Ontario, CKAN, groups, group_list, subjects, collections,
    taxonomy, catalogue, browse, discover.
    """
    return await client.list_groups(lang)
