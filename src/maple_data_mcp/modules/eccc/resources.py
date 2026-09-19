"""Zero-parameter MCP resources for the eccc module.

Zero-parameter is a hard requirement: any parameter makes FastMCP treat
a decorated function as a ResourceTemplate instead of a FunctionResource.

Every collection id and property name below was looked up live against
https://api.weather.gc.ca this session (not copied from documentation
prose) - MSC GeoMet carries ~100 collections in total; this is a
curated starting point for the ones that matter most for weather/
climate/water analysis, not an exhaustive list (use
eccc_search_collections/eccc_list_collections for the rest).
"""

from __future__ import annotations

from fastmcp.resources import resource

_WELL_KNOWN_COLLECTIONS_DOC = """\
# Well-known MSC GeoMet collections

Verified live against https://api.weather.gc.ca this session. Pass any
`collection_id` below to eccc_get_collection (for its full queryable
property list) or eccc_query_items (to fetch rows).

## Severe weather / alerts

- `weather-alerts` - active and recent watches/warnings/advisories/
  statements. Filter by `province` (2-letter code, e.g. "ON") and/or
  `alert_type` ("warning"/"watch"/"advisory"/"statement"). Each feature
  carries `alert_text_en`/`alert_text_fr` (the full alert text),
  `risk_colour_en`, `feature_name_en` (the affected area), and
  `status_en` ("alert"/"ended"). Does NOT support `datetime_filter`
  (see docs://eccc/gotchas).

## Current conditions / surface observations

- `swob-realtime` - real-time Surface Weather Observations from ~2,800
  stations. Properties use WMO-style shorthand names, each as a
  `<name>-value`/`<name>-uom`/`<name>-qa` triplet, e.g. `air_temp-value`
  (degrees C), `avg_wnd_spd_10m_pst10mts-value` (10-min average wind
  speed). Filter by `stn_nam-value` or bbox; check `swob-stations` for
  station ids/names first.
- `swob-stations`, `swob-partner-stations`, `swob-marine-stations` -
  station inventories for the collection above.
- `citypageweather-realtime` (marked experimental by ECCC) - per-city
  current conditions plus a multi-day text forecast.

## Air quality (AQHI)

- `aqhi-observations-realtime` - latest Air Quality Health Index
  reading per location (`aqhi`, 1-10+ scale; `location_id`,
  `location_name_en`, `observation_datetime`).
- `aqhi-forecasts-realtime` - AQHI forecast values per location.
- `aqhi-stations` - AQHI station/location inventory (ids, names,
  coordinates) to resolve a `location_id`.

## Climate normals and observations

- `climate-stations` - the master station inventory (`STN_ID`,
  `STATION_NAME`, `CLIMATE_IDENTIFIER`, `PROV_STATE_TERR_CODE`,
  `HAS_NORMALS_DATA`/`HAS_HOURLY_DATA` flags). **`LATITUDE`/
  `LONGITUDE` properties are integers scaled by 1e7, not decimal
  degrees** - use the feature's GeoJSON `geometry` for real
  coordinates (see docs://eccc/gotchas).
- `climate-normals` - 1981-2010 climate normals by `STN_ID`/
  `CLIMATE_IDENTIFIER` and `MONTH` (1-12; look for `PERIOD == "NORM"`),
  one row per normal element (`E_NORMAL_ELEMENT_NAME`, e.g. "Mean daily
  temperature deg C") with its `VALUE`.
- `climate-daily`, `climate-hourly`, `climate-monthly` - historical
  station observations at each frequency, filterable by
  `CLIMATE_IDENTIFIER` or `STN_ID`. These are large collections -
  always filter by station and/or a reasonably narrow bbox rather than
  paging through the whole country.
- `ltce-temperature`, `ltce-precipitation`, `ltce-snowfall`,
  `ltce-stations` - Long Term City Extremes: daily record highs/lows
  for major cities' "virtual" climate stations.

## Hydrology (water level / flow)

- `hydrometric-stations` - station inventory (`STATION_NUMBER`,
  `STATION_NAME`, `PROV_TERR_STATE_LOC`).
- `hydrometric-realtime` - real-time `LEVEL` (m) / `DISCHARGE` (m3/s)
  by `STATION_NUMBER` - 435,000+ rows measured live, always filter by
  station and/or `datetime_filter` (confirmed to work on this
  collection).
- `hydrometric-daily-mean`, `hydrometric-monthly-mean`,
  `hydrometric-annual-peaks`, `hydrometric-annual-statistics` - HYDAT
  historical archive at each aggregation level.

## Marine

- `marineweather-realtime` (marked experimental by ECCC) - marine
  forecasts and warnings by zone.
- `marine-standard-forecast-zones` - the marine forecast zone
  boundaries these forecasts are issued for.

## Everything else

Hurricane tracks (`hurricanes-*-realtime`), radar-derived precipitation
analysis (`weather:rdpa:*`), seasonal forecast models
(`weather:cansips:*`), and downscaled climate-projection families
(`climate:cmip5:*`, `climate:cangrd:*`, `climate:candcsu6:*`,
`climate:dcs:*`, `climate:spei-*`, `climate:indices:*`) are all real
MSC GeoMet collections not detailed here - use
eccc_search_collections(query=...) to find them.
"""

