### Fixed

- `bc_lobbyists_search_registrations`, `bc_lobbyists_search_activity_reports`
  and `bc_lobbyists_summarize_activity`: a `client` name no longer returns, along
  with the clients it names, every record that has no client number. A client
  number is compared only when `client` is all digits.
- `bc_env_get_snow_readings` and `bc_env_get_streamflow`: an `end` earlier than
  the current season (snow) or water year (streamflow) with no `start` no longer
  reads only the current file and answers with an empty series, in the
  streamflow case with a note blaming the station id. The call is now refused
  with a message that asks for `start`, since reading the archives from their
  first row would stop at the byte cap and return the oldest readings, not those
  nearest `end`. A call with `start` is unchanged.
- `bc_env_get_snow_station_data` and `bc_env_get_snow_readings`: with
  `lang='fr'`, the error for a bad station id or variable now shows the value
  received instead of the literal text `{station!r}` or `{variable!r}`.
- `ab_economic_get_data`: a filter column named `table` is refused with a
  message saying the name is reserved. It used to replace the validated table
  name in the request while the result still reported the table asked for.
- `electricity_alberta_get_pool_price`, `electricity_ontario_get_hourly_demand`,
  `electricity_ontario_get_supply_by_fuel`, `electricity_quebec_get_demand`,
  `electricity_quebec_get_generation` and `electricity_quebec_get_trade`: with
  only an `end_date`, they now return the last `limit` rows up to that date
  instead of the earliest rows of the window, which left out the end date's own
  hours. A call with both dates, or with only a `start_date`, is unchanged.
- `electricity_alberta_get_monthly_summary`: a month whose page AESO has not
  posted yet (or whose page cannot be read) is no longer remembered as "not
  published" for six hours. The next call asks AESO again, so a month appears
  as soon as the page is up.
- `electricity_ontario_get_hoep_history`: with no `year`, the default is now
  2025, the last year of the HOEP series, rather than last calendar year. From
  2027 the old default fell outside the allowed range and the call failed.
- `eccc_query_items`: a `sortby` with several keys, such as
  `STATION_NAME,-LATITUDE`, is no longer refused as one unknown property name;
  each key is checked on its own.
- `hc_drug_search_products`: a blank `schedule` or `atc` no longer counts as a
  filter. A call with only a blank value is refused ("give at least one"), where
  it used to return the whole product table as matches.
- `hc_nhp_search_products`: `query` and `company` now find names and holders
  whose accented letters differ in case from the text typed, such as
  `échinacée` for "Échinacée Plus". The search reported no match before.
