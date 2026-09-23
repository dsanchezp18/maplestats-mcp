"""MCP tools for the Alberta Economic Dashboard data API.

Every tool accepts `lang` by convention; the upstream content is
English-only, so it has no effect.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.ab_economic import client, constants
from maple_data_mcp.modules.ab_economic.schemas import (
    IndicatorList,
    TableData,
    TableFields,
    TableList,
)

Lang = Literal["en", "fr"]


@tool
async def ab_economic_list_indicators(lang: Lang = "en") -> IndicatorList:
    """List the Alberta Economic Dashboard's key indicators by topic, with last-update dates.

    Use for: seeing what Alberta's government tracks (agriculture,
    consumer spending, construction, energy, jobs, business, exports,
    productivity, population, GDP) and what was updated recently. Find
    the matching data table with ab_economic_list_tables.
    Keywords: Alberta, economic dashboard, key indicators, economy,
    latest data, Government of Alberta, snapshot, updates.
    Mots-clés : Alberta, tableau de bord économique, indicateurs clés,
    économie, données récentes, gouvernement de l'Alberta, mises à jour.
    """
    del lang
    return await client.list_indicators()


@tool
async def ab_economic_list_tables(query: str | None = None, lang: Lang = "en") -> TableList:
    """List or search the Alberta Economic Dashboard's ~260 data tables.

    Use for: finding the table behind an Alberta indicator, e.g.
    query="Unemployment", "CPI", "AESO", "RigCount", "Exports", or a
    StatCan table number such as "14100287". Names ending in an 8-10
    digit number mirror that StatCan table with Alberta-focused cuts.
    Keywords: Alberta, economic data, tables, labour force, CPI,
    exports, energy, housing starts, population, rig count.
    Mots-clés : Alberta, données économiques, tableaux, population
    active, IPC, exportations, énergie, mises en chantier, population.
    """
    del lang
    return await client.list_tables(query)


@tool
async def ab_economic_get_table_fields(table: str, lang: Lang = "en") -> TableFields:
    """Get an Alberta Economic Dashboard table's columns and their filter values.

    Use for: learning which columns (GeoName, Sex, Age, Industry, ...)
    and values to pass as `filters` to ab_economic_get_data, plus the
    indicator's name and frequency.
    Keywords: Alberta, economic dashboard, table schema, columns,
    dimensions, filter values, metadata.
    Mots-clés : Alberta, tableau de bord économique, structure du
    tableau, colonnes, dimensions, valeurs de filtre, métadonnées.
    """
    del lang
    return await client.get_table_fields(table)


@tool
async def ab_economic_get_data(
    table: str,
    filters: dict[str, str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.ROWS_DEFAULT,
    lang: Lang = "en",
) -> TableData:
    """Get time-series rows from an Alberta Economic Dashboard table.

    Use for: Alberta unemployment, employment, wages, CPI, GDP, exports,
    energy production, housing and population series. Filter to one
    series with column values from ab_economic_get_table_fields, e.g.
    table="UnemploymentRates_14100287", filters={"GeoName": "Alberta",
    "Sex": "Both sexes", "Age": "15 years and over"}. Dates are
    inclusive ISO dates; the most recent `limit` rows (max 2000) come
    back oldest first.
    Keywords: Alberta, economic data, time series, unemployment rate,
    inflation, GDP, exports, oil production, Calgary, Edmonton.
    Mots-clés : Alberta, données économiques, séries chronologiques,
    taux de chômage, inflation, PIB, exportations, production pétrolière.
    """
    del lang
    return await client.get_data(
        table, filters, start_date=start_date, end_date=end_date, limit=limit
    )
