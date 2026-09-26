"""MCP tools for Canadian Grain Commission statistics.

`lang` picks the file: "fr" reads the CGC's French CSV, so labels (and the
values filters must match) are French ("Blé", "Livraisons"). Filters ignore
case and accents.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.cgc import client, constants
from maplestats_mcp.modules.cgc.schemas import (
    CgcExportsDescription,
    CgcExportsResult,
    CgcWeeklyDescription,
    CgcWeeklyResult,
    ExportDimension,
    ExportFrequency,
    WeeklyDimension,
)

Lang = Literal["en", "fr"]
Filter = str | list[str] | None


@tool
async def cgc_weekly_describe(
    crop_year: str | None = None, lang: Lang = "en"
) -> CgcWeeklyDescription:
    """List what the Canadian Grain Commission's Grain Statistics Weekly holds for a crop year.

    Use for: the first step before cgc_weekly_query: the weeks published so
    far (grain week and the Sunday it ends), and per worksheet its metrics,
    periods, grains, regions and grades. Worksheets: Primary (producer
    deliveries, shipments, stocks, condo storage by prairie province),
    Process (deliveries, shipments, milled grain and stocks at process
    elevators), Terminal Receipts, Terminal Exports, Terminal Stocks and
    Terminal Disposition (by port: Vancouver, Prince Rupert, Churchill,
    Thunder Bay, Bay & Lakes, St. Lawrence, and by grade), Primary Shipment
    Distribution, Feed Grains, Feed Grains Shipment Distribution, Producer
    Cars, Imported Grains, Summary (stocks by elevator type). `crop_year`
    is e.g. '2025-26' (August to July), from 2013-14; default: the latest.
    Values are thousands of tonnes.
    Keywords: Canadian Grain Commission, CGC, grain statistics weekly,
    GSW, crop year, grain handling, primary elevators, terminal
    elevators, grain stocks, canola, wheat.
    Mots-clés : Commission canadienne des grains, CCG, statistiques
    hebdomadaires sur le grain, campagne agricole, manutention du grain,
    silos primaires, silos terminaux, stocks de grain, canola, blé.
    """
    return await client.describe_weekly(crop_year, lang=lang)


@tool
async def cgc_weekly_query(
    worksheet: str,
    crop_year: str | None = None,
    metric: Filter = None,
    period: Filter = None,
    grain: Filter = None,
    grade: Filter = None,
    region: Filter = None,
    week_from: int | None = None,
    week_to: int | None = None,
    latest_week_only: bool = False,
    group_by: list[WeeklyDimension] | None = None,
    limit: int = constants.ROWS_DEFAULT,
    lang: Lang = "en",
) -> CgcWeeklyResult:
    """Get weekly grain deliveries, shipments, exports and stocks from the Canadian Grain Commission.

    Use for: producer deliveries of wheat, canola, barley, oats, peas or
    lentils to primary elevators by province; terminal exports and receipts
    by port (Vancouver, Prince Rupert, Thunder Bay, St. Lawrence) and grade;
    grain stocks in commercial storage; weekly or crop-year-to-date grain
    movement. `worksheet` is required (e.g. 'Primary', 'Terminal Exports',
    'Summary'; cgc_weekly_describe lists them and their values). `period`
    is 'Current Week' (that week alone) or 'Crop Year' (to date). Filters
    take one value or a list. Omit `group_by` for the published rows; pass
    it (e.g. ['grain']) to sum the other columns per week, e.g. deliveries
    over all provinces; summing requires one metric and one period.
    `latest_week_only` keeps the newest week. Rows come in week order; past
    `limit` the latest are kept. Thousands of tonnes; rows without a region
    are national totals. From crop year 2013-14; updated each Thursday.
    Keywords: grain deliveries, grain exports, grain stocks, primary
    elevator, terminal elevator, port of Vancouver, canola deliveries,
    wheat exports, crop year to date, thousand tonnes.
    Mots-clés : livraisons de grain, exportations de grain, stocks de
    grain, silo primaire, silo terminal, port de Vancouver, livraisons de
    canola, exportations de blé, campagne agricole, milliers de tonnes.
    """
    return await client.query_weekly(
        worksheet,
        crop_year=crop_year,
        lang=lang,
        metric=metric,
        period=period,
        grain=grain,
        grade=grade,
        region=region,
        week_from=week_from,
        week_to=week_to,
        latest_week_only=latest_week_only,
        group_by=group_by,
        limit=limit,
    )


@tool
async def cgc_exports_describe(lang: Lang = "en") -> CgcExportsDescription:
    """List the grains, ports and destination countries in the CGC's monthly grain exports file.

    Use for: the values cgc_exports_query filters on (42 grain names
    including imported and 'US' grains, grades, elevator types PRIMARY,
    TERMINALS and CONTAINER, port regions, world regions, about 150
    destination countries) and the months covered (January 2013 to the
    latest month, usually a few weeks behind).
    Keywords: grain exports, destination countries, export markets,
    Canadian Grain Commission, licensed facilities, container exports,
    ports, wheat, canola.
    Mots-clés : exportations de grain, pays de destination, marchés
    d'exportation, Commission canadienne des grains, installations
    agréées, conteneurs, ports, blé, canola.
    """
    return await client.describe_exports(lang=lang)


@tool
async def cgc_exports_query(
    grain: Filter = None,
    destination: Filter = None,
    region: Filter = None,
    elevator: Filter = None,
    global_region: Filter = None,
    grade: Filter = None,
    year_from: int | None = None,
    year_to: int | None = None,
    frequency: ExportFrequency = "month",
    group_by: list[ExportDimension] | None = None,
    limit: int = constants.ROWS_DEFAULT,
    lang: Lang = "en",
) -> CgcExportsResult:
    """Get monthly Canadian grain exports by grain and destination country from the Canadian Grain Commission.

    Use for: how much wheat, durum, canola, barley, oats, peas, lentils or
    soybeans Canada exported to China, Japan, the United States, Mexico or
    any other country, by month, calendar year or crop year (August to
    July), from licensed primary, terminal and container facilities, since
    January 2013. Filters take one value or a list (cgc_exports_describe
    lists them); `region` is the port region, `elevator` PRIMARY, TERMINALS
    or CONTAINER. With frequency 'month' and no `group_by`, rows are as
    published; otherwise values are summed per period over every column not
    in `group_by` (e.g. frequency='crop_year', group_by=['destination']),
    and `months` shows partial periods. Rows come in period order, largest
    first within a period; past `limit` the oldest periods are dropped.
    `total_ktonnes` sums every match. Thousands of tonnes.
    Keywords: grain exports by country, canola exports to China, wheat
    exports, export destinations, monthly exports, crop year exports,
    Canadian Grain Commission, pulse exports, lentil exports, trade.
    Mots-clés : exportations de grain par pays, exportations de canola
    vers la Chine, exportations de blé, destinations d'exportation,
    exportations mensuelles, campagne agricole, Commission canadienne des
    grains, légumineuses, lentilles, commerce.
    """
    return await client.query_exports(
        lang=lang,
        grain=grain,
        destination=destination,
        region=region,
        elevator=elevator,
        global_region=global_region,
        grade=grade,
        year_from=year_from,
        year_to=year_to,
        frequency=frequency,
        group_by=group_by,
        limit=limit,
    )