_GOTCHAS_DOC = """\
# Known MSC GeoMet-OGC-API gotchas

- **An unknown/misspelled property name is silently ignored, not
  rejected.** `?not_a_real_property=xyz` returns HTTP 200 with
  `numberMatched: 0` (confirmed live) - it looks exactly like "no rows
  matched your filter." eccc_query_items checks `filters`/`fields`/
  `sortby` names against the collection's own `/queryables` first and
  raises a clear error naming the bad key, but this only catches a
  typo against a property that collection could ever have - it cannot
  tell you your *value* was wrong (e.g. a nonexistent station number).
- **`datetime_filter` support is genuinely per-collection and is not
  declared anywhere in a collection's own metadata.** Confirmed live:
  `hydrometric-realtime` filters correctly on `datetime`;
  `weather-alerts` returns HTTP 500 for *any* `datetime` value. Both
  collections' `/collections/{id}` extent reports only a `spatial`
  block, no `temporal` one, so this cannot be checked in advance from
  metadata - if a query with `datetime_filter` fails, retry without it
  and filter by `filters`/`bbox` instead.
- **No server-side cap on `limit`.** `limit=100000` against an 88-row
  collection was honoured in full (confirmed live). Several collections
  here have hundreds of thousands of rows (`hydrometric-realtime`:
  435,000+ measured live) - eccc_query_items caps `limit` at 1000 and
  expects paging via `offset` for anything larger, rather than trusting
  an unbounded request to stay reasonable.
- **`climate-stations`' `LATITUDE`/`LONGITUDE` properties are scaled
  integers, not decimal degrees.** `LATITUDE: 485500000` /
  `LONGITUDE: -1234200000` means 48.55 N, 123.42 W (divide by 1e7) -
  confirmed live. The feature's own GeoJSON `geometry` field already
  carries correct decimal coordinates; prefer that over the raw
  properties for anything needing real lon/lat.
- **No language query parameter exists.** Bilingual content is always
  returned as separate `_en`/`_fr` suffixed properties within the same
  response (e.g. `alert_text_en`/`alert_text_fr`), never toggled by a
  request parameter - every eccc_ tool's `lang` argument is a
  documented no-op kept for interface consistency with the rest of
  this server.
"""


@resource("docs://eccc/well-known-collections")
def eccc_well_known_collections_doc() -> str:
    """List well-known MSC GeoMet collections for alerts, current conditions,
    AQHI, climate normals/observations, hydrometric, and marine data."""
    return _WELL_KNOWN_COLLECTIONS_DOC


@resource("docs://eccc/gotchas")
def eccc_gotchas_doc() -> str:
    """List known MSC GeoMet-OGC-API quirks that are easy to get wrong."""
    return _GOTCHAS_DOC
