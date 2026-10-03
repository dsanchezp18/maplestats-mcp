"""MCP tools for the Canadian Wildland Fire Information System (CWFIS)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.cwfis import client
from maplestats_mcp.modules.cwfis.schemas import (
    FireDanger,
    ForecastResult,
    HotspotResult,
    LargeFireResult,
    PerimeterResult,
    SituationReport,
    SituationReportList,
    StationResult,
)

Lang = Literal["en", "fr"]


@tool
async def cwfis_get_hotspots(
    agency: str | None = None,
    bbox: list[float] | None = None,
    min_frp: float | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    canada_only: bool = True,
    sort_by: Literal["latest", "frp"] = "latest",
    limit: int = 20,
    offset: int = 0,
    lang: Lang = "en",
) -> HotspotResult:
    """Satellite fire hotspots (VIIRS, MODIS, SLSTR) with fire weather values per detection.

    With no dates: detections of the last 24 hours. With start_date AND end_date
    (YYYY-MM-DD): the archive since 1994. Filter by agency (province code such as
    'BC'), bbox [min_lon, min_lat, max_lon, max_lat] or minimum fire radiative
    power. Canada only by default (the source also carries US/Mexico detections).
    sort_by='frp' ranks detections by FRP, then lists those with no FRP (most
    archive rows before 2024 have none; without_frp counts them).
    Use for: where fires are burning right now, active fire detections in a
    province, hotspot counts on a past date, fire intensity (FRP, HFI) and FWI.
    Keywords: hotspots, active fires, satellite fire detection, VIIRS, MODIS,
    wildfire today, fire radiative power, FRP, CWFIS, NRCan, fire season.
    Mots-clés : points chauds, feux actifs, détection satellite, incendie de forêt,
    feux de végétation, puissance radiative, SCIF, RNCan, saison des feux.
    """
    del lang
    return await client.get_hotspots(
        agency=agency,
        bbox=bbox,
        min_frp=min_frp,
        start_date=start_date,
        end_date=end_date,
        canada_only=canada_only,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )


@tool
async def cwfis_get_fire_perimeters(
    bbox: list[float] | None = None,
    min_area_ha: float | None = None,
    include_geometry: bool = False,
    limit: int = 20,
    offset: int = 0,
    lang: Lang = "en",
) -> PerimeterResult:
    """Current-season estimated fire perimeters (M3 hotspot-cluster polygons), largest first.

    Not agency-mapped perimeters: polygons modelled from clustered hotspots this
    season (first/last detection date, hotspot count, area). Set
    include_geometry for GeoJSON polygons; those rows stop at about 400 KB of
    geometry (note and has_more say so; page on with offset). For final burned area by year use
    nrcan_nbac_query_fires; for BC agency fires use bcgw_get_active_wildfires.
    Use for: biggest fires this season, current fire footprint in a region.
    Keywords: fire perimeter, wildfire polygon, current season, M3, active fire
    size, area burned this year, CWFIS, NRCan, fire map, GeoJSON.
    Mots-clés : périmètre d'incendie, polygone de feu, saison en cours, superficie
    brûlée cette année, feux actifs, carte des feux, SCIF, RNCan, GeoJSON.
    """
    del lang
    return await client.get_perimeters(
        bbox=bbox,
        min_area_ha=min_area_ha,
        include_geometry=include_geometry,
        limit=limit,
        offset=offset,
    )


@tool
async def cwfis_get_weather_stations(
    province: str | None = None,
    name: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = 50.0,
    limit: int = 20,
    lang: Lang = "en",
) -> StationResult:
    """Fire weather stations with the latest Fire Weather Index (FWI) system values.

    Search by province code (SK and NL map to the layer's own codes), by name
    fragment, or by point (latitude + longitude + radius_km up to 200, nearest
    first). Stations report during the fire season; off season the layer holds
    only a few, and an empty result's note says how many and where. Each station
    has one noon observation plus FFMC, DMC, DC, ISI, BUI, FWI and DSR.
    Use for: today's fire weather index near a town, FWI by station, drought
    code and fine fuel moisture, wildfire risk indices for a province.
    Keywords: Fire Weather Index, FWI, FFMC, DMC, drought code, buildup index,
    ISI, fire weather station, fire danger, wildfire risk, CWFIS, NRCan.
    Mots-clés : Indice Forêt-Météo, IFM, indice de sécheresse, indice de
    propagation initiale, station météo incendie, danger d'incendie, risque de feu,
    SCIF, RNCan.
    """
    del lang
    return await client.get_stations(
        province=province,
        name=name,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        limit=limit,
    )


@tool
async def cwfis_get_fire_weather_forecast(
    station_name: str,
    limit: int = 100,
    lang: Lang = "en",
) -> ForecastResult:
    """Modelled FWI and fire weather values for the coming days at a fire-weather station.

    station_name is a case-insensitive fragment ('KELOWNA', 'EDMONTON'); every
    matching station returns one row per future day (SCRIBE model). Find
    station names with cwfis_get_weather_stations. Not general weather.
    Use for: fire danger for the coming days, FWI outlook at a station.
    Keywords: FWI outlook, wildfire outlook, fire danger next days, SCRIBE,
    fire weather station, wildfire, CWFIS, NRCan.
    Mots-clés : prévision météo-incendie, prévision IFM, danger d'incendie prévu,
    perspectives feux de forêt, prochains jours, feu de végétation, SCIF, RNCan.
    """
    del lang
    return await client.get_forecast(station_name=station_name, limit=limit)


@tool
async def cwfis_get_fire_danger(
    latitude: float,
    longitude: float,
    lang: Lang = "en",
) -> FireDanger:
    """Fire danger class (Low to Extreme) at a latitude/longitude from the national danger grid.

    Looks up the current-day fire danger rating polygon covering the point.
    Raises not-found for points outside land in and near Canada.
    Use for: how dangerous is wildfire risk at this location today, fire danger
    rating for a town, low/moderate/high/very high/extreme.
    Keywords: fire danger rating, wildfire risk today, danger class, extreme fire
    danger, fire danger map, point lookup, CWFIS, NRCan, forest fire risk.
    Mots-clés : cote de danger d'incendie, risque de feu aujourd'hui, classe de
    danger, danger extrême, carte du danger, point, SCIF, RNCan, feu de forêt.
    """
    del lang
    return await client.get_fire_danger(latitude=latitude, longitude=longitude)


@tool
async def cwfis_search_large_fires(
    year_from: int | None = None,
    year_to: int | None = None,
    agency: str | None = None,
    min_size_ha: float | None = None,
    cause: Literal["N", "H", "U", "H-PB"] | None = None,
    name: str | None = None,
    sort_by: Literal["size", "date"] = "size",
    limit: int = 20,
    offset: int = 0,
    lang: Lang = "en",
) -> LargeFireResult:
    """National Fire Database (NFDB) large-fire points: fires of 200 ha or more, 1980-2023.

    Filter by year range, agency (province/territory code or 'PC' for Parks
    Canada), minimum size in hectares, cause (N natural, H human, U unknown,
    H-PB human prescribed burn) and name fragment. Biggest first by default.
    Each record has report and out dates, final size, cause and location.
    Use for: largest wildfires in history, large fires by province and year,
    lightning versus human-caused fires, fire size and dates.
    Keywords: National Fire Database, NFDB, large fires, historical wildfires,
    fire size hectares, fire cause lightning human, biggest fire, CWFIS, NRCan.
    Mots-clés : Base de données nationale sur les feux, BDNF, grands feux,
    incendies historiques, superficie brûlée, cause foudre humaine, plus grand
    feu, SCIF, RNCan.
    """
    del lang
    return await client.search_large_fires(
        year_from=year_from,
        year_to=year_to,
        agency=agency,
        min_size_ha=min_size_ha,
        cause=cause,
        name=name,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )


@tool
async def cwfis_list_situation_reports(
    report_type: Literal["all", "end_of_season"] = "all",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 20,
    offset: int = 0,
    lang: Lang = "en",
) -> SituationReportList:
    """List weekly national wildfire situation reports (1998 onward) with national totals.

    Numeric totals (fires and hectares to date, ten-year averages, percent of
    normal, controlled/uncontrolled counts) are published for 1998-2023 reports
    only; from 2024 they appear in the narrative, so use
    cwfis_get_situation_report. report_type 'end_of_season' lists the yearly
    season summaries. Dates are YYYY-MM-DD; limit is at most 100.
    Use for: national area burned to date, fires so far this season versus the
    10-year average, season totals by year.
    Keywords: national situation report, area burned to date, number of fires,
    10-year average, season summary, CIFFC, wildfire statistics Canada, CWFIS.
    Mots-clés : rapport de situation national, superficie brûlée à ce jour,
    nombre de feux, moyenne sur 10 ans, bilan de saison, statistiques feux de
    forêt Canada, SCIF, RNCan.
    """
    del lang
    return await client.list_situation_reports(
        report_type=report_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )


@tool
async def cwfis_get_situation_report(
    report_type: Literal["in_season", "end_of_season"] = "in_season",
    date_on_or_before: str | None = None,
    lang: Lang = "en",
) -> SituationReport:
    """One national wildfire situation report with narrative text, in English or French.

    Latest by default, or the report on or before date_on_or_before
    (YYYY-MM-DD). In-season reports cover synopsis, prognosis, priority fires and
    national preparedness level; end-of-season reports summarise the whole
    season. lang selects the narrative language.
    Use for: the current national wildfire situation, preparedness level, how the
    season went, priority fires.
    Keywords: national wildfire situation, preparedness level, season summary,
    priority fires, fire season review, CIFFC, wildfire report Canada, CWFIS.
    Mots-clés : situation nationale des feux, niveau de préparation, bilan de la
    saison, feux prioritaires, rapport sur les feux de forêt au Canada, préparation nationale, SCIF, RNCan.
    """
    return await client.get_situation_report(
        report_type=report_type, date_on_or_before=date_on_or_before, lang=lang
    )
