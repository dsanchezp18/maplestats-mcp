"""MCP tools for NRCan's National Energy Use Database (OEE)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.nrcan_energy_use import client
from maplestats_mcp.modules.nrcan_energy_use.schemas import EnergyTable, ProductList, TableList

Lang = Literal["en", "fr"]


@tool
async def nrcan_energy_use_list_products(lang: Lang = "en") -> ProductList:
    """List NRCan's energy-use products: the Comprehensive Energy Use Database and energy surveys.

    Use for: choosing what to read. Surveys: Survey of Household Energy
    Use (SHEU 2019/2015, also by CMA), multi-unit residential buildings,
    commercial and institutional buildings (SCIEU), arenas, industrial
    consumption (ICE), appliance shipments. The comprehensive database
    covers energy use and GHG emissions by sector and province since 2000.
    Keywords: NRCan, energy use, energy consumption, household energy
    survey, SHEU, GHG emissions, energy efficiency, residential, buildings.
    Mots-clés : RNCan, consommation d'énergie, utilisation de l'énergie,
    enquête sur les ménages, émissions de GES, efficacité énergétique.
    """
    return await client.list_products(lang)


@tool
async def nrcan_energy_use_list_tables(
    product: str,
    sector: str | None = None,
    jurisdiction: str | None = None,
    lang: Lang = "en",
) -> TableList:
    """List the tables of one NRCan energy-use product, with titles and table keys.

    Use for: finding a table, e.g. product="sheu_2019" (household space
    heating, appliances, dwelling characteristics), or
    product="comprehensive" with sector ("res", "com", "id", "tran",
    "agr", "agg") and jurisdiction ("ca", "ab", "on", ...). Titles come
    from NRCan's English menus; read a table in French with
    nrcan_energy_use_get_table(lang="fr").
    Keywords: NRCan, energy use tables, household energy, heating,
    appliances, sector, province, energy database.
    Mots-clés : RNCan, tableaux, consommation d'énergie, chauffage,
    appareils, secteur, province, base de données.
    """
    del lang
    return await client.list_tables(product, sector, jurisdiction)


@tool
async def nrcan_energy_use_get_table(table_key: str, lang: Lang = "en") -> EnergyTable:
    """Read one NRCan energy-use table (header rows, data rows, and notes).

    Use for: household energy use by region and fuel, energy intensity,
    GHG emissions by sector and energy source over time, heating system
    shares, and commercial or industrial energy use. `table_key` comes
    from nrcan_energy_use_list_tables. `lang="fr"` returns NRCan's
    French table. Survey tables print a quality letter after each value;
    the legend is in `notes`.
    Keywords: NRCan, energy consumption, petajoules, GHG emissions,
    household energy use survey, heating, natural gas, electricity.
    Mots-clés : RNCan, consommation d'énergie, pétajoules, émissions de
    GES, enquête sur les ménages, chauffage, gaz naturel, électricité.
    """
    return await client.get_table(table_key, lang)
