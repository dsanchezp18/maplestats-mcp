### Added

- `cmhc_list_metropolitan_areas`: CMHC's 225 metropolitan areas (CMAs, census agglomerations
  and smaller centres) with the `geography_id` to pass with
  `geography_type="MetropolitanMajorArea"`, filtered by `name` ("Toronto" is 2270) or
  `province_id`. The `cmhc_` tools now return rents, vacancy rates and housing starts for a
  city, not only for Canada and the provinces.

### Fixed

- `cmhc_list_categories`, `cmhc_get_table_options` and `cmhc_get_table_data` accept
  `geography_type="CMA"` (and "RMR", "metro", "centre", "city"), which CMHC answered with an
  error, and a place name as `geography_id` ("Toronto", "Ontario") when exactly one area
  carries it; an unknown type, id or name is refused with the valid choices instead of
  reaching CMHC. `cmhc_get_table_data` also accepts the field labels that
  `cmhc_get_table_options` shows ("Bedroom Type", "Historical Time Periods") in place of
  their codes. Together these failed the chat demo's Toronto rent question.
- Chat demo: CMHC time series (`cmhc_get_table_data` with `row_field="TIMESERIES"`) are
  charted and tabled under the answer, one series per column. A saved conversation the page
  cannot draw is dropped instead of stopping the rest from loading, and a result the chart
  cannot draw shows a note under the answer instead of replacing the answer with an error.
