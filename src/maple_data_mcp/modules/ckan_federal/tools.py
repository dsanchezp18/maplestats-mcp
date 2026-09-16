"""MCP tools for the Government of Canada Open Data (CKAN federal) module.

Every tool returns a typed Pydantic model (see schemas.py) — FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.

No ckan_list_groups/ckan_list_tags tools are defined: confirmed live
that this portal's group_list and tag_list both return `[]`, and every
sampled package carries empty `tags`/`groups` arrays too — group_list
and tag_list would return nothing useful here (see client.py's module
docstring for how this was verified).
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ckan_federal import client
from maple_data_mcp.modules.ckan_federal.constants import SEARCH_ROWS_DEFAULT
from maple_data_mcp.modules.ckan_federal.schemas import (
    LicenseList,
    OrganizationDetail,
    OrganizationList,
    PackageDetail,
    PackageSearchResult,
    ResourceDetail,
)

Lang = Literal["en", "fr"]


@tool
async def ckan_search_datasets(
    query: str = "",
    fq: str | None = None,
    rows: int = SEARCH_ROWS_DEFAULT,
    start: int = 0,
    sort: str | None = None,
    lang: Lang = "en",
) -> PackageSearchResult:
    """Full-text/filtered search over the Government of Canada Open Data
    catalogue (~48,000 datasets).

    Use for: finding a dataset when you only know a topic, organization,
    or format; the main entry point before ckan_get_dataset. `query`
    empty/omitted matches every dataset (combine with `fq` to filter by
    e.g. "organization:statcan" or "res_format:CSV"). `rows` is capped
    at 100 per request to keep results compact — page further with
    `start`. `sort` accepts a Solr field + direction, e.g.
    "metadata_modified desc" (the default is relevance).
    Keywords: ckan, open data, open.canada.ca, dataset search, catalogue,
    federal, government of canada, package_search, discover, browse,
    filter, organization, format.
    """
    return await client.search_datasets(query, fq=fq, rows=rows, start=start, sort=sort, lang=lang)


@tool
async def ckan_get_dataset(dataset_id: str, lang: Lang = "en") -> PackageDetail:
    """Get full detail for one dataset (CKAN package), including all of
    its resources (downloadable files).

    Use for: inspecting a specific dataset once found via
    ckan_search_datasets — resource URLs/formats, license, keywords,
    publishing organization, and update dates. `dataset_id` is the
    dataset's id or name (identical on this portal, confirmed live).
    Keywords: ckan, open data, dataset detail, package_show, resources,
    open.canada.ca, federal, metadata, license, download.
    """
    return await client.get_dataset(dataset_id, lang)


@tool
async def ckan_list_organizations(lang: Lang = "en") -> OrganizationList:
    """List every organization publishing to the Government of Canada
    Open Data catalogue (~350 federal departments and agencies).

    Use for: browsing publishers before filtering ckan_search_datasets
    with fq="organization:<name>", or resolving an organization's short
    name. `lang` has no effect here (see ckan_get_organization for a
    per-language title).
    Keywords: ckan, open data, organizations, publishers, departments,
    agencies, federal, list, open.canada.ca, catalogue.
    """
    return await client.list_organizations(lang)


@tool
async def ckan_get_organization(organization_id: str, lang: Lang = "en") -> OrganizationDetail:
    """Get detail for one publishing organization, including its
    published-dataset count.

    Use for: confirming an organization's identity/description before
    filtering ckan_search_datasets by it. `organization_id` is the
    organization's id or short name (e.g. "statcan", "nrcan-rncan").
    Keywords: ckan, open data, organization detail, department, agency,
    publisher, federal, open.canada.ca, organization_show.
    """
    return await client.get_organization(organization_id, lang)


@tool
async def ckan_get_resource(resource_id: str, lang: Lang = "en") -> ResourceDetail:
    """Get metadata for one dataset resource (downloadable file), by its
    resource id.

    Use for: inspecting a single file's format, size, and download URL
    without fetching its parent dataset's full resource list —
    resource ids are found via ckan_get_dataset.
    Keywords: ckan, open data, resource, file, download, format, url,
    resource_show, federal, open.canada.ca.
    """
    return await client.get_resource(resource_id, lang)


@tool
async def ckan_list_licenses(lang: Lang = "en") -> LicenseList:
    """List the licenses datasets on this catalogue are published under
    (e.g. the Open Government Licence - Canada).

    Use for: resolving a dataset's `license_id` (from
    ckan_search_datasets/ckan_get_dataset) to its full title, terms URL,
    and open-data-compliance flags.
    Keywords: ckan, open data, license, licence, open government licence,
    terms, usage rights, federal, open.canada.ca, license_list.
    """
    return await client.list_licenses(lang)
