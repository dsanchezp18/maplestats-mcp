"""MCP tools for Alberta Energy Regulator (AER) statistical reports."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.aer import client
from maple_data_mcp.modules.aer.schemas import (
    ProductionVolumesLink,
    WellLicenceArchiveLink,
    WellLicenceDailyReport,
)

Lang = Literal["en", "fr"]


@tool
async def aer_get_well_licences_daily(
    day: str | None = None, lang: Lang = "en"
) -> WellLicenceDailyReport:
    """Fetch AER's ST1 "Well Licences Issued - Daily List" report text for
    one weekday of the current week (well name, licence number, unique
    identifier, licensee, substance, field, and more, per licence).

    day is a weekday name ("monday".."sunday"); defaults to today in
    Alberta (America/Edmonton) time. Returns the report as raw text --
    each licence record spans 5 fixed-width lines with no column
    boundary confirmed safe to split on generically.
    Keywords: Alberta, AER, Alberta Energy Regulator, ST1, well
    licence, well licences issued, oil and gas, drilling, licensee,
    daily report, mineral rights, field.
    Mots-clés: Alberta, AER, Alberta Energy Regulator, ST1, permis de
    puits, permis délivrés, pétrole et gaz, forage, titulaire de
    permis, rapport quotidien, droits miniers, champ.
    """
    return await client.get_well_licences_daily(day, lang=lang)


@tool
async def aer_get_well_licence_archive_link(
    year: int, month: int | None = None, lang: Lang = "en"
) -> WellLicenceArchiveLink:
    """Resolve AER's ST1 well-licence archive ZIP download link for a
    given year (or one month of the current year), confirming it exists.

    Pass month (1-12) only for the current year in progress -- AER
    publishes monthly ZIPs for that year and one combined yearly ZIP
    for every prior year. Discovery-only: returns the URL and size, not
    parsed contents (these are large fixed-width archives).
    Keywords: Alberta, AER, well licence archive, ST1, historical well
    licences, ZIP, oil and gas history, monthly archive, yearly
    archive.
    Mots-clés: Alberta, AER, archive des permis de puits, ST1, permis
    historiques, archive mensuelle, archive annuelle, pétrole et gaz.
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
    Keywords: Alberta, AER, ST3, production volumes, oil, gas, NGL,
    butane, ethane, propane, sulphur, oil prices, monthly statistics,
    energy resource industry.
    Mots-clés: Alberta, AER, ST3, volumes de production, pétrole, gaz,
    LGN, butane, éthane, propane, soufre, prix du pétrole,
    statistiques mensuelles, industrie énergétique.
    """
    return await client.get_production_volumes_link(product, lang=lang)
