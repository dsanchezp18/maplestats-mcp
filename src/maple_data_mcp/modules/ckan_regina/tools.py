"""MCP tools for the City of Regina Open Data (CKAN Regina) module.

Unlike ckan_toronto, ckan_regina_list_groups/ckan_regina_get_group ARE
defined: confirmed live this catalogue genuinely uses CKAN groups
(curated topics such as "City Administration" and "Maps", each with a
populated dataset count), and group_list is public here (unlike
ckan_bc, where the same call needs authentication). ckan_regina_list_tags
is also defined: confirmed live tag_list returns a populated vocabulary
and sampled packages carry real tags.

`lang` is accepted on every tool per this repo's convention, but
confirmed live to have no effect: no `_translated`/`_fra`-suffixed
field exists anywhere in this portal's CKAN data.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ckan_regina import client
from maple_data_mcp.modules.ckan_regina.constants import SEARCH_ROWS_DEFAULT
from maple_data_mcp.modules.ckan_regina.schemas import (
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
async def ckan_regina_search_datasets(
    query: str = "",
    fq: str | None = None,
    rows: int = SEARCH_ROWS_DEFAULT,
    start: int = 0,
    sort: str | None = None,
    lang: Lang = "en",
) -> PackageSearchResult:
    """Full-text/filtered search over the City of Regina Open Data catalogue (~1,400 datasets).

    Use for: finding a Regina municipal dataset when you only know a
    topic, organization, format, tag, or group; the main entry point
    before ckan_regina_get_dataset. `query` empty/omitted matches
    every dataset (combine with `fq` to filter by e.g. "tags:transit",
    "res_format:CSV", or "groups:maps"). `rows` is capped at 100 per
    request — page further with `start`. `sort` accepts a Solr field +
    direction, e.g. "metadata_modified desc". `lang` is accepted for
    consistency but has no effect — this portal's data is English-only.
    Keywords: ckan, open data, openregina.ca, regina, saskatchewan,
    municipal, city government, dataset search, catalogue,
    package_search, discover, browse, filter, tags, groups, format.
    """
    return await client.search_datasets(query, fq=fq, rows=rows, start=start, sort=sort, lang=lang)


@tool
async def ckan_regina_get_dataset(dataset_id: str, lang: Lang = "en") -> PackageDetail:
    """Get full detail for one Regina dataset (CKAN package), including its resources, tags, and groups.

    Use for: inspecting a specific dataset once found via
    ckan_regina_search_datasets — resource URLs/formats, license,
    tags, groups, and update dates. `dataset_id` accepts either the
    dataset's UUID id or its slug name. `lang` has no effect.
    Keywords: ckan, open data, dataset detail, package_show, resources,
    openregina.ca, regina, municipal, metadata, license, download,
    tags, groups.
    """
    return await client.get_dataset(dataset_id, lang)


@tool
async def ckan_regina_list_organizations(lang: Lang = "en") -> OrganizationList:
    """List the organization(s) publishing to the City of Regina Open Data catalogue.

    Use for: confirming the publishing organization before filtering
    ckan_regina_search_datasets with fq="organization:<name>". This
    portal publishes through a single organization (city-of-regina).
    `lang` has no effect.
    Keywords: ckan, open data, organizations, publisher, city of
    regina, municipal, list, catalogue, openregina.ca.
    """
    return await client.list_organizations(lang)


@tool
async def ckan_regina_get_organization(
    organization_id: str, lang: Lang = "en"
) -> OrganizationDetail:
    """Get detail for the City of Regina's publishing organization, including its published-dataset count.

    Use for: confirming the organization's identity/description before
    filtering ckan_regina_search_datasets by it. `organization_id` is
    "city-of-regina" on this portal (its id or name). `lang` has no
    effect.
    Keywords: ckan, open data, organization detail, city of regina,
    municipal, publisher, organization_show, openregina.ca.
    """
    return await client.get_organization(organization_id, lang)


@tool
async def ckan_regina_get_resource(resource_id: str, lang: Lang = "en") -> ResourceDetail:
    """Get metadata for one dataset resource (downloadable file), by its resource id.

    Use for: inspecting a single file's format, size, download URL,
    and whether it is queryable through CKAN's datastore API
    (`datastore_active`) without fetching its parent dataset's full
    resource list — resource ids are found via ckan_regina_get_dataset.
    `lang` has no effect.
    Keywords: ckan, open data, resource, file, download, format, url,
    resource_show, regina, openregina.ca, datastore.
    """
    return await client.get_resource(resource_id, lang)


@tool
async def ckan_regina_list_licenses(lang: Lang = "en") -> LicenseList:
    """List the licenses datasets on this catalogue are published under.

    Use for: resolving a dataset's `license_id` (from
    ckan_regina_search_datasets/ckan_regina_get_dataset) to its full
    title, terms URL, and openness-conformance status. `lang` has no
    effect.
    Keywords: ckan, open data, license, licence, open government
    licence, terms, usage rights, regina, openregina.ca, license_list.
    """
    return await client.list_licenses(lang)


@tool
async def ckan_regina_list_tags(lang: Lang = "en") -> TagList:
    """List every tag in the City of Regina Open Data catalogue's tag vocabulary.

    Use for: browsing subject terms before filtering
    ckan_regina_search_datasets with fq="tags:<name>". `lang` has no
    effect.
    Keywords: ckan, open data, tags, tag_list, keywords, subject terms,
    regina, municipal, openregina.ca, browse, filter.
    """
    return await client.list_tags(lang)


@tool
async def ckan_regina_list_groups(lang: Lang = "en") -> GroupList:
    """List this catalogue's curated thematic groups (e.g. City Administration, Maps).

    Use for: browsing topic groups before filtering
    ckan_regina_search_datasets with fq="groups:<name>", or resolving a
    group's short name before ckan_regina_get_group. `lang` is
    accepted for consistency but has no effect.
    Keywords: ckan, open data, groups, group_list, themes, collections,
    topics, regina, openregina.ca, browse, filter.
    """
    return await client.list_groups(lang)


@tool
async def ckan_regina_get_group(group_id: str, lang: Lang = "en") -> GroupDetail:
    """Get detail for one curated thematic group, including its live dataset count.

    Use for: confirming a group's scope/description before filtering
    ckan_regina_search_datasets by it. `group_id` is the group's id or
    short name, found via ckan_regina_list_groups. `lang` has no effect.
    Keywords: ckan, open data, group detail, theme, collection, topic,
    regina, openregina.ca, group_show, curated.
    """
    return await client.get_group(group_id, lang)
