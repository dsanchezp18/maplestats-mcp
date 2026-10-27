### Fixed

- `bc_env_get_snow_station_data`, `bc_env_get_snow_readings` and `bc_env_get_streamflow`:
  a cell holding text that is not a number became a null value with nothing said; the notes
  now count those cells, and `bc_env_get_streamflow` also counts rows skipped for having
  fewer than the file's 10 columns.
- `epcor_get_daily_water_quality`: a cell holding text other than a number or EPCOR's "--"
  missing marker (a "<0.01", say) became null with nothing said; `provenance.limits` now
  names those cells.
