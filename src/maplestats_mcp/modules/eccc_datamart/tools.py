"""MCP tools for the ECCC Data Catalogue file tree (data-donnees.az.ec.gc.ca)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.eccc_datamart import client, constants
from maplestats_mcp.modules.eccc_datamart.schemas import (
    FileRows,
    FileStructure,
    FolderListing,
    GhgrpResult,
    NpriResult,
    SearchResults,
)

Lang = Literal["en", "fr"]
Order = Literal["file", "largest"]


@tool
async def eccc_datamart_browse(
    path: str = "/",
    limit: int = constants.ENTRIES_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FolderListing:
    """List a folder of the Environment and Climate Change Canada Data Catalogue.

    Use for: walking ECCC's open data file tree at data-donnees.az.ec.gc.ca: top
    folders air, climate, ice, instruments, managementoversight, partnerships,
    regulatee, sites, species, substances, water and weather; dataset folders such as
    the National Pollutant Release Inventory (NPRI), Greenhouse Gas Reporting Program
    (GHGRP), National Air Pollution Surveillance (NAPS) year folders from 1974, oil
    sands monitoring. Each entry has its kind (folder, table,
    documentation, archive, other), bilingual display name, size as listed (rounded,
    e.g. 36 MiB), modified date, whether eccc_datamart_read_file can read it, and the
    download link. The folder's open.canada.ca record is linked when it has one.
    `path` is a folder path ("/substances/monitor"), or a catalogue page or file URL.
    Licence: Open Government Licence - Canada (commercial use allowed, attribution).
    `lang` picks the display names.
    Keywords: ECCC, Environment Canada, data catalogue, Data Mart, file tree, browse
    folder, NPRI, GHGRP, NAPS, oil sands monitoring, open data files, downloads.
    Mots-clés : Environnement et Changement climatique Canada, ECCC, Environnement
    Canada, catalogue de données, arborescence de fichiers, parcourir un dossier, INRP, PDGES, SNPA, surveillance des sables
    bitumineux, fichiers de données ouvertes, téléchargements.
    """
    return await client.browse(path=path, limit=limit, offset=offset, lang=lang)


@tool
async def eccc_datamart_search(
    query: str,
    topic: str | None = None,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> SearchResults:
    """Search the ECCC Data Catalogue's dataset folders by words (English or French).

    Use for: finding which folder of data-donnees.az.ec.gc.ca holds a dataset:
    pollutant releases, greenhouse gas emissions, air pollutant emissions inventory,
    acid rain and precipitation chemistry, mercury, oil sands rivers and lakes,
    benthic invertebrates, fish contaminants, seabirds and species at risk, sea ice,
    climate scenarios. Matches words (prefixes count) against folder names and their
    English and French titles across the first three levels (topic / function /
    dataset, about 500 folders); `topic` keeps one top folder (substances, air,
    climate, species, sites, ice, weather...). The folder list is built from about
    60 listings on first use and kept for a day. Then open a hit with
    eccc_datamart_browse.
    Keywords: ECCC data catalogue search, find dataset, environmental data, pollutant,
    emissions, oil sands monitoring, wildlife, contaminants, research data.
    Mots-clés : recherche dans le catalogue de données d'ECCC, trouver un jeu de
    données, données environnementales, polluants, émissions, qualité de l'air, qualité
    de l'eau, faune, contaminants, Environnement et Changement climatique Canada.
    """
    return await client.search(query=query, topic=topic, limit=limit, lang=lang)


@tool
async def eccc_datamart_describe_file(
    path: str, sheet: str | None = None, lang: Lang = "en"
) -> FileStructure:
    """Describe a CSV or Excel file of the ECCC Data Catalogue before reading it.

    Use for: seeing a file's sheets with declared size, the guessed header row,
    column names and the first rows, plus the read-me, data dictionary and metadata
    files of the same folder (with the start of a small CSV or TXT read-me, such as the
    GHGRP 'Lisez Moi - Read Me' notes). `path` is a file path from
    eccc_datamart_browse (or its download URL). Reads .csv, .tsv, .txt, .xlsx and .xls
    files up to 40 MB, in UTF-8 or Windows-1252. ZIP archives (NAPS integrated data,
    the 175 MB NPRI database), Word data dictionaries, PDFs and images are not opened:
    the error gives their download link. Licence: Open Government Licence - Canada.
    Keywords: ECCC, describe file, columns, header, sheets, CSV, Excel, data
    dictionary, read me, metadata, preview.
    Mots-clés : Environnement et Changement climatique Canada, ECCC, décrire un fichier, colonnes, en-tête, feuilles, CSV, Excel,
    dictionnaire de données, lisez-moi, métadonnées, aperçu.
    """
    return await client.describe_file(path=path, sheet=sheet, lang=lang)


@tool
async def eccc_datamart_read_file(
    path: str,
    sheet: str | None = None,
    columns: list[str] | None = None,
    filters: dict[str, str] | None = None,
    contains: str | None = None,
    header_row: int | None = None,
    header_rows: int = 1,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> FileRows:
    """Read rows of a CSV or Excel file in the ECCC Data Catalogue.

    Use for: getting the values in any ECCC table file: NPRI ten-year tables by
    province, industry and substance, GHGRP data tables, air pollutant emissions
    inventory, oil sands monitoring results, NAPS annual summaries, research data
    files. `path` comes from eccc_datamart_browse. `columns` picks columns, `filters`
    keeps rows whose column equals the value (case-insensitive), `contains` keeps rows
    with that text anywhere, `offset` and `limit` page (total_rows counts every
    match). `header_row` (1-based) and `header_rows` (1 to 5) fix headers the guess
    misses. Values come back as text, as published. Files up to 40 MB (the 34-38 MB
    NPRI single-year CSVs fit; prefer the CSV copy over the XLSX one, it reads much
    faster); larger files, ZIP archives and non-table files are refused with their
    download link. Licence: Open Government Licence - Canada, attribution included.
    Keywords: ECCC, read file, rows, CSV, Excel, filter, environmental data, emissions
    table, monitoring data, Data Mart.
    Mots-clés : Environnement et Changement climatique Canada, ECCC, lire un fichier, lignes, CSV, Excel, filtre, données
    environnementales, tableau des émissions, données de surveillance.
    """
    return await client.read_file(
        path=path,
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


@tool
async def eccc_datamart_npri_facilities(
    year: int | None = None,
    facility: str | None = None,
    company: str | None = None,
    province: str | None = None,
    substance: str | None = None,
    naics: str | None = None,
    npri_id: str | None = None,
    order: Order = "file",
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> NpriResult:
    """Look up National Pollutant Release Inventory (NPRI) data by facility and substance.

    Use for: pollutant releases to air, water and land, disposals and transfers
    reported by a facility or company in one year (single-year tables, 2020 to the
    latest, default latest): which substances a plant or mine released, the largest
    emitters of a substance (PM2.5, nitrogen oxides, sulphur dioxide, mercury, VOCs)
    in a province, facilities in a NAICS industry. Filters: `facility` and `company`
    (words in the name, accents ignored), `province` (code or name), `substance`
    (name in English or French, or CAS number), `naics` (code prefix), `npri_id`.
    `order` largest ranks by grand total in tonnes. Each record gives units (tonnes,
    kg, grams, g TEQ), air, water, land and road dust, disposals, transfers and grand
    total, NAICS and coordinates. Years 1993-2019 are only in bulk files too large for
    this reader (the note says where). Reads a 34-38 MB CSV, so the first call takes
    about 30 seconds. Licence: Open Government Licence - Canada.
    Keywords: NPRI, National Pollutant Release Inventory, pollutant releases, facility
    emissions, air emissions, toxic substances, disposals, transfers, industrial
    polluters.
    Mots-clés : INRP, Inventaire national des rejets de polluants, rejets de polluants,
    émissions des installations, émissions atmosphériques, substances toxiques,
    éliminations, transferts, pollueurs industriels, Environnement et Changement
    climatique Canada (ECCC).
    """
    return await client.npri_facilities(
        year=year,
        facility=facility,
        company=company,
        province=province,
        substance=substance,
        naics=naics,
        npri_id=npri_id,
        order=order,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def eccc_datamart_ghgrp_facilities(
    year: int | None = None,
    year_to: int | None = None,
    facility: str | None = None,
    company: str | None = None,
    province: str | None = None,
    naics: str | None = None,
    ghgrp_id: str | None = None,
    npri_id: str | None = None,
    order: Order = "file",
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> GhgrpResult:
    """Look up Greenhouse Gas Reporting Program (GHGRP) facility emissions, 2004 onward.

    Use for: greenhouse gas emissions of large emitters by facility and year: a
    facility's emissions over time, the largest emitters in a province or industry
    (oil sands, refineries, cement, steel, power plants, pipelines), emissions by gas
    (CO2, CH4, N2O, HFC, PFC, SF6, in tonnes CO2e) and total CO2e. Filters: `year`
    (or `year` to `year_to`; default every year), `facility` and `company` (words in
    the name, legal or trade), `province` (code or name), `naics` (code prefix),
    `ghgrp_id` (e.g. G10001), `npri_id`. `order` largest ranks by total CO2e;
    total_co2e_sum adds up every match. Facility public contact details in the file
    are left out. Licence: Open Government Licence - Canada.
    Keywords: GHGRP, greenhouse gas emissions, facility emissions, large emitters, CO2,
    methane, carbon dioxide equivalent, climate, industrial emissions, oil sands.
    Mots-clés : PDGES, émissions de gaz à effet de serre, GES par installation, grands
    émetteurs, CO2, méthane, équivalent dioxyde de carbone, climat, émissions
    industrielles, sables bitumineux, Programme de déclaration des gaz à effet de
    serre, Environnement et Changement climatique Canada (ECCC).
    """
    return await client.ghgrp_facilities(
        year=year,
        year_to=year_to,
        facility=facility,
        company=company,
        province=province,
        naics=naics,
        ghgrp_id=ghgrp_id,
        npri_id=npri_id,
        order=order,
        limit=limit,
        offset=offset,
        lang=lang,
    )
