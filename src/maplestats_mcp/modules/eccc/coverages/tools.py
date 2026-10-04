"""MCP tools for MSC GeoMet's gridded climate coverages (OGC API - Coverages).

These read the 49 `climate:*` coverage collections on api.weather.gc.ca
(CanDCS-U6 CMIP6, CMIP5, DCS, climate indices, SPEI, CanGRD) that the
feature tools in ../tools.py list but cannot read. `lang` picks the
language of the licence text in provenance; the source itself answers in
English only.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.eccc.coverages import client
from maplestats_mcp.modules.eccc.coverages.schemas import (
    CoverageCollectionList,
    CoverageData,
    CoverageDescription,
)

Lang = Literal["en", "fr"]


@tool
async def eccc_coverages_search(
    query: str = "",
    scenario: str | None = None,
    variable: str | None = None,
    timeframe: Literal["historical", "projected"] | None = None,
    frequency: Literal["annual", "seasonal", "monthly"] | None = None,
    year: int | None = None,
    limit: int = 20,
    lang: Lang = "en",
) -> CoverageCollectionList:
    """Find ECCC gridded climate projection and climate analysis datasets (coverages).

    Use for: picking the right climate-projection collection before
    fetching values: CanDCS-U6 (CMIP6, SSP1-2.6/2-4.5/5-8.5), CMIP5 and
    DCS (RCP2.6/4.5/8.5), downscaled climate indices (heating and cooling
    degree days, hot days, growing season), SPEI drought index and CanGRD
    observed anomalies. `query` words must all appear (id, title,
    description, variable names); `scenario` (e.g. "SSP585", "RCP8.5"),
    `variable` (id such as "tas" or a title word such as "precipitation"),
    `timeframe`, `frequency` and `year` (a year the data covers) narrow
    further. Each result lists its variables, scenarios, percentiles,
    seasons, 20/30-year windows and time range. Then call
    eccc_coverages_get_data.
    Keywords: climate projections, climate change scenarios, cmip6, cmip5,
    candcs-u6, downscaled, ssp, rcp, future temperature, future
    precipitation, climate indices, degree days, spei, drought, cangrd,
    environment canada, climate data canada.
    Mots-clés : projections climatiques, scénarios de changements
    climatiques, modèles climatiques, réduction d'échelle, température
    future, précipitations futures, indices climatiques, degrés-jours,
    sécheresse, environnement canada, données climatiques.
    """
    return await client.search_coverages(
        query,
        scenario=scenario,
        variable=variable,
        timeframe=timeframe,
        frequency=frequency,
        year=year,
        limit=limit,
        lang=lang,
    )


@tool
async def eccc_coverages_describe(collection_id: str, lang: Lang = "en") -> CoverageDescription:
    """Describe one ECCC gridded climate coverage: variables, units, scenarios, axes, time range.

    Use for: checking what a `climate:*` collection holds before asking
    for data: its variables with units, emission scenarios, ensemble
    percentiles, seasons, 20/30-year averaging windows, first and last
    year or month, grid resolution and extent, with a dataset note. Ids
    look like `climate:candcsu6:projected:annual:absolute` or
    `climate:indices:projected`; find them with eccc_coverages_search.
    Keywords: climate projection metadata, variables, units, scenarios,
    percentiles, ensemble, time range, grid resolution, coverage
    description, cmip6, environment canada.
    Mots-clés : métadonnées des projections climatiques, variables,
    unités, scénarios d'émissions, percentiles, ensemble de modèles,
    période couverte, résolution de la grille, environnement canada.
    """
    return await client.describe_coverage(collection_id, lang=lang)


@tool
async def eccc_coverages_get_data(
    collection_id: str,
    lat: float | None = None,
    lon: float | None = None,
    bbox: list[float] | None = None,
    variables: list[str] | None = None,
    scenarios: list[str] | None = None,
    percentiles: list[float] | None = None,
    seasons: list[str] | None = None,
    averaging_periods: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    max_rows: int = 1000,
    lang: Lang = "en",
) -> CoverageData:
    """Get climate projection values for a point or area as tidy rows (time, value, unit, scenario).

    Use for: future (or historical modelled) temperature, precipitation,
    degree days, hot days or drought index at a place in Canada, e.g.
    annual mean temperature in Edmonton 2015-2100 under SSP5-8.5, or the
    2071-2100 change in summer precipitation. Give a point (`lat`, `lon`:
    the nearest grid cell with data is used, and `point_distance_km` says
    how far it is) or a `bbox` [west, south, east, north] (one row per
    cell). `variables` defaults to the collection's first variable;
    `scenarios` and `seasons` default to all; `percentiles` defaults to
    the ensemble median (50th); `averaging_periods` (e.g. "2071-2100")
    defaults to all windows; `start`/`end` are YYYY (or YYYY-MM for
    monthly sets) and default to the full range. Each row names its
    variable, scenario, percentile, season and window, so several
    scenarios can be compared in one call. One upstream request is made
    per variable x scenario x percentile x season x window (at most 40),
    and a call is refused above about 250,000 grid values; `max_rows`
    (up to 10000) caps the rows returned, with `truncated` and
    `total_rows`. Rows include the ECCC licence in provenance.
    Keywords: climate projections, future temperature, future
    precipitation, climate change by city, cmip6 point data, ssp585,
    rcp8.5, 2050, 2080, heating degree days, drought index, time series,
    environment canada.
    Mots-clés : projections climatiques, température future,
    précipitations futures, changements climatiques par ville, scénario
    d'émissions, série chronologique, degrés-jours de chauffage, indice
    de sécheresse, horizon 2050, environnement canada.
    """
    return await client.get_coverage_data(
        collection_id,
        lat=lat,
        lon=lon,
        bbox=bbox,
        variables=variables,
        scenarios=scenarios,
        percentiles=percentiles,
        seasons=seasons,
        averaging_periods=averaging_periods,
        start=start,
        end=end,
        max_rows=max_rows,
        lang=lang,
    )
