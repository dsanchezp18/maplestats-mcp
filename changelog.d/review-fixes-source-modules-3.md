### Fixed

- `ab_opendata_get_budget_table`: a line item whose figures were whole numbers between 1900
  and 2100 rising from left to right (1950, 1980, 2020, 2075 in millions of dollars) was
  read as a row of years: the line vanished and every later row got column names such as
  "2025-26 Budget 1950". A row of years is now a header when it has no line-item label or
  has a line of header text (Actual, Budget, Forecast) under it, whatever the gaps between
  its years (2017, 2019, 2025, 2026), or when its label reads as a header ("Calendar Year
  Assumptions", "Exercice"). Any other labelled row is a header only when its years run one
  after another, it comes before the first data row and no header row above already holds
  years, so a first line item of consecutive figures stays data.
- `ilo_get_data` and `ilo_compare_countries`: with `last_n` (which `ilo_compare_countries`
  sets itself when no start is given) and an `end_period` in the past, on the route that
  reads ILO's second server, the years were counted back from the current year, so
  `last_n=10, end_period="2015"` returned three years. They are now counted back from
  `end_period`.
- `cihi_get_indicator_data`: the "latest" rows were the end of the file, which is ordered by
  place, so they were the last place's rows. The newest `limit` rows are now chosen by the
  time frame column ("Time frame", or "Période" in the French file), still within the row
  cap and the 200 KB budget, and returned in file order. A table with no such column keeps
  the end of the file, and `provenance.coverage` says "newest" or "last" accordingly.
- `hc_vigilance_search_reactions`: a search for "éruption" never found "Éruption", because
  the fast test run on each block of the file folded the case of ASCII letters only and
  dropped the line before the exact test could accept it. Accented letters now match in
  either case.
- `electricity_ontario_get_hourly_demand` and `electricity_ontario_get_supply_by_fuel`: in the
  first days of a year, the latest hours (no `year`, no `start_date`, no `end_date`) failed
  with a missing file or came back short, because only the current year's file was read.
  When that file is absent or holds fewer hours than `limit`, the year before is read as
  well and the last hours of both are returned; the result's `year` is the newest file read,
  and the peak, average, totals, shares and `rows_matched` cover only the hours returned,
  not the whole earlier file. `provenance.limits` says which hours. A `year`, `start_date`
  or `end_date` still reads that year's file alone.
- `bcer_search_wells`, `bcer_get_production`, `bcer_get_drilling_records`,
  `bcer_search_facilities` and `bcer_get_reference_table`: lines the scan skipped because
  they did not have as many fields as the header were counted but never reported. When there
  were any, the result's `notes` now say how many, in English and French.
- `cfia_disease_detections`: with `counts_by="province"`, a row naming several provinces
  ("Alberta and Saskatchewan") is counted in each of them, so the province counts add up to
  more than the rows. `row_count` and `herd_count` already count each row once; the result's
  `notes` now say so when it happens.
- `cwfis_get_weather_stations`: `province` accepts a province or territory name in English
  or French ("Alberta", "Colombie-Britannique", "Terre-Neuve-et-Labrador"), in any case and
  with or without accents; a name used to be sent as written, matched nothing, and the empty
  answer blamed the fire season. The layer's own values are codes, so the filter and the
  `province` shown for each station are unchanged.
- `oecd_get_data` and `oecd_compare_countries`: after an HTTP 429 with `Retry-After: 600`, the message could say "about
  11 minutes" instead of "about 10", because the wait was read back as 600.0000000000005
  seconds when the clock had not advanced (a coarse clock on Windows). The wait is now
  rounded to a millisecond before it is rounded up to whole minutes, so 600 s reads 10
  minutes and 601 s reads 11.
- `nrcan_fuel_prices_list_locations` and `nrcan_fuel_prices_get_prices`: the module and tool
  descriptions now say, in English and French, that NRCan's terms apply (non-commercial
  reproduction only, commercial redistribution needs its written permission, its prices rely
  on third-party data) and point to `provenance.licence`, where the terms were already given.
