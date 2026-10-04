"""MCP tools for the BC Ministry of Environment monitoring files."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.bc_environment import client, constants
from maplestats_mcp.modules.bc_environment.schemas import (
    AirSeries,
    AirStationList,
    AqhiResult,
    HydroParameter,
    HydroSeries,
    HydroStationList,
    SnowSeries,
    SnowStationList,
    SnowSurveyList,
    SurveySeason,
    WellList,
    WellSeries,
    WellSeriesKind,
)

Lang = Literal["en", "fr"]


@tool
async def bc_env_list_air_stations(
    query: str | None = None,
    parameter: str | None = None,
    owner: str | None = None,
    limit: int = constants.LIST_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> AirStationList:
    """List British Columbia pollution monitoring sites reporting this hour.

    Use for: finding a BC monitoring site and its EMS id before reading its
    hourly data: about 100 stations run by the province (ENV), Metro Vancouver
    (MVRD) and industry, with city, coordinates, the parameters each measures
    (PM25, PM10, O3, NO2, SO2, TRS, H2S, CO, wind) and their units, and
    the latest hour. `query` matches name, city or EMS id; `parameter` keeps stations
    measuring it (e.g. PM25); `owner` filters ENV, MVRD or INDUSTRY.
    Keywords: British Columbia, pollution, monitoring site, PM2.5, ozone,
    nitrogen dioxide, sulphur dioxide, EMS id, Metro Vancouver, wildfire smoke.
    Mots-clés : Colombie-Britannique, qualité de l'air, station de surveillance,
    PM2,5, particules fines, ozone, dioxyde d'azote, dioxyde de soufre, fumée de feux
    de forêt, Metro Vancouver.
    """
    return await client.list_air_stations(
        query=query, parameter=parameter, owner=owner, limit=limit, lang=lang
    )


@tool
async def bc_env_get_air_station_data(
    station: str,
    parameters: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> AirSeries:
    """Hourly pollutant and weather readings at one BC monitoring site, last 30 days.

    Use for: the recent hourly record of one station (name or EMS id from
    bc_env_list_air_stations), e.g. PM2.5 during a wildfire smoke event in Kamloops
    or SO2 in Trail, reshaped from the station's wide file into one row per hour and
    parameter (newest first) with units, plus the published rolling means (PM25_24,
    O3_8, SO2_24). `parameters` keeps some columns; `start`/`end` (2026-09-15 or
    2026-09-15 08:00) filter on the hour in Pacific Standard Time (UTC-8 all year;
    time_utc is also given). Data are unverified raw values; verified history is
    only on an ftp server this tool cannot reach.
    Keywords: British Columbia, hourly pollution, PM2.5, ozone, NO2, SO2,
    station data, time series, wildfire smoke, raw data, last 30 days.
    Mots-clés : Colombie-Britannique, pollution horaire, PM2,5, ozone, NO2,
    SO2, données de station, série chronologique, fumée de feux de forêt, données
    brutes.
    """
    return await client.get_air_station_data(
        station=station, parameters=parameters, start=start, end=end, limit=limit, lang=lang
    )


@tool
async def bc_env_get_air_parameter_data(
    parameter: str,
    station: str | None = None,
    start: str | None = None,
    end: str | None = None,
    latest_only: bool = False,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> AirSeries:
    """One air pollutant or weather parameter across all BC stations, hourly.

    Use for: comparing stations for one parameter (PM25, PM10, O3, NO2, NO, NOx, SO2,
    TRS, H2S, CO, CH4, THC, NMHC, HF, or TEMP, HUMIDITY, PRECIP, PRESSURE,
    WSPD_SCLR, WDIR_VECT and other meteorology), e.g. the latest PM2.5 at every
    station (`latest_only=true`) or ozone at one station over a week. Each row has the
    unrounded raw value, the reported value, the instrument and the unit; hours are
    Pacific Standard Time (UTC-8) with time_utc. Last 30 days, unverified.
    Keywords: British Columbia, air pollutant, PM2.5 map, latest readings, ozone,
    instrument, raw value, reported value, meteorology, provincial network.
    Mots-clés : Colombie-Britannique, polluant atmosphérique, PM2,5, dernières
    mesures, ozone, instrument, valeur brute, valeur déclarée, météorologie, réseau
    provincial.
    """
    return await client.get_air_parameter_data(
        parameter=parameter,
        station=station,
        start=start,
        end=end,
        latest_only=latest_only,
        limit=limit,
        lang=lang,
    )


@tool
async def bc_env_get_aqhi(
    area: str | None = None, history_hours: int = 0, lang: Lang = "en"
) -> AqhiResult:
    """Current AQHI and forecasts for British Columbia areas (BC Ministry of Environment).

    Use for: the AQHI now in each of 27 BC areas (Metro Vancouver NW/NE/SW/SE,
    Fraser Valley, Victoria, Kamloops, Kelowna (Central Okanagan), Prince George,
    Williams Lake ...) with the risk category and the forecasts for today, tonight,
    tomorrow and tomorrow night; with `area` and `history_hours` (up to 720), the
    area's hourly AQHI for the last days, newest first.
    Keywords: AQHI, British Columbia, BC smoke forecast, risk category, wildfire smoke,
    Metro Vancouver, Okanagan, Kamloops, Prince George, BC areas.
    Mots-clés : cote air santé, CAS, Colombie-Britannique, prévision de la qualité de
    l'air, risque pour la santé, fumée, Metro Vancouver, Okanagan, conditions
    actuelles, horaire.
    """
    return await client.get_aqhi(area=area, history_hours=history_hours, lang=lang)


@tool
async def bc_env_list_snow_stations(
    query: str | None = None,
    status: str | None = None,
    operator: str | None = None,
    limit: int = constants.LIST_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> SnowStationList:
    """List BC automated snow weather stations (snow pillows).

    Use for: finding an automated snow station id (such as 1A01P Yellowhead Lake or
    2F01AP Trout Creek West) before reading SWE or snow depth;
    about 156 stations with elevation, status, operator (BC ENV, BC Hydro ...) and
    coordinates. The first digit and letter of the id give the basin (1 Fraser,
    2 Columbia, 3 coast, 4 north).
    Keywords: British Columbia, snow pillow, automated snow weather station, snow
    survey, River Forecast Centre, snowpack, station list, elevation, basin, BC Hydro.
    Mots-clés : Colombie-Britannique, coussin à neige, station nivométéorologique
    automatique, relevé nivométrique, Centre de prévision des crues, manteau neigeux,
    liste des stations, altitude.
    """
    return await client.list_snow_stations(
        query=query, status=status, operator=operator, limit=limit, lang=lang
    )


@tool
async def bc_env_get_snow_station_data(
    station: str,
    variables: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> SnowSeries:
    """Current-season readings of one BC automated snow station, with units and grades.

    Use for: everything one snow pillow station measured since 1 October: SWE
    (SW, mm), snow depth (SD, cm), TA (degC), cumulative precipitation (PC, mm) and, where present, peak wind, one row per time
    and variable (newest first, UTC), with the data grade. `variables` keeps some
    (e.g. ["SW", "SD"]). For earlier seasons use bc_env_get_snow_readings.
    Keywords: snow water equivalent, SWE, snow depth, snow pillow, British Columbia,
    snowpack, data grade, current season, station readings, River Forecast Centre.
    Mots-clés : équivalent en eau de la neige, épaisseur de neige, coussin à neige,
    Colombie-Britannique, manteau neigeux, données horaires, précipitations,
    saison en cours.
    """
    return await client.get_snow_station_data(
        station=station, variables=variables, start=start, end=end, limit=limit, lang=lang
    )


@tool
async def bc_env_get_snow_readings(
    variable: str,
    stations: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> SnowSeries:
    """BC snow pillow readings for many stations, reshaped from the wide files, with archive.

    Use for: one variable across stations or across years: SW (SWE,
    mm), SD (snow depth, cm), PC (cumulative precipitation, mm), TA (degC),
    SW_DAILY (daily SWE), and current-season PA, XR, UD, US, UP,
    UR (pressure, humidity, wind). The source publishes one column per station; this
    returns one row per time and station (UTC, newest first). `stations` takes ids or
    name fragments. A `start` before the current season reads the archive (hourly
    since October 2003, daily SWE since 1967) by range requests, e.g. SWE at 2F01AP
    on 1 April 2023.
    Keywords: snow water equivalent, SWE history, snow depth, snowpack, British
    Columbia, archive, hourly, daily, April 1 snowpack, wide to long, tidy.
    Mots-clés : équivalent en eau de la neige, historique, épaisseur de neige,
    manteau neigeux, Colombie-Britannique, archive, horaire, quotidien, relevé du
    1er avril.
    """
    return await client.get_snow_readings(
        variable=variable, stations=stations, start=start, end=end, limit=limit, lang=lang
    )


@tool
async def bc_env_get_snow_surveys(
    query: str | None = None,
    season: SurveySeason = "current",
    start: str | None = None,
    end: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> SnowSurveyList:
    """Manual snow survey (snow course) measurements in British Columbia.

    Use for: snow depth (cm), SWE (mm) and density (%) measured by hand
    at snow courses around the survey dates (1 January to 15 June), for the current
    season or the archive back to the 1930s, e.g. the 1 April survey at Yellowhead
    (1A01). `query` matches course name or number prefix; `start`/`end` filter the
    survey date. Newest first.
    Keywords: snow survey, snow course, manual measurement, SWE, snowpack,
    snow depth, density, British Columbia, River Forecast Centre, history, April 1.
    Mots-clés : relevé nivométrique, parcours nivométrique, mesure manuelle,
    équivalent en eau de la neige, épaisseur de neige, densité, Colombie-Britannique,
    historique.
    """
    return await client.get_snow_surveys(
        query=query, season=season, start=start, end=end, limit=limit, lang=lang
    )


@tool
async def bc_env_list_wells(
    query: str | None = None,
    status: str | None = None,
    region: str | None = None,
    with_data_only: bool = True,
    limit: int = constants.LIST_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> WellList:
    """List BC provincial groundwater observation wells.

    Use for: finding an observation well id (OW002 ...) by city, address, region
    (Cariboo, Okanagan, Lower Mainland, Vancouver Island ...) or status (Active,
    Inactive) before reading its levels; each well has coordinates, aquifer id
    and material, depth and ground elevation (feet, as in the provincial wells
    database), the date its data file last changed and a GWELLS link.
    `with_data_only=false` also lists wells that have no level files.
    Keywords: groundwater, observation well, aquifer, GWELLS id, British Columbia,
    well list, monitoring network, drought, GWELLS, piezometer.
    Mots-clés : eaux souterraines, puits d'observation, aquifère, nappe phréatique,
    Colombie-Britannique, liste des puits, réseau de surveillance, sécheresse, niveau
    d'eau.
    """
    return await client.list_wells(
        query=query,
        status=status,
        region=region,
        with_data_only=with_data_only,
        limit=limit,
        lang=lang,
    )


@tool
async def bc_env_get_well_levels(
    well: str,
    series: WellSeriesKind = "daily",
    start: str | None = None,
    end: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> WellSeries:
    """Groundwater levels at one BC observation well (depth below ground, metres).

    Use for: the groundwater record of a well such as OW002 Abbotsford: `series`
    "daily" (daily means over the whole record, back to the 1960s for the oldest
    wells), "hourly" (last 12 months, with approval status Approved or Working) or
    "all" (every published reading). Values are metres below ground, so a larger
    number means a deeper level. Hourly times are a fixed UTC-7 clock.
    `start`/`end` filter by date; newest first.
    Keywords: groundwater level, depth below ground, observation well, piezometric level,
    aquifer, British Columbia, drought, time series, daily mean, hourly.
    Mots-clés : niveau des eaux souterraines, profondeur de l'eau, puits
    d'observation, nappe phréatique, aquifère, Colombie-Britannique, sécheresse,
    série chronologique, moyenne quotidienne.
    """
    return await client.get_well_levels(
        well=well, series=series, start=start, end=end, limit=limit, lang=lang
    )


@tool
async def bc_env_list_streamflow_gauges(
    query: str | None = None,
    limit: int = constants.LIST_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> HydroStationList:
    """List BC provincial streamflow gauges (Ministry of Environment network).

    Use for: finding a BC provincial creek gauge, about 60 stations run by the
    Ministry of Environment and partners (ids like 08HA0022 Koksilah River at Trestle
    or H08KC0844 Hakai) that are not in the federal WSC network served by
    eccc_ tools; with the parameters each reports (discharge, stage) and the latest
    time.
    Keywords: BC provincial gauge, streamflow, creek flow, discharge, British Columbia,
    Ministry of Environment, Hakai, flow monitoring, provincial network.
    Mots-clés : station hydrométrique, débit, écoulement fluvial, niveau d'eau,
    hauteur d'eau, Colombie-Britannique, réseau provincial, jauge, ruisseau.
    """
    return await client.list_hydrometric_stations(query=query, limit=limit, lang=lang)


@tool
async def bc_env_get_streamflow(
    station: str,
    parameter: HydroParameter = "discharge",
    start: str | None = None,
    end: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> HydroSeries:
    """Discharge (m3/s) or stage (m) at one BC provincial streamflow gauge.

    Use for: the flow or gauge-height record of a provincial gauge (id from
    bc_env_list_streamflow_gauges): the current hydrological year (since 1 October)
    hourly, or, with `start` earlier, the yearly archives (back to the 2000s)
    read by range requests, e.g. 08HA0022 in August 2024. Rows are UTC, newest first,
    with the grade (Undefined, RISC U, RISC E, Estimated ...).
    Keywords: discharge, streamflow, creek flow, gauge height, British Columbia,
    provincial gauge, archive, low flow, freshet, m3/s.
    Mots-clés : débit, écoulement, débit fluvial, hauteur d'eau, niveau d'eau,
    hydrométrique, Colombie-Britannique, station provinciale, archive, étiage, crue.
    """
    return await client.get_hydrometric_data(
        station=station, parameter=parameter, start=start, end=end, limit=limit, lang=lang
    )
