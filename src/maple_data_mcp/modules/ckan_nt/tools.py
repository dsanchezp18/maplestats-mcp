"""MCP tools for the Northwest Territories Open Data (CKAN NT) module.

Every tool returns a typed Pydantic model (see schemas.py) - FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.

`lang` is accepted on every tool for consistency with the rest of this
project (and with modules/ckan_federal/'s convention), but this portal
is English-only in practice - confirmed live: no package, resource,
organization, or license record in any sample carried a `_translated`
dict or `_fra`-suffixed field, and no `/fr/...`-prefixed path exists (both
`/fr/dataset/<id>` and `/dataset/fr/<id>` 404). `lang` therefore has no
effect on any returned value here; it is kept purely so a caller/BM25
query mentioning "fr" doesn't rule this module out, matching
modules/boc/tools.py's documented reasoning for the same situation.

ckan_nt_list_tags and ckan_nt_list_groups ARE defined here, unlike
ckan_federal, which omits both - confirmed live that this portal
genuinely uses CKAN tags (151 real tags) and groups (15 real topic
categories, each with a description and package_count), the opposite of
the federal portal's confirmed-empty result for both.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ckan_nt import client
from maple_data_mcp.modules.ckan_nt.constants import SEARCH_ROWS_DEFAULT
from maple_data_mcp.modules.ckan_nt.schemas import (
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
async def ckan_nt_search_datasets(
    query: str = "",
    fq: str | None = None,
    rows: int = SEARCH_ROWS_DEFAULT,
    start: int = 0,
    sort: str | None = None,
    lang: Lang = "en",
) -> PackageSearchResult:
    """Full-text/filtered search over the Northwest Territories Open Data
    catalogue (~341 datasets).

    Use for: finding a dataset when you only know a topic, organization,
    tag, or group; the main entry point before ckan_nt_get_dataset.
    `query` empty/omitted matches every dataset (combine with `fq` to
    filter by e.g. "organization:bureau-of-statistics", "tags:housing",
    or "groups:home-and-community" - confirmed live). `rows` is capped at
    100 per request to keep results compact - page further with `start`.
    `sort` accepts a Solr field + direction, e.g.
    "metadata_modified desc" (the default is relevance).
    Keywords: ckan, open data, opendata.gov.nt.ca, dataset search,
    catalogue, northwest territories, nwt, territorial, government,
    package_search, discover, browse, filter, organization, tag, group,
    format.
    """
    return await client.search_datasets(query, fq=fq, rows=rows, start=start, sort=sort, lang=lang)


@tool
async def ckan_nt_get_dataset(dataset_id: str, lang: Lang = "en") -> PackageDetail:
    """Get full detail for one dataset (CKAN package), including all of
    its resources (downloadable files), tags, and topic groups.

    Use for: inspecting a specific dataset once found via
    ckan_nt_search_datasets - resource URLs/formats, license, tags,
    topic groups, publishing organization, and update dates.
    `dataset_id` is the dataset's id or name (identical on this portal,
    confirmed live).
    Keywords: ckan, open data, dataset detail, package_show, resources,
    opendata.gov.nt.ca, northwest territories, nwt, territorial, metadata,
    license, tags, groups, download.
    """
    return await client.get_dataset(dataset_id, lang)


@tool
async def ckan_nt_list_organizations(lang: Lang = "en") -> OrganizationList:
    """List every organization publishing to the Northwest Territories
    Open Data catalogue (GNWT departments and agencies).

    Use for: browsing publishers before filtering ckan_nt_search_datasets
    with fq="organization:<name>", or resolving an organization's short
    name.
    Keywords: ckan, open data, organizations, publishers, departments,
    agencies, gnwt, northwest territories, nwt, territorial, list,
    opendata.gov.nt.ca, catalogue.
    """
    return await client.list_organizations(lang)


@tool
async def ckan_nt_get_organization(organization_id: str, lang: Lang = "en") -> OrganizationDetail:
    """Get detail for one publishing organization, including its
    published-dataset count.

    Use for: confirming an organization's identity/description before
    filtering ckan_nt_search_datasets by it. `organization_id` is the
    organization's id or short name (e.g. "bureau-of-statistics",
    "justice").
    Keywords: ckan, open data, organization detail, department, agency,
    publisher, gnwt, northwest territories, nwt, territorial,
    opendata.gov.nt.ca, organization_show.
    """
    return await client.get_organization(organization_id, lang)


@tool
async def ckan_nt_list_groups(lang: Lang = "en") -> GroupList:
    """List every topic group datasets on this catalogue are organized
    into (~15 groups, e.g. "Home and Community", "Business and Economy").

    Use for: browsing subject-area categories before filtering
    ckan_nt_search_datasets with fq="groups:<name>" - unlike the federal
    CKAN module, this portal genuinely uses groups (confirmed live), so
    this is real discovery value, not a stub.
    Keywords: ckan, open data, groups, topics, categories, subject areas,
    northwest territories, nwt, territorial, opendata.gov.nt.ca,
    group_list, browse.
    """
    return await client.list_groups(lang)


@tool
async def ckan_nt_list_tags(lang: Lang = "en") -> TagList:
    """List the full tag vocabulary used across this catalogue's datasets
    (~151 tags, e.g. "housing", "births", "air quality").

    Use for: discovering exact tag spellings before filtering
    ckan_nt_search_datasets with fq="tags:<name>" - unlike the federal
    CKAN module, this portal genuinely uses tags (confirmed live), so
    this is real discovery value, not a stub.
    Keywords: ckan, open data, tags, keywords, vocabulary, northwest
    territories, nwt, territorial, opendata.gov.nt.ca, tag_list, browse.
    """
    return await client.list_tags(lang)


@tool
async def ckan_nt_get_resource(resource_id: str, lang: Lang = "en") -> ResourceDetail:
    """Get metadata for one dataset resource (downloadable file), by its
    resource id.

    Use for: inspecting a single file's format, size, and download URL
    without fetching its parent dataset's full resource list - resource
    ids are found via ckan_nt_get_dataset.
    Keywords: ckan, open data, resource, file, download, format, url,
    resource_show, northwest territories, nwt, territorial,
    opendata.gov.nt.ca.
    """
    return await client.get_resource(resource_id, lang)


@tool
async def ckan_nt_list_licenses(lang: Lang = "en") -> LicenseList:
    """List the licenses datasets on this catalogue are published under
    (e.g. the Open Government Licence - Northwest Territories).

    Use for: resolving a dataset's `license_id` (from
    ckan_nt_search_datasets/ckan_nt_get_dataset) to its full title, terms
    URL, and open-data-compliance flags.
    Keywords: ckan, open data, license, licence, open government licence,
    terms, usage rights, northwest territories, nwt, territorial,
    opendata.gov.nt.ca, license_list.
    """
    return await client.list_licenses(lang)
