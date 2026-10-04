"""MCP tools for Ontario Energy Board (OEB) open data."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.oeb import client
from maplestats_mcp.modules.oeb.schemas import DatasetDetail, DatasetList, QueryResult, RatesTable

Lang = Literal["en", "fr"]
RateTable = Literal[
    "electricity_residential",
    "electricity_general_service",
    "natural_gas_residential",
    "rpp_time_of_use",
    "rpp_tiered",
    "rpp_ultra_low_overnight",
]


@tool
async def oeb_list_datasets(query: str | None = None, lang: Lang = "en") -> DatasetList:
    """List the Ontario Energy Board's open data datasets, with description, file
    types, update frequency, last-updated date and number of current and archived
    files; `query` keeps those whose title or description has every word.

    Covers the 43 dataset pages of oeb.ca's open data page (RRR filings of
    electricity distributors, transmitters and natural gas distributors,
    scorecards, complaints, current and historical rates, rates databases,
    licences, applications, cost awards, expenses) and the 2021 yearbook
    workbooks (slug yearbook-electricity-distributors-2021). The first call
    reads every page (about 15 s); later calls are cached for six hours.
    Use for: finding which OEB file holds Ontario utility reliability,
    customers, revenue, capital, labour, billing or low-income data.
    Keywords: Ontario Energy Board, OEB, open data, RRR, reporting and
    record-keeping requirements, electricity distributors, local distribution
    company, LDC, natural gas utilities, yearbook, utility datasets.
    Mots-clés : Commission de l'énergie de l'Ontario, CEO, données ouvertes,
    exigences de rapport et de tenue de dossiers, distributeurs
    d'électricité, sociétés de distribution locale, services publics
    d'électricité, services publics de gaz naturel, annuaire des
    distributeurs, jeux de données des services publics, Ontario.
    """
    return await client.list_datasets(query, lang=lang)


@tool
async def oeb_describe_dataset(
    dataset: str,
    file: str | None = None,
    release: str | None = None,
    sheet: str | None = None,
    lang: Lang = "en",
) -> DatasetDetail:
    """Describe one OEB open data dataset: its files (numbered, with release:
    'current' or the date of an archived release) and, for one file, the fields
    with example values, the record count, the years and the distributors.

    dataset is a slug from oeb_list_datasets or words of its title ("system
    reliability", "2.1.5.4"). file is a number from the file list or words of
    the file name (default: the first current file); release picks an archived
    release by date ("2024-08-27"); sheet picks an Excel worksheet. Reads the
    whole file (the largest, the trial balance, is 62 MB).
    Use for: seeing which measures an RRR file has before querying it.
    Keywords: OEB, Ontario Energy Board, dataset fields, columns, RRR file,
    data dictionary, archived release, distributors list, years covered.
    Mots-clés : CEO, Commission de l'énergie de l'Ontario, champs, colonnes,
    variables, fichier RRR, dictionnaire de données, publication archivée,
    liste des distributeurs, années couvertes, description du jeu de
    données.
    """
    return await client.describe_dataset(dataset, file, release, sheet, lang=lang)


@tool
async def oeb_query_dataset(
    dataset: str,
    distributor: str | None = None,
    year: int | None = None,
    fields: list[str] | None = None,
    where: dict[str, str] | None = None,
    file: str | None = None,
    release: str | None = None,
    sheet: str | None = None,
    max_rows: int = 100,
    lang: Lang = "en",
) -> QueryResult:
    """Read rows of an OEB open data file, filtered by distributor name, year and
    other columns, with the measures you name: e.g. SAIDI and SAIFI of Hydro
    Ottawa in 2024, customers by rate class, revenue, FTEs, LEAP grants.

    distributor matches every word in the company name (current or historical
    name); year matches the Year/Fiscal Year column; fields keeps the company,
    year and the columns whose names contain each entry ("SAIDI",
    "Total Customers"); where is {column: value}, exact match ignoring case
    ({"Cause of Interruption": "Tree Contacts"}). dataset, file, release and
    sheet as in oeb_describe_dataset. Returns at most max_rows (1-1000) rows and
    the total count.
    Use for: Ontario electricity and gas utility statistics by company and year.
    Keywords: Ontario utility reliability, SAIDI, SAIFI, power outages,
    distributor customers, demand and revenue, capital expenditures, labour
    FTE, billing accuracy, LEAP, OESP, net metering, scorecard, OEB.
    Mots-clés : fiabilité des services publics ontariens, fiabilité du
    réseau électrique, SAIDI, SAIFI, pannes de courant, interruptions de
    service, clients des distributeurs, demande et revenus, dépenses en
    immobilisations, effectifs, exactitude de la facturation, facturation
    nette, fiche de rendement, CEO.
    """
    return await client.query_dataset(
        dataset,
        file,
        release,
        distributor,
        year,
        fields,
        where,
        sheet,
        max_rows,
        lang=lang,
    )


@tool
async def oeb_rates(
    table: RateTable,
    distributor: str | None = None,
    max_rows: int = 200,
    lang: Lang = "en",
) -> RatesTable:
    """Ontario electricity and natural gas rates from the OEB: current rates by
    utility (residential or general service under 50 kW electricity, residential
    natural gas), with each field's description and unit from the OEB's data
    keys, or the historical Regulated Price Plan prices (time-of-use, tiered,
    ultra-low overnight) by effective date.

    distributor filters the current-rate tables by every word of the utility
    name ("Toronto Hydro", "Enbridge"); the RPP tables are province-wide.
    Use for: monthly fixed charge, distribution and transmission rates of an
    Ontario utility, or how time-of-use prices changed.
    Keywords: Ontario electricity rates, hydro rates, time-of-use prices,
    TOU, tiered prices, ultra-low overnight, Regulated Price Plan, RPP,
    natural gas rates, delivery charge, distribution charge, OEB.
    Mots-clés : tarifs d'électricité de l'Ontario, prix de l'électricité,
    facture d'électricité, prix selon l'heure de consommation, prix par
    paliers, très bas prix de nuit, grille tarifaire réglementée, tarifs
    du gaz naturel, frais de livraison, frais de distribution, CEO.
    """
    return await client.get_rates(table, distributor, max_rows, lang=lang)
