"""MCP tools for Alberta Wildfire live status."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.ab_wildfire import client
from maplestats_mcp.modules.ab_wildfire.client import FireFilters
from maplestats_mcp.modules.ab_wildfire.schemas import (
    DangerAtPoint,
    DangerSummary,
    Dataset,
    DateBasis,
    FireControlOrderList,
    FireGroupBy,
    FireList,
    FireSort,
    FireSummary,
    PerimeterList,
    PerimeterState,
    SeasonStatistics,
)

Lang = Literal["en", "fr"]


@tool
async def ab_wildfire_get_fires(
    dataset: Dataset = "current",
    status: str | None = None,
    active_only: bool = False,
    fire_type: str | None = None,
    cause: str | None = None,
    size_class: str | None = None,
    forest_area: str | None = None,
    fire_year: int | None = None,
    carryover: bool | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    date_basis: DateBasis = "assessed",
    min_area_ha: float | None = None,
    bbox: list[float] | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    sort_by: FireSort = "latest",
    limit: int = 20,
    offset: int = 0,
    lang: Lang = "en",
) -> FireList:
    """List Alberta Wildfire fire locations (points) with status, cause, size
    class, estimated area in hectares and responsible forest area, from
    Alberta Wildfire's own status map. No API key.

    dataset "current" (default) is this year's fires plus carry-over fires,
    active and extinguished together, including mutual-aid fires (fire_type
    "Mutual Aid", no cause recorded). "previous_5_years" is the last six
    fire years each cut at today's calendar date, for same-date comparison
    only, not a full history. active_only=true keeps fires still being
    worked (Out of Control, Being Held, Under Control, Assistance Started);
    off-season there are none, which is normal. status is exact text such as
    "Extinguished"; cause such as "Lightning", "Human", "Under
    Investigation"; size_class letters "A" (to 0.1 ha), "B" (to 4), "C" (to
    40), "D" (to 200), "E" (over 200), comma separated ("D,E"); forest_area
    a substring such as "Calgary" or "Slave Lake" (run
    ab_wildfire_summarize_fires with group_by "forest_area" for the names).
    start_date/end_date (YYYY-MM-DD, inclusive) apply to the assessment date
    (date_basis "assessed", roughly when the fire was found) or to the last
    status change ("status_changed", for example when it was put out), as
    Alberta calendar days; timestamps in the rows are UTC.
    bbox [min_lon, min_lat, max_lon, max_lat], or latitude, longitude and
    radius_km (up to 300) for fires near a point, nearest first. sort_by
    "latest" (default) or "largest". limit 1-2000, page with offset.
    Use for: wildfires burning now in Alberta, the biggest fires of the
    season, lightning versus human-caused fires, fires near a town or
    in a forest area, how many fires Alberta had this year.
    Keywords: Alberta, wildfire, forest fire, active fires, fire status,
    out of control, being held, under control, extinguished, fire cause,
    lightning, human caused, size class, forest area, mutual aid, fire
    locations, fire season, Alberta Wildfire.
    Mots-clés : Alberta, feu de forêt, incendie de forêt, feux actifs,
    statut du feu, hors de contrôle, maîtrisé, éteint, cause du feu, foudre,
    cause humaine, classe de superficie, zone forestière, entraide, saison
    des feux.
    """
    return await client.list_fires(
        dataset,
        FireFilters(
            status=status,
            active_only=active_only,
            fire_type=fire_type,
            cause=cause,
            size_class=size_class,
            forest_area=forest_area,
            fire_year=fire_year,
            carryover=carryover,
            start_date=start_date,
            end_date=end_date,
            date_basis=date_basis,
            min_area_ha=min_area_ha,
            bbox=bbox,
        ),
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def ab_wildfire_summarize_fires(
    dataset: Dataset = "current",
    group_by: FireGroupBy = "status",
    status: str | None = None,
    active_only: bool = False,
    fire_type: str | None = None,
    cause: str | None = None,
    size_class: str | None = None,
    forest_area: str | None = None,
    fire_year: int | None = None,
    carryover: bool | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    date_basis: DateBasis = "assessed",
    min_area_ha: float | None = None,
    bbox: list[float] | None = None,
    lang: Lang = "en",
) -> FireSummary:
    """Count Alberta wildfires and sum their estimated area (hectares) grouped
    by "status", "cause", "size_class", "forest_area", "fire_type" or
    "fire_year", with the same filters as ab_wildfire_get_fires. Computed by
    the server over every matching row, not a sample.

    Also the way to find the exact forest-area, cause and status labels to
    filter on. The totals include mutual-aid fires and carry-over fires
    unless filtered (fire_type "Wildfire", carryover false); the dashboard
    headline in ab_wildfire_get_season_statistics counts current-year
    wildfires only. With dataset "previous_5_years", group_by "fire_year"
    compares the same date across six years.
    Use for: fires by cause this season, area burned by forest area, how
    many fires are out of control, fire counts by size class, comparing
    this year with earlier years on the same date.
    Keywords: Alberta, wildfire, fire statistics, fires by cause, area
    burned, hectares, lightning, human caused, forest area, size class,
    fire counts, season totals, Alberta Wildfire.
    Mots-clés : Alberta, feu de forêt, statistiques des feux, feux par
    cause, superficie brûlée, hectares, foudre, cause humaine, zone
    forestière, classe de superficie, nombre de feux, bilan de la saison.
    """
    return await client.summarize_fires(
        dataset,
        group_by,
        FireFilters(
            status=status,
            active_only=active_only,
            fire_type=fire_type,
            cause=cause,
            size_class=size_class,
            forest_area=forest_area,
            fire_year=fire_year,
            carryover=carryover,
            start_date=start_date,
            end_date=end_date,
            date_basis=date_basis,
            min_area_ha=min_area_ha,
            bbox=bbox,
        ),
        lang=lang,
    )


@tool
async def ab_wildfire_get_season_statistics(lang: Lang = "en") -> SeasonStatistics:
    """Alberta Wildfire's season dashboard: active wildfires and area, wildfires
    and area burned so far this year, new wildfires in the last 24 hours, and
    the totals as at the same calendar date in each of the last six years
    next to the 5, 10 and 25-year averages.

    Headline figures count current-year wildfires only (mutual-aid and
    carry-over fires are left out), so they differ from row counts of
    ab_wildfire_get_fires. The 25-year averages and the current year's own
    averages are null in the source, and the active count can exceed zero
    while the active-fire layer is empty (for example a fire turned over to
    another agency).
    Use for: how this fire season compares with the average, hectares burned
    in Alberta so far this year, how many wildfires Alberta has had, new
    fires in the past day.
    Keywords: Alberta, wildfire, fire season, season statistics, hectares
    burned, area burned, year to date, five year average, ten year average,
    comparison, wildfire count, Alberta Wildfire dashboard.
    Mots-clés : Alberta, feu de forêt, saison des feux, statistiques de la
    saison, hectares brûlés, superficie brûlée, depuis le début de l'année,
    moyenne sur cinq ans, moyenne sur dix ans, comparaison, nombre de feux,
    tableau de bord.
    """
    return await client.get_season_statistics(lang=lang)


@tool
async def ab_wildfire_get_fire_perimeters(
    state: PerimeterState = "active",
    fire_number: str | None = None,
    cause: str | None = None,
    size_class: str | None = None,
    forest_area: str | None = None,
    min_area_ha: float | None = None,
    include_geometry: bool = False,
    limit: int = 20,
    offset: int = 0,
    lang: Lang = "en",
) -> PerimeterList:
    """List mapped Alberta wildfire perimeters (polygons), largest first, with
    the fire's status, cause, estimated and mapped area, and how the outline
    was captured (GPS, aerial imagery, hybrid).

    state "active" (default; empty off-season, which is normal) or
    "extinguished" (this year's mapped fires). Only some fires get a
    perimeter, none for fires turned over to another agency; use
    ab_wildfire_get_fires for every fire point. fire_number is a substring
    such as "HWF" or "WWF-012-2026". include_geometry returns GeoJSON in
    WGS84 simplified to about 50 m (limit then 1-100, otherwise 1-2000).
    Satellite-derived estimated perimeters for all of Canada are in
    cwfis_get_fire_perimeters.
    Use for: the outline of an Alberta wildfire, the size of a burned area,
    mapping extinguished fires, how a perimeter was captured.
    Keywords: Alberta, wildfire, fire perimeter, burned area, polygon,
    GeoJSON, fire boundary, extinguished fires, active fires, area
    hectares, Alberta Wildfire.
    Mots-clés : Alberta, feu de forêt, périmètre du feu, zone brûlée,
    polygone, GeoJSON, limite du feu, feux éteints, feux actifs, superficie
    en hectares.
    """
    return await client.get_perimeters(
        state,
        fire_number=fire_number,
        cause=cause,
        size_class=size_class,
        forest_area=forest_area,
        min_area_ha=min_area_ha,
        include_geometry=include_geometry,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def ab_wildfire_get_fire_danger(
    latitude: float, longitude: float, lang: Lang = "en"
) -> DangerAtPoint:
    """Alberta's fire danger rating at a point: Low, Moderate, High, Very High
    or Extreme, with what the class means.

    Based on the Fire Weather Index system (temperature, humidity, rain,
    wind) and refreshed daily (provenance.as_of is the layer's last edit;
    the polygon's own timestamp can read hours ahead of the clock). The rating polygons cover all of Alberta,
    including towns outside the forest zone; a point elsewhere returns a null
    class. It is general public information, not a substitute for the
    site-specific rating regulated forest operations must use. For a box or
    the whole province use ab_wildfire_summarize_fire_danger; for the
    national fire weather indices at stations use cwfis_get_weather_stations.
    Use for: how dangerous is the wildfire risk at a town, is the fire
    danger extreme near me, camping or burning conditions in Alberta.
    Keywords: Alberta, fire danger, fire danger rating, wildfire risk,
    fire weather index, extreme, very high, high, moderate, low,
    forest fire danger, Alberta Wildfire.
    Mots-clés : Alberta, danger d'incendie, cote de danger d'incendie,
    risque de feu de forêt, indice forêt-météo, extrême, très élevé, élevé,
    modéré, faible, danger de feu de forêt.
    """
    return await client.get_fire_danger(latitude, longitude, lang=lang)


@tool
async def ab_wildfire_summarize_fire_danger(
    bbox: list[float] | None = None, lang: Lang = "en"
) -> DangerSummary:
    """Count Alberta's fire danger rating polygons by class (Low to Extreme),
    province-wide or for a box [min_lon, min_lat, max_lon, max_lat], with the
    most severe class present.

    Counts are polygons, not area (polygon sizes differ), so they show which
    classes occur, not how much land each covers. For one location use
    ab_wildfire_get_fire_danger.
    Use for: is any part of Alberta at extreme fire danger, fire danger
    across a region, the worst rating in an area.
    Keywords: Alberta, fire danger, danger rating, wildfire risk, region,
    province-wide, extreme, very high, fire weather, rating polygons,
    Alberta Wildfire.
    Mots-clés : Alberta, danger d'incendie, cote de danger, risque de feu de
    forêt, région, ensemble de la province, extrême, très élevé, météo des
    incendies, polygones de cote.
    """
    return await client.summarize_fire_danger(bbox, lang=lang)


@tool
async def ab_wildfire_get_fire_restrictions(
    latitude: float | None = None,
    longitude: float | None = None,
    alert_type: str | None = None,
    name_contains: str | None = None,
    limit: int = 100,
    lang: Lang = "en",
) -> FireControlOrderList:
    """List Alberta fire bans, fire restrictions, fire advisories and forest
    area closures (plus off-highway-vehicle restrictions when any exist) from
    the Alberta Fire Ban System, most severe first, province-wide or only
    those covering a point.

    alert_type is "Forest Area Closure", "Fire Ban", "Fire Restriction",
    "Fire Advisory" or "OHV Restriction". name_contains matches the issuing
    municipality, county or park ("Banff", "County"). Each entry has a start
    date but no end date, so an old entry may be stale; the response says how
    many started over a year ago. One entry can be several polygons. The
    issuing authority is the reference for what is allowed.
    Use for: is there a fire ban where I am, which Alberta counties have fire
    restrictions, campfire rules in a municipality, current fire bans.
    Keywords: Alberta, fire ban, fire restriction, fire advisory, forest
    closure, burning ban, campfire, open fire, OHV restriction, county,
    municipality, national park, Alberta Fire Ban System.
    Mots-clés : Alberta, interdiction de feu, restriction de feu, avis de
    feu, fermeture de forêt, interdiction de brûlage, feu de camp, feu à
    ciel ouvert, restriction VTT, comté, municipalité, parc national.
    """
    return await client.get_fire_control_orders(
        latitude,
        longitude,
        alert_type=alert_type,
        name_contains=name_contains,
        limit=limit,
        lang=lang,
    )
