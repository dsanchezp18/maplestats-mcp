"""MCP tools for the Open Alberta file reader."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.ab_opendata import client, constants
from maplestats_mcp.modules.ab_opendata.schemas import (
    DatasetDetail,
    DatasetList,
    OrganizationList,
    ResourceRows,
    ResourceStructure,
)

Lang = Literal["en", "fr"]
FormatName = Literal["xlsx", "xls", "csv"]
SortName = Literal["relevance", "modified", "title"]


@tool
async def ab_opendata_search_datasets(
    query: str | None = None,
    organization: str | None = None,
    format: FormatName | None = None,
    ogl_alberta_only: bool = False,
    sort: SortName = "relevance",
    limit: int = constants.DATASETS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> DatasetList:
    """Search Open Alberta (open.alberta.ca) datasets that have Excel or CSV files.

    Use for: finding the file behind an Alberta government number: AISH and Income
    Support caseloads, Alberta Health indicator tables, Treasury Board and Finance
    (economic review indicators at a glance, population projections), Education and
    post-secondary results, Municipal Affairs financial returns, energy royalties,
    traffic volumes and collisions, vital statistics (births, deaths). Each dataset
    shows title, ministry (organization), licence, last-modified date, update
    frequency and its resources with format, size and file URL (for
    ab_opendata_describe_resource and ab_opendata_read_resource). `query` is free
    text; `organization` is a slug (see ab_opendata_list_organizations); `format`
    keeps xlsx, xls or csv; `ogl_alberta_only` drops the rare dataset under another
    licence (those are flagged, with a plain note that other terms apply). The
    portal's DataStore has no active resources, so files are the only route to rows.
    `sort` modified or title, or an `offset`, drops the organization counts (portal limitation).
    Pace: one request per 10 seconds (portal crawl delay).
    Keywords: Open Alberta, Alberta government, open.alberta.ca, dataset search,
    Excel, CSV, AISH, Income Support, Alberta Health, Treasury Board and Finance,
    Open Government Licence Alberta, ministry.
    Mots-clés : Open Alberta, gouvernement de l'Alberta, données ouvertes Alberta,
    recherche de jeux de données, Excel, CSV, AISH, soutien du revenu, Alberta
    Health, Conseil du Trésor et Finances, Licence du gouvernement ouvert Alberta,
    ministère.
    """
    return await client.search_datasets(
        query=query,
        organization=organization,
        format=format,
        ogl_alberta_only=ogl_alberta_only,
        sort=sort,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def ab_opendata_list_organizations(
    format: FormatName | None = None, lang: Lang = "en"
) -> OrganizationList:
    """List the Alberta ministries and agencies that publish Excel or CSV datasets.

    Use for: getting the organization slug (health, treasuryboardandfinance,
    education, municipalaffairs, energy-and-minerals, assisted-living-and-social-
    services, transportation-and-economic-corridors, servicealberta, advancededucation
    and others) to pass as `organization` to ab_opendata_search_datasets, with the
    number of datasets each has with files. Ministries are renamed after
    reorganizations, so older datasets can sit under a former name.
    Keywords: Open Alberta, organizations, ministries, departments, agencies, Alberta
    Health, Treasury Board and Finance, Education, Municipal Affairs, publishers,
    dataset counts.
    Mots-clés : Open Alberta, organisations, ministères, organismes, Alberta Health,
    Conseil du Trésor et Finances, Éducation, Affaires municipales, éditeurs, nombre
    de jeux de données, gouvernement de l'Alberta.
    """
    return await client.list_organizations(format=format, lang=lang)


@tool
async def ab_opendata_get_dataset(dataset: str, lang: Lang = "en") -> DatasetDetail:
    """Get one Open Alberta dataset with every resource, its licence and update cycle.

    Use for: seeing all the files of a dataset found by ab_opendata_search_datasets
    (yearly workbooks, CSV and XLSX copies of one table, former versions), each with
    format, size, last-modified date, whether this module can read it, and the
    licence. `dataset` is the slug, the dataset id, or the open.alberta.ca/dataset
    page URL. Files that are links to other sites (regional dashboard exports, maps,
    PDFs) are listed with readable false.
    Keywords: Open Alberta, dataset, resources, files, licence, update frequency,
    metadata, Excel, CSV, Alberta government, Open Government Licence.
    Mots-clés : Open Alberta, jeu de données, ressources, fichiers, licence, fréquence
    de mise à jour, métadonnées, Excel, CSV, gouvernement de l'Alberta, Licence du
    gouvernement ouvert.
    """
    return await client.get_dataset(dataset=dataset, lang=lang)


@tool
async def ab_opendata_describe_resource(
    url: str, sheet: str | None = None, lang: Lang = "en"
) -> ResourceStructure:
    """List the sheets and columns of an Open Alberta Excel or CSV file.

    Use for: looking inside a file before reading it: every sheet name with its
    declared row and column counts, the guessed header row, the column names and the
    first rows after the header. Many Alberta workbooks open with a notes or cover
    sheet, put title rows above the table or run years across columns, so check
    this before ab_opendata_read_resource. `url` is a resource URL from
    ab_opendata_search_datasets (a /dataset/<id>/resource/<id>/download/ link on
    open.alberta.ca); .xlsx, .xls and .csv are read, and the real format is detected
    from the file because the portal's labels are sometimes wrong. The result
    carries the licence and the attribution statement to cite. Pace: one request
    per 10 seconds.
    Keywords: Open Alberta, sheets, columns, header row, Excel, xlsx, xls, CSV, file
    structure, preview, workbook, Alberta government data.
    Mots-clés : Open Alberta, feuilles, colonnes, ligne d'en-tête, Excel, xlsx, xls,
    CSV, structure d'un fichier, aperçu, classeur, données du gouvernement de
    l'Alberta.
    """
    return await client.describe_resource(url=url, sheet=sheet, lang=lang)


@tool
async def ab_opendata_read_resource(
    url: str,
    sheet: str | None = None,
    columns: list[str] | None = None,
    filters: dict[str, str] | None = None,
    contains: str | None = None,
    header_row: int | None = None,
    header_rows: int = 1,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> ResourceRows:
    """Read rows of an Open Alberta Excel (.xlsx, .xls) or CSV file.

    Use for: getting the numbers: AISH and Income Support monthly caseloads, Alberta
    Health indicators by zone, population projections, post-secondary enrolment,
    municipal financial returns and tax rates, oil sands royalty and project data,
    highway traffic volumes, live births and deaths, wildfire records. `url` is a
    resource URL from ab_opendata_search_datasets. The largest sheet (most cells; indexes and notes are skipped) is read unless
    `sheet` names another (all names come back). `header_row` is guessed (the first
    row with three filled cells) and can be set as a 1-based row number;
    `header_rows` (1 to 5) joins that many rows into the column names when a
    header spans several rows (years above labels, as in highway traffic
    volumes); layouts are kept as published, every value is text, and columns are named from the
    header (blank ones column_N). `columns` picks columns, `filters` keeps rows
    whose column equals the value exactly (case-insensitive, e.g. {"Zone":
    "Calgary"}), `contains` keeps rows with that text in any cell, and `offset` and
    `limit` page the result (total_rows counts every match). The result carries the
    licence and, for Open Government Licence - Alberta datasets, the attribution
    statement to cite. Pace: one request per 10 seconds.
    Keywords: Open Alberta, read file, Excel, xlsx, xls, CSV, rows, filter, caseload,
    population projections, traffic volume, royalties, wildfire, Alberta Health.
    Mots-clés : Open Alberta, lire un fichier, Excel, xlsx, xls, CSV, lignes, filtre,
    dossiers, projections de population, volume de circulation, redevances, feux de
    forêt, Alberta Health.
    """
    return await client.read_resource(
        url=url,
        sheet=sheet,
        columns=columns,
        filters=filters,
        contains=contains,
        header_row=header_row,
        header_rows=header_rows,
        limit=limit,
        offset=offset,
        lang=lang,
    )
