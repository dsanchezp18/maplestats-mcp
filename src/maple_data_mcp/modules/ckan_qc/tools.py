"""MCP tools for the Quebec Open Data (CKAN QC) module.

Every tool returns a typed Pydantic model (see schemas.py) -- FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.

`lang` is accepted on every tool for interface consistency with every
other CKAN module in this codebase, but it is a documented no-op here:
confirmed live this session that donneesquebec.ca carries no
bilingual-extension infrastructure at all (no `_translated` dict, no
`_fra`-suffixed field, anywhere), so there is nothing for `lang` to
pick between -- see client.py's module docstring for how this was
verified.

Unlike ckan_federal, ckan_qc_list_tags and ckan_qc_list_groups ARE
defined: confirmed live that this portal's tag_list (4,402 entries) and
group_list (12 entries) both return real, populated data, the opposite
of ckan_federal's confirmed-empty result for both.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ckan_qc import client
from maple_data_mcp.modules.ckan_qc.constants import (
    DATASTORE_ROWS_DEFAULT,
    SEARCH_ROWS_DEFAULT,
)
from maple_data_mcp.modules.ckan_qc.schemas import (
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
async def ckan_qc_search_datasets(
    query: str = "",
    fq: str | None = None,
    rows: int = SEARCH_ROWS_DEFAULT,
    start: int = 0,
    sort: str | None = None,
    lang: Lang = "en",
) -> PackageSearchResult:
    """Full-text/filtered search over the Quebec Open Data catalogue
    (~1,600 datasets, donneesquebec.ca).

    Use for: finding a dataset when you only know a topic, organization,
    tag, or format; the main entry point before ckan_qc_get_dataset.
    `query` empty/omitted matches every dataset (combine with `fq` to
    filter by e.g. "organization:mtq", 'tags:"Transport"', or
    "res_format:CSV"). `rows` is capped at 100 per request to keep
    results compact -- page further with `start`. `sort` accepts a Solr
    field + direction, e.g. "metadata_modified desc" (the default is
    relevance). This catalogue is effectively French-only; `lang` is
    accepted for interface consistency but has no effect.
    Keywords: ckan, open data, donneesquebec.ca, dataset search,
    catalogue, quebec, provincial, government of quebec, package_search,
    discover, browse, filter, organization, format, tags.
    Mots-clés: ckan, données ouvertes, donneesquebec.ca, recherche de
    jeux de données, catalogue, québec, provincial, gouvernement du
    québec, package_search, découvrir, parcourir, filtrer, organisme,
    format, étiquettes.
    """
    return await client.search_datasets(query, fq=fq, rows=rows, start=start, sort=sort, lang=lang)


@tool
async def ckan_qc_get_dataset(dataset_id: str, lang: Lang = "en") -> PackageDetail:
    """Get full detail for one dataset (CKAN package), including all of
    its resources (downloadable files), tags, and thematic groups.

    Use for: inspecting a specific dataset once found via
    ckan_qc_search_datasets -- resource URLs/formats, license, tags,
    thematic groups, publishing organization, update frequency, and
    spatial/temporal coverage. `dataset_id` is the dataset's id or name
    (interchangeable on this portal, confirmed live). `lang` has no
    effect (this catalogue is effectively French-only).
    Keywords: ckan, open data, dataset detail, package_show, resources,
    donneesquebec.ca, quebec, metadata, license, download, tags, groups.
    Mots-clés: ckan, données ouvertes, détail du jeu de données,
    package_show, ressources, donneesquebec.ca, québec, métadonnées,
    licence, téléchargement, étiquettes, groupes.
    """
    return await client.get_dataset(dataset_id, lang)


@tool
async def ckan_qc_list_organizations(lang: Lang = "en") -> OrganizationList:
    """List every organization publishing to the Quebec Open Data
    catalogue (~144 ministries, agencies, and municipalities).

    Use for: browsing publishers before filtering ckan_qc_search_datasets
    with fq="organization:<name>", or resolving an organization's short
    name and description. `lang` has no effect here.
    Keywords: ckan, open data, organizations, publishers, ministries,
    municipalities, quebec, list, donneesquebec.ca, catalogue.
    Mots-clés: ckan, données ouvertes, organismes, éditeurs, ministères,
    municipalités, québec, liste, donneesquebec.ca, catalogue.
    """
    return await client.list_organizations(lang)


@tool
async def ckan_qc_get_organization(organization_id: str, lang: Lang = "en") -> OrganizationDetail:
    """Get detail for one publishing organization, including its
    description and published-dataset count.

    Use for: confirming an organization's identity/description before
    filtering ckan_qc_search_datasets by it. `organization_id` is the
    organization's id or short name (e.g. "mtq" for the Ministere des
    Transports et de la Mobilite durable). `lang` has no effect here.
    Keywords: ckan, open data, organization detail, ministry, agency,
    municipality, publisher, quebec, donneesquebec.ca, organization_show.
    Mots-clés: ckan, données ouvertes, détail de l'organisme, ministère,
    agence, municipalité, éditeur, québec, donneesquebec.ca,
    organization_show.
    """
    return await client.get_organization(organization_id, lang)


@tool
async def ckan_qc_get_resource(resource_id: str, lang: Lang = "en") -> ResourceDetail:
    """Get metadata for one dataset resource (downloadable file), by its
    resource id.

    Use for: inspecting a single file's format, size, download URL, and
    whether it has a queryable CKAN datastore, without fetching its
    parent dataset's full resource list -- resource ids are found via
    ckan_qc_get_dataset. `lang` has no effect here.
    Keywords: ckan, open data, resource, file, download, format, url,
    resource_show, quebec, donneesquebec.ca, datastore.
    Mots-clés: ckan, données ouvertes, ressource, fichier, téléchargement,
    format, url, resource_show, québec, donneesquebec.ca, entrepôt de
    données.
    """
    return await client.get_resource(resource_id, lang)


@tool
async def ckan_qc_list_licenses(lang: Lang = "en") -> LicenseList:
    """List the licenses datasets on this catalogue are published under
    (e.g. Creative Commons Attribution).

    Use for: resolving a dataset's `license_id` (from
    ckan_qc_search_datasets/ckan_qc_get_dataset) to its full title, terms
    URL, and open-data-compliance flags. `lang` has no effect here.
    Keywords: ckan, open data, license, licence, creative commons,
    terms, usage rights, quebec, donneesquebec.ca, license_list.
    Mots-clés: ckan, données ouvertes, licence, creative commons,
    conditions d'utilisation, droits d'usage, québec, donneesquebec.ca,
    license_list.
    """
    return await client.list_licenses(lang)


@tool
async def ckan_qc_list_groups(lang: Lang = "en") -> GroupList:
    """List the thematic groups (subject categories) datasets on this
    catalogue are organized into (12 groups, e.g. "Transport",
    "Sante", "Environnement, ressources naturelles et energie").

    Use for: browsing this catalogue by subject area before filtering
    ckan_qc_search_datasets with fq="groups:<name>", or resolving a
    group's description and dataset count. Unlike the federal CKAN
    module, this portal genuinely uses groups. `lang` has no effect
    here.
    Keywords: ckan, open data, groups, categories, themes, subjects,
    quebec, donneesquebec.ca, group_list, browse, classification.
    Mots-clés: ckan, données ouvertes, groupes, catégories, thèmes,
    sujets, québec, donneesquebec.ca, group_list, parcourir,
    classification.
    """
    return await client.list_groups(lang)


@tool
async def ckan_qc_list_tags(query: str | None = None, lang: Lang = "en") -> TagList:
    """List or search the free-text tags used across this catalogue's
    datasets (4,402 tags total; uncontrolled, so near-duplicate
    spellings/casings coexist, e.g. "Transport"/"TRANSPORT"/"transport
    routier").

    Use for: discovering how a topic is actually tagged before filtering
    ckan_qc_search_datasets with fq='tags:"<tag>"'. Pass `query` to
    search a substring (recommended -- an unfiltered call is capped at
    200 results and `truncated` will be true). Unlike the federal CKAN
    module, this portal genuinely uses tags. `lang` has no effect here.
    Keywords: ckan, open data, tags, keywords, free-text, search,
    quebec, donneesquebec.ca, tag_list, browse, discover.
    Mots-clés: ckan, données ouvertes, étiquettes, mots-clés, texte
    libre, recherche, québec, donneesquebec.ca, tag_list, parcourir,
    découvrir.
    """
    return await client.list_tags(query, lang)


@tool
async def ckan_qc_datastore_search(
    resource_id: str,
    filters: dict[str, str] | None = None,
    query: str | None = None,
    sort: str | None = None,
    fields: str | None = None,
    limit: int = DATASTORE_ROWS_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> DatastoreSearchResult:
    """Query actual row data from one DataStore-active Quebec resource, not just its metadata.

    Use for: filtering or paging through a resource's real rows without
    downloading the whole file first. Most resources here are plain
    files, not DataStore tables -- check `datastore_active` on the
    resource (from ckan_qc_get_dataset or ckan_qc_get_resource) before
    calling this; a resource_id that is not DataStore-active raises a
    not-found error the same as an unknown one. `filters` is an
    exact-match column/value dict; `query` instead runs a full-text
    search across the resource.
    Keywords: ckan, datastore, datastore_search, row query, filter,
    Quebec, open data.
    Mots-clés : ckan, datastore, datastore_search, requête de lignes,
    filtre, Quebec, données ouvertes.
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
