"""MCP tools for Alberta Energy Regulator (AER) statistical reports."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.aer import client
from maplestats_mcp.modules.aer.schemas import (
    ProductionVolumesLink,
    St98Table,
    St98TableList,
    WellLicenceArchiveLink,
    WellLicenceDailyReport,
)

Lang = Literal["en", "fr"]


@tool
async def aer_get_well_licences_daily(
    day: str | None = None, lang: Lang = "en"
) -> WellLicenceDailyReport:
    """Fetch AER's ST1 "Well Licences Issued - Daily List" report text for
    the latest date with one weekday (well name, licence number, unique
    identifier, licensee, substance, field, and more, per licence).

    day is a weekday name ("monday".."sunday"); defaults to yesterday in
    Alberta (America/Edmonton) time, the latest posted list. Each weekday
    file is replaced weekly around midnight after the day ends, so asking
    for today (or a file not yet replaced) gives last week's list: then
    `note` says so and report_date is older than expected_date. Returns
    the report as raw text --
    each licence record spans 5 fixed-width lines with no column
    boundary confirmed safe to split on generically.
    Use for: which new oil and gas wells AER licensed on a given day
    this week, and who the licensee is.
    Keywords: Alberta, AER, Alberta Energy Regulator, ST1, well
    licence, well licences issued, oil and gas, drilling, licensee,
    daily report, mineral rights, field.
    Mots-clés : Alberta, AER, Alberta Energy Regulator, organisme de
    réglementation de l'énergie de l'Alberta, ST1,
    permis de puits, nouveaux puits, permis délivrés, pétrole et gaz,
    forage, titulaire de permis, rapport quotidien, droits miniers,
    champ pétrolier.
    """
    return await client.get_well_licences_daily(day, lang=lang)


@tool
async def aer_get_well_licence_archive_link(
    year: int, month: int | None = None, lang: Lang = "en"
) -> WellLicenceArchiveLink:
    """Resolve AER's ST1 well-licence archive ZIP download link for a
    given year (or one month of the current year), confirming it exists.

    year runs from 2017 (the archive's first year) to the current year.
    Pass month (1-12) only for the current year in progress -- AER
    publishes monthly ZIPs for that year and one combined yearly ZIP
    for every prior year; a month not yet posted comes back with
    exists false and a note. Discovery-only: returns the URL and size, not
    parsed contents (these are large fixed-width archives).
    Use for: finding the download for historical Alberta well licences
    by year or month, for bulk analysis outside this server.
    Keywords: Alberta, AER, well licence archive, ST1, historical well
    licences, ZIP, oil and gas history, monthly archive, yearly
    archive.
    Mots-clés : Alberta, AER, Alberta Energy Regulator, organisme de
    réglementation de l'énergie de l'Alberta, archive
    des permis de puits, ST1, historique des permis de forage, archive
    mensuelle, archive annuelle, fichier ZIP, pétrole et gaz.
    """
    return await client.get_well_licence_archive_link(year, month, lang=lang)


@tool
async def aer_get_production_volumes_link(product: str, lang: Lang = "en") -> ProductionVolumesLink:
    """Resolve AER's ST3 current-month production-volume/price XLSX
    download link for one product, confirming it exists.

    product is one of "butane", "ethane", "gas", "ngl", "oil",
    "propane", "sulphur", "oil_prices". ST3 is released monthly, one
    month in arrears. Discovery-only: returns the URL, size, and
    last-modified date, not parsed spreadsheet rows.
    Use for: getting the latest monthly Alberta oil, gas, NGL or
    sulphur production spreadsheet, or AER's oil price workbook.
    Keywords: Alberta, AER, ST3, production volumes, oil, gas, NGL,
    butane, ethane, propane, sulphur, oil prices, monthly statistics,
    energy resource industry.
    Mots-clés : Alberta, AER, Alberta Energy Regulator, organisme de
    réglementation de l'énergie de l'Alberta, ST3,
    volumes de production, production pétrolière, gaz naturel, LGN,
    butane, éthane, propane, soufre, prix du pétrole, statistiques
    mensuelles, industrie énergétique.
    """
    return await client.get_production_volumes_link(product, lang=lang)


@tool
async def aer_st98_list_tables(
    edition: int | None = None, query: str = "", lang: Lang = "en"
) -> St98TableList:
    """List the figures and tables in AER's ST98 Alberta Energy Outlook
    data workbook for one edition (default the latest), with each one's
    title, series (with units), year range and whether it holds forecasts;
    also lists the editions (2022 to the latest).

    The workbook behind each edition's executive summary: reserves and
    resources, oil and gas prices (WTI, WCS, Henry Hub), capital
    expenditure, primary energy production, demand and removals, crude
    oil and bitumen supply, bitumen upgrading, NGLs, and drilling. query
    filters on words in the title or series ("bitumen", "price",
    "reserves"). Pass a `table` id to aer_st98_get_table for the values.
    Use for: finding which ST98 figure holds Alberta's oil sands or
    natural gas outlook, or AER's price and capital-spending forecast.
    Keywords: Alberta, AER, ST98, Alberta Energy Outlook, energy
    forecast, reserves, oil sands, bitumen, crude oil, natural gas, NGL,
    oil price, capital expenditure, supply and demand, outlook.
    Mots-clés : Alberta, AER, ST98, perspectives énergétiques de
    l'Alberta, prévisions énergétiques, réserves, sables bitumineux,
    bitume, pétrole brut, gaz naturel, LGN, prix du pétrole, dépenses en
    immobilisations, offre et demande.
    """
    return await client.list_st98_tables(edition, query=query, lang=lang)


@tool
async def aer_st98_get_table(
    table: str,
    edition: int | None = None,
    series: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    forecast: bool | None = None,
    lang: Lang = "en",
) -> St98Table:
    """Read one figure or table of AER's ST98 Alberta Energy Outlook as
    tidy rows: series, year (or month, or item), value, unit, a forecast
    flag (true from the edition year on, AER's projection; false for
    history), an estimated flag, and the edition.

    table is an id from aer_st98_list_tables ("figure_8", "table_1");
    figure numbers differ between editions, so list first. series keeps
    the columns whose label contains that text ("bitumen",
    "petajoules"); start_year/end_year bound the years; forecast=true
    keeps only forecast years, false only history. Notes carry AER's
    sources and footnotes. Values are as published (nominal dollars).
    Use for: AER's forecast of Alberta bitumen or natural gas production
    to 2035, WTI or Henry Hub price assumptions, remaining reserves,
    capital spending, or wells drilled by year.
    Keywords: Alberta, AER, ST98, Alberta Energy Outlook, forecast,
    projection, oil sands production, bitumen, crude oil, natural gas,
    reserves, WTI, Henry Hub, capital expenditure, drilling, energy
    demand.
    Mots-clés : Alberta, AER, ST98, perspectives énergétiques, prévision,
    projection, production des sables bitumineux, bitume, pétrole brut,
    gaz naturel, réserves, prix WTI, dépenses en immobilisations, forage,
    demande d'énergie.
    """
    return await client.get_st98_table(
        table,
        edition=edition,
        series=series,
        start_year=start_year,
        end_year=end_year,
        forecast=forecast,
        lang=lang,
    )
