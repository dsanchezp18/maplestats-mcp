"""MCP tools for Canada's federal, provincial, territorial and municipal CKAN portals.

One tool family serves every CKAN catalogue via a `portal` key, the
same design as arcgis_hub_* and socrata_*: the Action API is identical
on every deployment, and one family keeps `search_tools` from returning
ten indistinguishable per-portal docstrings. The place names in each
docstring are what lets a query like "Toronto bike share data" still
find these tools.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ckan import client
from maple_data_mcp.modules.ckan.constants import DATASTORE_ROWS_DEFAULT, SEARCH_ROWS_DEFAULT
from maple_data_mcp.modules.ckan.schemas import (
    DatastoreSearchResult,
    GroupDetail,
    GroupList,
    LicenseList,
    OrganizationDetail,
    OrganizationList,
    PackageDetail,
    PackageSearchResult,
    PortalKey,
    PortalList,
    ResourceDetail,
    TagList,
)

Lang = Literal["en", "fr"]


@tool
async def ckan_list_portals(lang: Lang = "en") -> PortalList:
    """List every CKAN open-data catalogue (federal, provincial, territorial, city) and its key.

    Use for: finding the `portal` key every other ckan_ tool needs, and
    which portals support tags, groups, and row-level DataStore queries.
    Portals: federal (open.canada.ca), on (Ontario), bc (British
    Columbia), ab (Alberta), qc (Québec, Données Québec), nt (Northwest
    Territories), yt (Yukon), montreal, toronto, regina.
    Keywords: CKAN, open data portal, catalogue, federal, provincial,
    territorial, municipal, city, list portals.
    Mots-clés : CKAN, portail de données ouvertes, catalogue, fédéral,
    provincial, territorial, municipal, ville, liste des portails.
    """
    return client.list_portals(lang)


@tool
async def ckan_search_datasets(
    portal: PortalKey,
    query: str = "",
    fq: str | None = None,
    rows: int = SEARCH_ROWS_DEFAULT,
    start: int = 0,
    sort: str | None = None,
    lang: Lang = "en",
) -> PackageSearchResult:
    """Search one Canadian CKAN open-data catalogue for datasets.

    Use for: finding a dataset by topic on open.canada.ca (portal
    "federal", ~48,000 datasets incl. CRA, OSFI, Health Canada, ESDC,
    Elections Canada), Ontario, BC, Alberta, Québec, NWT, Yukon,
    Montréal, Toronto, or Regina. Empty `query` matches everything;
    narrow with Solr `fq`, e.g. "organization:statcan" or
    "res_format:CSV". `rows` ≤ 100; page with `start`. `sort` e.g.
    "metadata_modified desc". `lang` picks French titles on bilingual
    portals (federal, on); Québec and Montréal content is French-only.
    Keywords: CKAN, open data, dataset search, catalogue, government,
    federal, provincial, municipal, package_search, discover, browse.
    Mots-clés : CKAN, données ouvertes, recherche de jeux de données,
    catalogue, gouvernement, fédéral, provincial, municipal, découvrir,
    parcourir, filtre.
    """
    return await client.search_datasets(
        portal, query, fq=fq, rows=rows, start=start, sort=sort, lang=lang
    )


@tool
async def ckan_get_dataset(portal: PortalKey, dataset_id: str, lang: Lang = "en") -> PackageDetail:
    """Get one CKAN dataset's full metadata and every downloadable resource.

    Use for: resource URLs/formats, license, keywords/tags, publisher,
    update dates, and portal-specific metadata (in `extras`) for a
    dataset found with ckan_search_datasets. `dataset_id` is the id or
    name (slug). Check each resource's `datastore_active` before
    querying rows with ckan_datastore_search.
    Keywords: CKAN, dataset detail, package_show, resources, download,
    metadata, license, open data.
    Mots-clés : CKAN, détail du jeu de données, ressources,
    téléchargement, métadonnées, licence, données ouvertes.
    """
    return await client.get_dataset(portal, dataset_id, lang)


@tool
async def ckan_list_organizations(portal: PortalKey, lang: Lang = "en") -> OrganizationList:
    """List the publishing organizations (departments, agencies, ministries) of one CKAN portal.

    Use for: browsing publishers before filtering ckan_search_datasets
    with fq="organization:<name>". Federal lists ~350 departments and
    agencies; Toronto and Regina each have one city organization.
    Keywords: CKAN, organizations, publishers, departments, agencies,
    ministries, open data.
    Mots-clés : CKAN, organisations, éditeurs, ministères, organismes,
    données ouvertes.
    """
    return await client.list_organizations(portal, lang)


@tool
async def ckan_get_organization(
    portal: PortalKey, organization_id: str, lang: Lang = "en"
) -> OrganizationDetail:
    """Get one CKAN publishing organization's description and dataset count.

    Use for: confirming a department's or agency's identity before
    filtering searches by it. `organization_id` is the id or short name
    (e.g. "statcan", "nrcan-rncan" on the federal portal).
    Keywords: CKAN, organization detail, department, agency, publisher.
    Mots-clés : CKAN, détail de l'organisation, ministère, organisme,
    éditeur.
    """
    return await client.get_organization(portal, organization_id, lang)


@tool
async def ckan_get_resource(
    portal: PortalKey, resource_id: str, lang: Lang = "en"
) -> ResourceDetail:
    """Get one CKAN resource (a single file or API endpoint within a dataset).

    Use for: a resource's download URL, format, size, dates, and whether
    it has a queryable DataStore table (`datastore_active`).
    Keywords: CKAN, resource, file, download URL, format, datastore.
    Mots-clés : CKAN, ressource, fichier, URL de téléchargement, format.
    """
    return await client.get_resource(portal, resource_id, lang)


@tool
async def ckan_list_licenses(portal: PortalKey, lang: Lang = "en") -> LicenseList:
    """List the licenses one CKAN portal publishes datasets under (e.g. Open Government Licence).

    Use for: explaining what a dataset's `license_id` permits.
    Keywords: CKAN, license, licence, open government licence, terms of use.
    Mots-clés : CKAN, licence, licence du gouvernement ouvert,
    conditions d'utilisation.
    """
    return await client.list_licenses(portal, lang)


@tool
async def ckan_list_tags(portal: PortalKey, query: str | None = None, lang: Lang = "en") -> TagList:
    """List or search one CKAN portal's tag vocabulary.

    Use for: finding the exact tag to filter searches by
    (fq="tags:<tag>"). Unfiltered lists are capped at 200; pass `query`
    for a substring match. The federal portal has no tags (use its
    `keywords` via ckan_get_dataset instead).
    Keywords: CKAN, tags, keywords, vocabulary, subjects.
    Mots-clés : CKAN, mots-clés, étiquettes, vocabulaire, sujets.
    """
    return await client.list_tags(portal, query, lang)


@tool
async def ckan_list_groups(portal: PortalKey, lang: Lang = "en") -> GroupList:
    """List one CKAN portal's curated thematic groups (topics such as health, transport).

    Use for: browsing a catalogue by theme, then filtering searches with
    fq="groups:<name>". Not available on federal, Alberta, or Toronto,
    which do not use CKAN groups.
    Keywords: CKAN, groups, themes, topics, categories.
    Mots-clés : CKAN, groupes, thèmes, sujets, catégories.
    """
    return await client.list_groups(portal, lang)


@tool
async def ckan_get_group(portal: PortalKey, group_id: str, lang: Lang = "en") -> GroupDetail:
    """Get one CKAN thematic group's description and dataset count.

    Keywords: CKAN, group detail, theme, topic, category.
    Mots-clés : CKAN, détail du groupe, thème, sujet, catégorie.
    """
    return await client.get_group(portal, group_id, lang)


@tool
async def ckan_datastore_search(
    portal: PortalKey,
    resource_id: str,
    filters: dict[str, str] | None = None,
    query: str | None = None,
    sort: str | None = None,
    fields: str | None = None,
    limit: int = DATASTORE_ROWS_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> DatastoreSearchResult:
    """Query rows from a DataStore-backed CKAN resource (tabular data, not just metadata).

    Use for: reading actual records from a table on any CKAN portal
    except Yukon (no DataStore). Only resources with
    `datastore_active: true` work. `filters` is exact-match per column,
    e.g. {"Year": "2024"}; `query` is full-text (rejected on federal
    resources over 100,000 rows — use `filters`). `sort` e.g.
    "Year desc"; `fields` a comma-separated column list; `limit` ≤ 1000.
    Rows are returned as published, so `lang` has no effect.
    Keywords: CKAN, datastore, rows, records, table, query, filter, data.
    Mots-clés : CKAN, magasin de données, lignes, enregistrements,
    tableau, requête, filtre, données.
    """
    del lang
    return await client.datastore_search(
        portal,
        resource_id,
        filters=filters,
        query=query,
        sort=sort,
        fields=fields,
        limit=limit,
        offset=offset,
    )
