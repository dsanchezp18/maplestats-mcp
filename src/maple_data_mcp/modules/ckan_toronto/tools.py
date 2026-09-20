"""MCP tools for the City of Toronto Open Data (CKAN Toronto) module.

Every tool returns a typed Pydantic model (see schemas.py) -- FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.

No ckan_toronto_list_groups tool is defined: confirmed live that this
portal's group_list returns `[]` and every sampled package carries an
empty `groups` array -- group_list would return nothing useful here.
Unlike the federal module, ckan_toronto_list_tags IS defined: confirmed
live that tag_list returns a populated 909-tag vocabulary and sampled
packages carry real tags -- see client.py's module docstring for how
this was verified.

`lang` is accepted on every tool per this repo's convention, but
confirmed live to have no effect on this deployment: no
`_translated`/`_fra`-suffixed field exists anywhere in this portal's
CKAN data (see client.py's module docstring).
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ckan_toronto import client
from maple_data_mcp.modules.ckan_toronto.constants import (
    DATASTORE_ROWS_DEFAULT,
    SEARCH_ROWS_DEFAULT,
)
from maple_data_mcp.modules.ckan_toronto.schemas import (
    DatastoreSearchResult,
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
async def ckan_toronto_search_datasets(
    query: str = "",
    fq: str | None = None,
    rows: int = SEARCH_ROWS_DEFAULT,
    start: int = 0,
    sort: str | None = None,
    lang: Lang = "en",
) -> PackageSearchResult:
    """Full-text/filtered search over the City of Toronto Open Data
    catalogue (~550 datasets).

    Use for: finding a Toronto municipal dataset when you only know a
    topic, organization, format, or tag; the main entry point before
    ckan_toronto_get_dataset. `query` empty/omitted matches every
    dataset (combine with `fq` to filter by e.g.
    "tags:cycling", "res_format:CSV", or "dataset_category:Map").
    `rows` is capped at 100 per request to keep results compact — page
    further with `start`. `sort` accepts a Solr field + direction, e.g.
    "metadata_modified desc" (the default is relevance). `lang` is
    accepted for consistency but has no effect — this portal's data is
    English-only.
    Keywords: ckan, open data, open.toronto.ca, toronto, municipal,
    city government, dataset search, catalogue, package_search,
    discover, browse, filter, tags, format.
    Mots-clés: ckan, données ouvertes, open.toronto.ca, toronto,
    municipal, administration municipale, recherche de jeux de
    données, catalogue, package_search, découvrir, parcourir, filtrer,
    étiquettes, format.
    """
    return await client.search_datasets(query, fq=fq, rows=rows, start=start, sort=sort, lang=lang)


@tool
async def ckan_toronto_get_dataset(dataset_id: str, lang: Lang = "en") -> PackageDetail:
    """Get full detail for one Toronto dataset (CKAN package), including
    all of its resources (downloadable files) and municipal-specific
    metadata (topics, refresh rate, known limitations, civic issues).

    Use for: inspecting a specific dataset once found via
    ckan_toronto_search_datasets — resource URLs/formats, license,
    tags, topics, update cadence, and stated data limitations.
    `dataset_id` accepts either the dataset's UUID id or its slug name
    (both resolve on this portal — unlike the federal module, the two
    are genuinely different strings here). `lang` has no effect.
    Keywords: ckan, open data, dataset detail, package_show, resources,
    open.toronto.ca, toronto, municipal, metadata, license, download,
    topics, limitations.
    Mots-clés: ckan, données ouvertes, détail du jeu de données,
    package_show, ressources, open.toronto.ca, toronto, municipal,
    métadonnées, licence, téléchargement, sujets, limites.
    """
    return await client.get_dataset(dataset_id, lang)


@tool
async def ckan_toronto_list_organizations(lang: Lang = "en") -> OrganizationList:
    """List the organization(s) publishing to the City of Toronto Open
    Data catalogue.

    Use for: confirming the publishing organization before filtering
    ckan_toronto_search_datasets with fq="organization:<name>". This
    portal publishes through a single organization (city-of-toronto),
    unlike the federal catalogue's ~350 departments — this tool still
    exists for interface parity and to confirm that fact rather than
    have an agent assume it. `lang` has no effect.
    Keywords: ckan, open data, organizations, publisher, city of
    toronto, municipal, list, catalogue, open.toronto.ca.
    Mots-clés: ckan, données ouvertes, organismes, éditeur, ville de
    toronto, municipal, liste, catalogue, open.toronto.ca.
    """
    return await client.list_organizations(lang)


@tool
async def ckan_toronto_get_organization(
    organization_id: str, lang: Lang = "en"
) -> OrganizationDetail:
    """Get detail for the City of Toronto's publishing organization,
    including its published-dataset count.

    Use for: confirming the organization's identity/description before
    filtering ckan_toronto_search_datasets by it. `organization_id` is
    "city-of-toronto" on this portal (its id or name). `lang` has no
    effect.
    Keywords: ckan, open data, organization detail, city of toronto,
    municipal, publisher, organization_show, open.toronto.ca.
    Mots-clés: ckan, données ouvertes, détail de l'organisme, ville de
    toronto, municipal, éditeur, organization_show, open.toronto.ca.
    """
    return await client.get_organization(organization_id, lang)


@tool
async def ckan_toronto_get_resource(resource_id: str, lang: Lang = "en") -> ResourceDetail:
    """Get metadata for one dataset resource (downloadable file), by its
    resource id.

    Use for: inspecting a single file's format, size, download URL, and
    whether it is queryable through CKAN's datastore API
    (`datastore_active`) without fetching its parent dataset's full
    resource list — resource ids are found via ckan_toronto_get_dataset.
    `lang` has no effect.
    Keywords: ckan, open data, resource, file, download, format, url,
    resource_show, datastore, toronto, open.toronto.ca.
    Mots-clés: ckan, données ouvertes, ressource, fichier,
    téléchargement, format, url, resource_show, entrepôt de données,
    toronto, open.toronto.ca.
    """
    return await client.get_resource(resource_id, lang)


@tool
async def ckan_toronto_list_licenses(lang: Lang = "en") -> LicenseList:
    """List the licenses datasets on this catalogue are published under
    (e.g. the Open Government Licence - Toronto).

    Use for: resolving a dataset's `license_id` (from
    ckan_toronto_search_datasets/ckan_toronto_get_dataset) to its full
    title, terms URL, and openness-conformance status. `lang` has no
    effect.
    Keywords: ckan, open data, license, licence, open government
    licence, terms, usage rights, toronto, open.toronto.ca,
    license_list.
    Mots-clés: ckan, données ouvertes, licence, licence du gouvernement
    ouvert, conditions d'utilisation, droits d'usage, toronto,
    open.toronto.ca, license_list.
    """
    return await client.list_licenses(lang)


@tool
async def ckan_toronto_list_tags(lang: Lang = "en") -> TagList:
    """List every tag in the City of Toronto Open Data catalogue's tag
    vocabulary (~900 tags).

    Use for: browsing subject terms before filtering
    ckan_toronto_search_datasets with fq="tags:<name>" — unlike the
    federal portal, this catalogue genuinely uses CKAN tags (confirmed
    live), so this tool has real discovery value here. `lang` has no
    effect.
    Keywords: ckan, open data, tags, tag_list, keywords, subject terms,
    toronto, municipal, open.toronto.ca, browse, filter.
    Mots-clés: ckan, données ouvertes, étiquettes, tag_list, mots-clés,
    termes sujets, toronto, municipal, open.toronto.ca, parcourir,
    filtrer.
    """
    return await client.list_tags(lang)


@tool
async def ckan_toronto_datastore_search(
    resource_id: str,
    filters: dict[str, str] | None = None,
    query: str | None = None,
    sort: str | None = None,
    fields: str | None = None,
    limit: int = DATASTORE_ROWS_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> DatastoreSearchResult:
    """Query actual row data from one DataStore-active Toronto resource, not just its metadata.

    Use for: filtering or paging through a resource's real rows without
    downloading the whole file first. Most resources here are plain
    files, not DataStore tables -- check `datastore_active` on the
    resource (from ckan_toronto_get_dataset or ckan_toronto_get_resource) before
    calling this; a resource_id that is not DataStore-active raises a
    not-found error the same as an unknown one. `filters` is an
    exact-match column/value dict; `query` instead runs a full-text
    search across the resource.
    Keywords: ckan, datastore, datastore_search, row query, filter,
    Toronto, open data.
    Mots-clés : ckan, datastore, datastore_search, requête de lignes,
    filtre, Toronto, données ouvertes.
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
