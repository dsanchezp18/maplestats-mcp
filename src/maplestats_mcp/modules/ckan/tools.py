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

from maplestats_mcp.modules.ckan import client, files
from maplestats_mcp.modules.ckan.constants import (
    DATASTORE_ROWS_DEFAULT,
    FILE_ROWS_DEFAULT,
    SEARCH_ROWS_DEFAULT,
)
from maplestats_mcp.modules.ckan.schemas import (
    CollectionDetail,
    DatastoreSearchResult,
    FileRows,
    FileStructure,
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
from maplestats_mcp.shared.envelope import raise_localized
from maplestats_mcp.shared.errors import InvalidInput

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
    Mots-clés : CKAN, portail de données ouvertes, catalogue de données,
    liste des portails, Portail du gouvernement ouvert, ouvert.canada.ca,
    Catalogue de données de l'Ontario, Données Québec, données ouvertes de
    Montréal, Colombie-Britannique, Territoires du Nord-Ouest, Yukon,
    fédéral, provincial, territorial, municipal, ville.
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
    trouver un jeu de données, catalogue de données, gouvernement ouvert,
    ouvert.canada.ca, Données Québec, Ville de Montréal,
    fédéral, provincial, municipal, découvrir, parcourir, filtre.
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
    Mots-clés : CKAN, détail du jeu de données, fiche du jeu de données,
    ressources, liens de téléchargement, télécharger les données,
    métadonnées, licence, éditeur, date de mise à jour, données ouvertes.
    """
    return await client.get_dataset(portal, dataset_id, lang)


@tool
async def ckan_list_organizations(portal: PortalKey, lang: Lang = "en") -> OrganizationList:
    """List the publishing organizations (departments, agencies, ministries) of one CKAN portal.

    Use for: browsing publishers before filtering ckan_search_datasets
    with fq="organization:<name>". Federal lists ~350 departments and
    agencies; Toronto and Regina each have one city organization.
    Keywords: CKAN, organizations, publishers, departments, agencies,
    ministries, open data, catalogue.
    Mots-clés : CKAN, organisations, éditeurs, ministères, organismes,
    organismes publics, ministères fédéraux, producteurs de données,
    liste des éditeurs, données ouvertes, catalogue.
    """
    return await client.list_organizations(portal, lang)


@tool
async def ckan_get_resource(
    portal: PortalKey, resource_id: str, lang: Lang = "en"
) -> ResourceDetail:
    """Get one CKAN resource (a single file or API endpoint within a dataset).

    Use for: a resource's download URL, format, size, dates, and whether
    it has a queryable DataStore table (`datastore_active`).
    Keywords: CKAN, resource, file, download URL, format, datastore, data
    file, CSV.
    Mots-clés : CKAN, ressource, fichier de données, lien de
    téléchargement, URL du fichier, format du fichier, taille du fichier,
    CSV, DataStore, magasin de données.
    """
    return await client.get_resource(portal, resource_id, lang)


@tool
async def ckan_list_licenses(portal: PortalKey, lang: Lang = "en") -> LicenseList:
    """List the licenses one CKAN portal publishes datasets under (e.g. Open Government Licence).

    Use for: explaining what a dataset's `license_id` permits.
    Keywords: CKAN, license, licence, open government licence, terms of use,
    open data, reuse, copyright.
    Mots-clés : CKAN, licence, licence du gouvernement ouvert, licence
    ouverte, conditions d'utilisation, droit d'auteur, réutilisation des
    données, Creative Commons, données ouvertes.
    """
    return await client.list_licenses(portal, lang)


@tool
async def ckan_list_tags(portal: PortalKey, query: str | None = None, lang: Lang = "en") -> TagList:
    """List or search one CKAN portal's tag vocabulary.

    Use for: finding the exact tag to filter searches by
    (fq="tags:<tag>"). Unfiltered lists are capped at 200; pass `query`
    for a substring match. The federal portal has no tags (use its
    `keywords` via ckan_get_dataset instead).
    Keywords: CKAN, tags, keywords, vocabulary, subjects, open data, browse,
    topics.
    Mots-clés : CKAN, mots-clés, étiquettes, vocabulaire, liste des
    mots-clés, sujets, thèmes, filtrer par mot-clé, données ouvertes,
    parcourir.
    """
    return await client.list_tags(portal, query, lang)


@tool
async def ckan_list_groups(portal: PortalKey, lang: Lang = "en") -> GroupList:
    """List one CKAN portal's curated thematic groups (topics such as health, transport).

    Use for: browsing a catalogue by theme, then filtering searches with
    fq="groups:<name>". Not available on federal, Alberta, or Toronto,
    which do not use CKAN groups.
    Keywords: CKAN, groups, themes, topics, categories, open data, browse,
    catalogue.
    Mots-clés : CKAN, groupes, groupes thématiques, thèmes, sujets,
    catégories, santé, transport, parcourir par thème, données ouvertes,
    catalogue.
    """
    return await client.list_groups(portal, lang)


@tool
async def ckan_get_organization_or_group(
    portal: PortalKey,
    kind: Literal["organization", "group"],
    collection_id: str,
    lang: Lang = "en",
) -> CollectionDetail:
    """Get one CKAN publishing organization or thematic group: description and dataset count.

    Use for: confirming a department's or agency's identity
    (kind="organization", e.g. "statcan", "nrcan-rncan" on the federal
    portal) before filtering ckan_search_datasets with
    fq="organization:<name>", or checking what a group from
    ckan_list_groups covers (kind="group") before filtering with
    fq="groups:<name>". `collection_id` is the id or short name. Groups
    are not available on federal, Alberta, or Toronto.
    Keywords: CKAN, organization detail, department, agency, publisher,
    ministry, group detail, theme, topic, category, open data, catalogue,
    subject area, dataset count.
    Mots-clés : CKAN, détail de l'organisation, ministère, organisme,
    éditeur, ministères et organismes, détail du groupe, thème, sujet,
    catégorie, données ouvertes, catalogue, domaine, nombre de jeux de
    données.
    """
    detail: OrganizationDetail | GroupDetail
    if kind == "organization":
        detail = await client.get_organization(portal, collection_id, lang)
    elif kind == "group":
        detail = await client.get_group(portal, collection_id, lang)
    else:
        raise_localized(
            InvalidInput,
            "Invalid input: ckan: kind must be 'organization' or 'group'.",
            "ckan : kind doit être 'organization' ou 'group'.",
            lang,
        )
    return CollectionDetail(kind=kind, **detail.model_dump())


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
    except Yukon and Alberta (neither has DataStore-active resources).
    Only resources with
    `datastore_active: true` work; for a file-only resource use
    ckan_read_resource. `filters` is exact-match per column,
    e.g. {"Year": "2024"}; `query` is full-text (rejected on federal
    resources over 100,000 rows — use `filters`). `sort` e.g.
    "Year desc"; `fields` a comma-separated column list; `limit` ≤ 1000.
    Rows are returned as published; `lang` sets the language of messages.
    Keywords: CKAN, datastore, rows, records, table, query, filter, data.
    Mots-clés : CKAN, DataStore, magasin de données, lignes,
    enregistrements, tableau de données, interroger un tableau, requête,
    filtrer les lignes, recherche plein texte, données tabulaires.
    """
    return await client.datastore_search(
        portal,
        resource_id,
        filters=filters,
        query=query,
        sort=sort,
        fields=fields,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def ckan_describe_resource(
    portal: PortalKey, resource_id: str, sheet: str | None = None, lang: Lang = "en"
) -> FileStructure:
    """List the sheets and columns of the Excel or CSV file behind a CKAN resource.

    Use for: looking inside a file-only dataset before reading it, on federal
    (open.canada.ca), Ontario, BC, Québec, Montréal, NWT, Yukon,
    Regina and Alberta portals (not Toronto: the portal does not permit automated file downloads). Most of their tabular datasets have no
    DataStore (`datastore_active` false), so the file is the only route to
    the numbers: ECCC wastewater indicators, CRA tax statistics and
    benefits by FSA, DFO salmon escapement, ESDC temporary foreign workers,
    ISED insolvency, Finance budget tables, Ontario tourism, education and
    agriculture workbooks, BC treasury and local-government finance, NWT
    traffic counts. `resource_id` comes from
    ckan_get_dataset; no URL is accepted, the file link is taken from the
    portal's own record and only the portal's known data hosts are downloaded.
    Returns every sheet with declared rows and columns, the guessed header
    row, other rows that look like headers (`header_row_candidates`), the
    column names and a short preview, plus the licence (a plain warning when
    it is not an open licence), organization, landing page, last-modified
    date and source URL. Reads .xlsx, legacy .xls and CSV/TSV (UTF-8 or
    Windows-1252, delimiter detected); the real format is sniffed from the
    bytes because labels are often wrong. Files over 40 MB are refused.
    Cached 2 hours; API calls are paced per portal.
    Keywords: CKAN, resource file, Excel, xlsx, xls, CSV, sheets, columns, header
    row, file-only dataset, open.canada.ca, Ontario, BC, licence.
    Mots-clés : CKAN, ressource, fichier Excel, classeur, xlsx, xls, CSV,
    feuilles, onglets, colonnes, ligne d'en-tête, aperçu du fichier, jeu de
    données sans DataStore, ouvert.canada.ca, Ontario, Colombie-Britannique,
    licence.
    """
    return await files.describe_resource(portal, resource_id, sheet, lang)


@tool
async def ckan_read_resource(
    portal: PortalKey,
    resource_id: str,
    sheet: str | None = None,
    header_row: int | None = None,
    header_rows: int = 1,
    filters: dict[str, str] | None = None,
    contains: str | None = None,
    columns: list[str] | None = None,
    limit: int = FILE_ROWS_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileRows:
    """Read rows of the Excel or CSV file behind a CKAN resource, from any CKAN portal.

    Use for: getting the numbers of a file-only dataset (no DataStore) on
    federal (open.canada.ca), Ontario, BC, Québec, Montréal, NWT,
    Yukon, Regina or Alberta (not Toronto, whose portal does not permit automated file downloads): ECCC wastewater indicators, tax filer
    statistics and child benefits by FSA, DFO salmon escapement, ESDC
    temporary foreign worker data, ISED insolvency statistics, Finance
    budget tables, Ontario tourism, education and farm finance workbooks, BC
    treasury-board and municipal finance, NWT files. `resource_id`
    comes from ckan_get_dataset (no URL is accepted). When the DataStore is
    active the rows come from it (like ckan_datastore_search) and a 404 falls
    back to the file; otherwise the file is downloaded and read: .xlsx, legacy
    .xls, CSV/TSV (UTF-8 or Windows-1252, delimiter detected), format sniffed
    from the bytes. In a multi-sheet workbook name the `sheet`; without it the
    sheet list and sizes come back with no rows, unless one sheet holds 80% of
    the cells (a notes sheet beside the table), which is then read (use
    ckan_describe_resource first). `header_row` (1-based) overrides the guessed
    header and `header_rows` (1 to 5) joins several rows into the column names.
    `columns` selects columns, `filters` keeps rows whose column equals the
    value (case-insensitive), `contains` keeps rows with that text in any cell,
    `limit` (up to 1000) and `offset` page the result; values are text as
    published. Every result carries the licence, organization, landing page,
    last-modified date, source URL and a citation line, with a plain warning
    when the licence is not open (BC Access Only, Ontario terms of use, no
    licence stated). Files over 40 MB are refused.
    Keywords: CKAN, read file, Excel, xlsx, xls, CSV, rows, filter, file-only dataset,
    wastewater, tax statistics, FSA, salmon, insolvency, budget, tourism.
    Mots-clés : CKAN, lire un fichier, fichier Excel, classeur, xlsx, xls, CSV,
    lignes, filtre, jeu de données sans DataStore, eaux usées, statistiques
    fiscales, allocation canadienne pour enfants, RTA, saumon, insolvabilité,
    travailleurs étrangers temporaires, budget, tourisme.
    """
    return await files.read_resource(
        portal,
        resource_id,
        sheet=sheet,
        header_row=header_row,
        header_rows=header_rows,
        filters=filters,
        contains=contains,
        columns=columns,
        limit=limit,
        offset=offset,
        lang=lang,
    )
