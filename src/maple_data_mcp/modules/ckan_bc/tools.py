"""MCP tools for the BC Data Catalogue (CKAN BC) module.

Every tool returns a typed Pydantic model (see schemas.py) — FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.

Unlike ckan_federal, ckan_bc_list_tags/ckan_bc_list_groups/
ckan_bc_get_group ARE defined here: confirmed live that, unlike the
federal portal, this one has a real ~7,087-entry tag vocabulary and 26
real curated groups with populated datasets (see client.py's module
docstring for how this was verified).
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ckan_bc import client
from maple_data_mcp.modules.ckan_bc.constants import SEARCH_ROWS_DEFAULT
from maple_data_mcp.modules.ckan_bc.schemas import (
    GroupDetail,
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
async def ckan_bc_search_datasets(
    query: str = "",
    fq: str | None = None,
    rows: int = SEARCH_ROWS_DEFAULT,
    start: int = 0,
    sort: str | None = None,
    lang: Lang = "en",
) -> PackageSearchResult:
    """Full-text/filtered search over the BC Data Catalogue (~3,357 datasets).

    Use for: finding a dataset when you only know a topic, organization,
    tag, group, or format; the main entry point before
    ckan_bc_get_dataset. `query` empty/omitted matches every dataset
    (combine with `fq` to filter by e.g. "organization:bc-stats",
    "res_format:csv", "tags:wildfire", or "groups:census-profiles").
    `rows` is capped at 100 per request to keep results compact — page
    further with `start`. `sort` accepts a Solr field + direction, e.g.
    "metadata_modified desc" (the default is relevance). `lang` is
    accepted for interface consistency but has no effect — this portal
    is English-only.
    Keywords: ckan, open data, catalogue.data.gov.bc.ca, dataset search,
    catalogue, british columbia, bc government, province, package_search,
    discover, browse, filter, organization, format, tags, groups.
    """
    return await client.search_datasets(query, fq=fq, rows=rows, start=start, sort=sort, lang=lang)


@tool
async def ckan_bc_get_dataset(dataset_id: str, lang: Lang = "en") -> PackageDetail:
    """Get full detail for one dataset (CKAN package), including its
    resources (downloadable files), tags, and groups.

    Use for: inspecting a specific dataset once found via
    ckan_bc_search_datasets — resource URLs/formats, license, tags,
    groups, publishing organization, and update dates. `dataset_id` is
    the dataset's id or name (interchangeable, confirmed live). `lang`
    is accepted for interface consistency but has no effect — this
    portal is English-only.
    Keywords: ckan, open data, dataset detail, package_show, resources,
    catalogue.data.gov.bc.ca, british columbia, metadata, license,
    download, tags, groups, bcgw.
    """
    return await client.get_dataset(dataset_id, lang)


@tool
async def ckan_bc_list_organizations(lang: Lang = "en") -> OrganizationList:
    """List every organization that has published at least one dataset
    to the BC Data Catalogue (~164 of ~244 registered provincial
    ministries, agencies, and Crown corporations).

    Use for: browsing publishers before filtering
    ckan_bc_search_datasets with fq="organization:<name>", or resolving
    an organization's short name. `lang` is accepted for interface
    consistency but has no effect — this portal is English-only.
    Keywords: ckan, open data, organizations, publishers, ministries,
    agencies, british columbia, province, list, catalogue.data.gov.bc.ca.
    """
    return await client.list_organizations(lang)


@tool
async def ckan_bc_get_organization(organization_id: str, lang: Lang = "en") -> OrganizationDetail:
    """Get detail for one publishing organization, including its
    published-dataset count and external website.

    Use for: confirming an organization's identity/description before
    filtering ckan_bc_search_datasets by it. `organization_id` is the
    organization's id or short name (e.g. "bc-stats",
    "bc-wildfire-service"). `lang` is accepted for interface
    consistency but has no effect — this portal is English-only.
    Keywords: ckan, open data, organization detail, ministry, agency,
    publisher, british columbia, catalogue.data.gov.bc.ca,
    organization_show.
    """
    return await client.get_organization(organization_id, lang)


@tool
async def ckan_bc_get_resource(resource_id: str, lang: Lang = "en") -> ResourceDetail:
    """Get metadata for one dataset resource (downloadable file), by its
    resource id.

    Use for: inspecting a single file's format, size, storage location,
    and download URL without fetching its parent dataset's full
    resource list — resource ids are found via ckan_bc_get_dataset.
    `lang` is accepted for interface consistency but has no effect —
    this portal is English-only.
    Keywords: ckan, open data, resource, file, download, format, url,
    resource_show, british columbia, catalogue.data.gov.bc.ca, bcgw.
    """
    return await client.get_resource(resource_id, lang)


@tool
async def ckan_bc_list_licenses(lang: Lang = "en") -> LicenseList:
    """List the licenses datasets on this catalogue are published under
    (e.g. the Open Government Licence - British Columbia).

    Use for: resolving a dataset's `license_id` (from
    ckan_bc_search_datasets/ckan_bc_get_dataset) to its full title,
    terms URL, and open-data-compliance flags. `lang` is accepted for
    interface consistency but has no effect — this portal is
    English-only.
    Keywords: ckan, open data, license, licence, open government licence,
    terms, usage rights, british columbia, catalogue.data.gov.bc.ca,
    license_list.
    """
    return await client.list_licenses(lang)


@tool
async def ckan_bc_list_tags(query: str | None = None, lang: Lang = "en") -> TagList:
    """List or search this catalogue's tag vocabulary (~7,087 free-text
    tags used across datasets).

    Use for: finding the exact tag spelling to filter
    ckan_bc_search_datasets with fq="tags:<name>", or browsing what
    subject terms exist. Pass `query` (a substring match, e.g.
    "wildfire") to search a specific term — an unfiltered call is capped
    at 200 of the full vocabulary (see the response's `truncated`/
    `provenance.limits` fields) rather than returning all ~7,087 at
    once. `lang` is accepted for interface consistency but has no
    effect — this portal is English-only.
    Keywords: ckan, open data, tags, tag_list, keywords, subject terms,
    british columbia, catalogue.data.gov.bc.ca, search, vocabulary.
    """
    return await client.list_tags(query, lang)


@tool
async def ckan_bc_list_groups(lang: Lang = "en") -> GroupList:
    """List this catalogue's curated thematic groups (e.g. Census
    Profiles, Wildfire - Current Season), each with its live dataset
    count.

    Use for: browsing curated topic collections before filtering
    ckan_bc_search_datasets with fq="groups:<name>", or resolving a
    group's short name before ckan_bc_get_group. `lang` is accepted for
    interface consistency but has no effect — this portal is
    English-only.
    Keywords: ckan, open data, groups, group_list, themes, collections,
    british columbia, catalogue.data.gov.bc.ca, topics, curated.
    """
    return await client.list_groups(lang)


@tool
async def ckan_bc_get_group(group_id: str, lang: Lang = "en") -> GroupDetail:
    """Get detail for one curated thematic group, including its
    description and published-dataset count.

    Use for: confirming a group's scope/description before filtering
    ckan_bc_search_datasets by it. `group_id` is the group's id or short
    name (e.g. "census-profiles", "wildfire-current"), found via
    ckan_bc_list_groups. `lang` is accepted for interface consistency
    but has no effect — this portal is English-only.
    Keywords: ckan, open data, group detail, theme, collection, topic,
    british columbia, catalogue.data.gov.bc.ca, group_show, curated.
    """
    return await client.get_group(group_id, lang)
