"""MCP tools for the City of Montreal open-data (CKAN Montreal) module.

Every tool returns a typed Pydantic model (see schemas.py) — FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.

`lang` is accepted on every tool for interface consistency with
ckan_federal, but this portal's content is French-only in practice
(confirmed live: every sampled package's flat `language` field is "FR",
no bilingual `_translated` field exists anywhere) — `lang="en"` only
changes the CKAN UI chrome behind `landing_page_url`, never the returned
data. See client.py's module docstring for exactly what was checked.

Unlike ckan_federal, ckan_montreal_list_tags/ckan_montreal_list_groups
ARE defined: confirmed live that this portal's tag_list (1,174 names)
and group_list (12 real groups) are both genuinely populated, the
opposite of federal's confirmed-empty result for both.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ckan_montreal import client
from maple_data_mcp.modules.ckan_montreal.constants import SEARCH_ROWS_DEFAULT
from maple_data_mcp.modules.ckan_montreal.schemas import (
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
async def ckan_montreal_search_datasets(
    query: str = "",
    fq: str | None = None,
    rows: int = SEARCH_ROWS_DEFAULT,
    start: int = 0,
    sort: str | None = None,
    lang: Lang = "en",
) -> PackageSearchResult:
    """Full-text/filtered search over the City of Montreal open-data
    catalogue (~404 datasets).

    Use for: finding a Montreal municipal dataset when you only know a
    topic, organization, tag, or format; the main entry point before
    ckan_montreal_get_dataset. `query` empty/omitted matches every
    dataset (combine with `fq` to filter by e.g.
    "organization:ville-de-montreal", "tags:Arbre", or "res_format:CSV").
    `rows` is capped at 100 per request to keep results compact — page
    further with `start`. `sort` accepts a Solr field + direction, e.g.
    "metadata_modified desc" (default is relevance); an unrecognized
    `sort` field is silently ignored by this portal rather than rejected.
    Content is French-only regardless of `lang`.
    Keywords: ckan, open data, donnees montreal, montreal, dataset
    search, catalogue, municipal, city, package_search, discover,
    browse, filter, organization, format, tags.
    Mots-clés: ckan, données ouvertes, données Montréal, Montréal,
    recherche de jeux de données, catalogue, municipal, ville, découvrir,
    parcourir, filtre, organisme, format, étiquettes.
    """
    return await client.search_datasets(query, fq=fq, rows=rows, start=start, sort=sort, lang=lang)


@tool
async def ckan_montreal_get_dataset(dataset_id: str, lang: Lang = "en") -> PackageDetail:
    """Get full detail for one Montreal dataset (CKAN package), including
    all of its resources (downloadable files), tags, and groups.

    Use for: inspecting a specific dataset once found via
    ckan_montreal_search_datasets — resource URLs/formats, license,
    tags, groups, publishing organization, update frequency, and update
    dates. `dataset_id` is the dataset's id (UUID) or name (URL slug) —
    unlike the federal portal, these are NOT always identical here, but
    package_show resolves either.
    Keywords: ckan, open data, dataset detail, package_show, resources,
    donnees montreal, montreal, municipal, metadata, license, download,
    tags, groups.
    Mots-clés: ckan, données ouvertes, détail du jeu de données,
    package_show, ressources, données Montréal, Montréal, municipal,
    métadonnées, licence, téléchargement, étiquettes, groupes.
    """
    return await client.get_dataset(dataset_id, lang)


@tool
async def ckan_montreal_list_organizations(lang: Lang = "en") -> OrganizationList:
    """List every organization publishing to the City of Montreal
    open-data catalogue (6 total, confirmed live — a small municipal
    roster, not a large federal-style one).

    Use for: browsing publishers before filtering
    ckan_montreal_search_datasets with fq="organization:<name>", or
    resolving an organization's short name (e.g. "ville-de-montreal",
    "bixi", "societe-de-transport-de-montreal").
    Keywords: ckan, open data, organizations, publishers, departments,
    agencies, montreal, municipal, list, donnees montreal, catalogue.
    Mots-clés: ckan, données ouvertes, organismes, éditeurs, services,
    agences, Montréal, municipal, liste, données Montréal, catalogue.
    """
    return await client.list_organizations(lang)


@tool
async def ckan_montreal_get_organization(
    organization_id: str, lang: Lang = "en"
) -> OrganizationDetail:
    """Get detail for one publishing organization, including its
    published-dataset count.

    Use for: confirming an organization's identity/description before
    filtering ckan_montreal_search_datasets by it. `organization_id` is
    the organization's id or short name (e.g. "ville-de-montreal",
    "bixi").
    Keywords: ckan, open data, organization detail, department, agency,
    publisher, montreal, municipal, donnees montreal, organization_show.
    Mots-clés: ckan, données ouvertes, détail de l'organisme, service,
    agence, éditeur, Montréal, municipal, données Montréal,
    organization_show.
    """
    return await client.get_organization(organization_id, lang)


@tool
async def ckan_montreal_get_resource(resource_id: str, lang: Lang = "en") -> ResourceDetail:
    """Get metadata for one dataset resource (downloadable file), by its
    resource id.

    Use for: inspecting a single file's format, size, and download URL
    without fetching its parent dataset's full resource list —
    resource ids are found via ckan_montreal_get_dataset.
    Keywords: ckan, open data, resource, file, download, format, url,
    resource_show, montreal, municipal, donnees montreal.
    Mots-clés: ckan, données ouvertes, ressource, fichier, téléchargement,
    format, url, resource_show, Montréal, municipal, données Montréal.
    """
    return await client.get_resource(resource_id, lang)


@tool
async def ckan_montreal_list_licenses(lang: Lang = "en") -> LicenseList:
    """List the licenses datasets on this catalogue are published under
    (e.g. Creative Commons Attribution 4.0).

    Use for: resolving a dataset's `license_id` (from
    ckan_montreal_search_datasets/ckan_montreal_get_dataset) to its full
    title, terms URL, and conformance flags.
    Keywords: ckan, open data, license, licence, creative commons,
    terms, usage rights, montreal, municipal, donnees montreal,
    license_list.
    Mots-clés: ckan, données ouvertes, licence, creative commons,
    conditions d'utilisation, droits d'usage, Montréal, municipal,
    données Montréal, license_list.
    """
    return await client.list_licenses(lang)


@tool
async def ckan_montreal_list_tags(lang: Lang = "en") -> TagList:
    """List every distinct tag (mot-clé) in use across the catalogue
    (1,174 confirmed live).

    Use for: discovering subject-matter terms to filter
    ckan_montreal_search_datasets with fq="tags:<name>" — unlike the
    federal portal, this catalogue genuinely uses CKAN tags.
    Keywords: ckan, open data, tags, mots-cles, keywords, subject,
    montreal, municipal, donnees montreal, tag_list, browse, discover.
    Mots-clés: ckan, données ouvertes, étiquettes, mots-clés, sujet,
    Montréal, municipal, données Montréal, tag_list, parcourir, découvrir.
    """
    return await client.list_tags(lang)


@tool
async def ckan_montreal_list_groups(lang: Lang = "en") -> GroupList:
    """List every subject-area group in use across the catalogue (12
    confirmed live, e.g. "Transport", "Environnement, ressources
    naturelles et énergie").

    Use for: browsing broad subject areas before filtering
    ckan_montreal_search_datasets with fq="groups:<name>" — unlike the
    federal portal, this catalogue genuinely uses CKAN groups.
    Keywords: ckan, open data, groups, subject areas, themes, domaines,
    montreal, municipal, donnees montreal, group_list, browse, discover.
    Mots-clés: ckan, données ouvertes, groupes, domaines, thèmes,
    Montréal, municipal, données Montréal, group_list, parcourir,
    découvrir.
    """
    return await client.list_groups(lang)
