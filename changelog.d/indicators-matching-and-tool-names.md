### Changed

- `statcan_indicators_get_indicators`: every word of `query` must appear in the title,
  in any order and ignoring accents, instead of the whole query as one phrase; "CPI" and
  "inflation" find the Consumer Price Index and "GDP" finds gross domestic product.
  `geo_code` also takes a province name or abbreviation ("AB", "Alberta", "Québec"), and
  a place named in `query` ("unemployment rate Alberta") filters by it when `geo_code` is
  not given. A `limit` above 300 is lowered to 300 and noted instead of failing. When
  nothing matches, `provenance.limits` says why: the geographies the indicator is
  published for, or titles holding some of the words.
- `call_tool` runs a tool whose name a client changed only by a namespace, case or
  separator (`maplestats.wds_get_data_from_vectors`, `WDS-GET-DATA-FROM-VECTORS`), and an
  unknown name's error suggests up to three close tool names. A misspelled name is never
  run. `/stats` counts such a call under the tool it ran.
