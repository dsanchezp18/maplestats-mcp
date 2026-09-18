"""MCP tools for the Yukon Open Data (CKAN ckan_yt) module.

Every tool returns a typed Pydantic model (see schemas.py) — FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.

Unlike ckan_federal, this module DOES define ckan_yt_list_tags and
ckan_yt_list_groups: confirmed live that this portal's tag_list (914
names) and group_list (17 subject categories) are both genuinely
populated, and every sampled package carries non-empty tags/groups
arrays -- see client.py's module docstring for how this was verified.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ckan_yt import client
from maple_data_mcp.modules.ckan_yt.constants import SEARCH_ROWS_DEFAULT
from maple_data_mcp.modules.ckan_yt.schemas import (
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
async def ckan_yt_search_datasets(
    query: str = "",
    fq: str | None = None,
    rows: int = SEARCH_ROWS_DEFAULT,
    start: int = 0,
    sort: str | None = None,
    lang: Lang = "en",
) -> PackageSearchResult:
    """Full-text/filtered search over the Yukon Open Data catalogue
    (~3,841 datasets).

    Use for: finding a Yukon territorial government dataset when you
    only know a topic, organization, tag, or format; the main entry
    point before ckan_yt_get_dataset. `query` empty/omitted matches
    every dataset (combine with `fq` to filter by e.g.
    "organization:geomatics-yukon", "tags:mining", or
    "groups:economics-and-industry" — this portal, unlike the federal
    one, has real tags and groups; see ckan_yt_list_tags/
    ckan_yt_list_groups). `rows` is capped at 100 per request to keep
    results compact — page further with `start`. `sort` accepts a Solr
    field + direction, e.g. "metadata_modified desc" (default is
    relevance). `lang` has no effect on dataset content on this
    portal (English-only) — only on landing_page_url's chrome.
    Keywords: ckan, open data, open.yukon.ca, yukon, territorial,
    dataset search, catalogue, package_search, discover, browse,
    filter, organization, tag, group, format.
    Mots-clés: ckan, données ouvertes, open.yukon.ca, yukon, territorial,
    recherche de jeux de données, catalogue, package_search, découvrir,
    parcourir, filtrer, organisme, étiquette, groupe, format.
    """
    return await client.search_datasets(query, fq=fq, rows=rows, start=start, sort=sort, lang=lang)


@tool
async def ckan_yt_get_dataset(dataset_id: str, lang: Lang = "en") -> PackageDetail:
    """Get full detail for one dataset (CKAN package), including all of
    its resources (downloadable files), tags, and groups.

    Use for: inspecting a specific Yukon dataset once found via
    ckan_yt_search_datasets — resource URLs/formats, license,
    custodian, update frequency, tags, groups, publishing organization,
    and update dates. `dataset_id` is the dataset's id or name.
    Keywords: ckan, open data, dataset detail, package_show, resources,
    open.yukon.ca, yukon, territorial, metadata, license, custodian,
    download, tags, groups.
    Mots-clés: ckan, données ouvertes, détail du jeu de données,
    package_show, ressources, open.yukon.ca, yukon, territorial,
    métadonnées, licence, dépositaire, téléchargement, étiquettes,
    groupes.
    """
    return await client.get_dataset(dataset_id, lang)


@tool
async def ckan_yt_list_organizations(lang: Lang = "en") -> OrganizationList:
    """List every organization publishing to the Yukon Open Data
    catalogue (~25 territorial departments and agencies).

    Use for: browsing publishers before filtering
    ckan_yt_search_datasets with fq="organization:<name>", or resolving
    an organization's short name. `lang` has no effect here (this
    portal has no bilingual organization fields).
    Keywords: ckan, open data, organizations, publishers, departments,
    agencies, yukon, territorial, list, open.yukon.ca, catalogue.
    Mots-clés: ckan, données ouvertes, organismes, éditeurs, ministères,
    agences, yukon, territorial, liste, open.yukon.ca, catalogue.
    """
    return await client.list_organizations(lang)


@tool
async def ckan_yt_get_organization(organization_id: str, lang: Lang = "en") -> OrganizationDetail:
    """Get detail for one publishing organization, including its
    published-dataset count.

    Use for: confirming an organization's identity/description before
    filtering ckan_yt_search_datasets by it. `organization_id` is the
    organization's id or short name (e.g. "geomatics-yukon",
    "atipp-office").
    Keywords: ckan, open data, organization detail, department, agency,
    publisher, yukon, territorial, open.yukon.ca, organization_show.
    Mots-clés: ckan, données ouvertes, détail de l'organisme, ministère,
    agence, éditeur, yukon, territorial, open.yukon.ca,
    organization_show.
    """
    return await client.get_organization(organization_id, lang)


@tool
async def ckan_yt_get_resource(resource_id: str, lang: Lang = "en") -> ResourceDetail:
    """Get metadata for one dataset resource (downloadable file), by its
    resource id.

    Use for: inspecting a single file's format, size, and download URL
    without fetching its parent dataset's full resource list —
    resource ids are found via ckan_yt_get_dataset.
    Keywords: ckan, open data, resource, file, download, format, url,
    resource_show, yukon, territorial, open.yukon.ca.
    Mots-clés: ckan, données ouvertes, ressource, fichier,
    téléchargement, format, url, resource_show, yukon, territorial,
    open.yukon.ca.
    """
    return await client.get_resource(resource_id, lang)


@tool
async def ckan_yt_list_licenses(lang: Lang = "en") -> LicenseList:
    """List the licenses datasets on this catalogue are published under
    (e.g. the Open Government Licence - Yukon).

    Use for: resolving a dataset's `license_id` (from
    ckan_yt_search_datasets/ckan_yt_get_dataset) to its full title,
    terms URL, and openness-taxonomy fields (family, domain coverage,
    conformance status).
    Keywords: ckan, open data, license, licence, open government
    licence, terms, usage rights, yukon, territorial, open.yukon.ca,
    license_list.
    Mots-clés: ckan, données ouvertes, licence, licence du gouvernement
    ouvert, conditions d'utilisation, droits d'usage, yukon,
    territorial, open.yukon.ca, license_list.
    """
    return await client.list_licenses(lang)


@tool
async def ckan_yt_list_tags(lang: Lang = "en") -> TagList:
    """List every free-text subject tag used across the Yukon Open Data
    catalogue (~914 tags).

    Use for: discovering the actual vocabulary of subject terms before
    filtering ckan_yt_search_datasets with fq="tags:<name>". This
    portal, unlike the federal one, genuinely uses CKAN tags — every
    dataset carries several. Tag popularity/dataset counts are not
    included here; use ckan_yt_search_datasets with a tag filter to
    see how many datasets a given tag matches.
    Keywords: ckan, open data, tags, tag_list, keywords, subject terms,
    vocabulary, yukon, territorial, open.yukon.ca, browse, discover.
    Mots-clés: ckan, données ouvertes, étiquettes, tag_list, mots-clés,
    termes sujets, vocabulaire, yukon, territorial, open.yukon.ca,
    parcourir, découvrir.
    """
    return await client.list_tags(lang)


@tool
async def ckan_yt_list_groups(lang: Lang = "en") -> GroupList:
    """List every subject-category group datasets on this catalogue are
    classified into (17 broad categories, e.g. "Nature and
    environment", "Economics and industry").

    Use for: browsing this portal's primary subject taxonomy before
    filtering ckan_yt_search_datasets with
    fq="groups:<name>". This portal, unlike the federal one, genuinely
    uses CKAN groups as a top-level classification distinct from the
    free-text tag vocabulary (see ckan_yt_list_tags).
    Keywords: ckan, open data, groups, group_list, subject categories,
    taxonomy, classification, yukon, territorial, open.yukon.ca,
    browse, discover.
    Mots-clés: ckan, données ouvertes, groupes, group_list, catégories
    de sujets, taxonomie, classification, yukon, territorial,
    open.yukon.ca, parcourir, découvrir.
    """
    return await client.list_groups(lang)
