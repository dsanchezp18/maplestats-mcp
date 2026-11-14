### Fixed

- `ons_get_series` and `ons_get_indicator`: `start_period` and `end_period`
  are now compared as dates, so a bound written in another form than the
  series' periods filters correctly. Before, `start_period="2026-07"` on a
  quarterly series kept `2026-Q1` and `2026-Q2`, `start_period="2026-Q3"` on a
  monthly series dropped every 2026 month and ended in "no values", and
  `end_period="2026-03"` on a quarterly series dropped `2026-Q1`. A period is
  kept when it overlaps the window, so a month bound keeps the quarter that
  contains it. A month that does not exist (`2026-13`) is now refused as not
  a period.
- `oeb_list_datasets`, `oeb_describe_dataset` and `oeb_query_dataset`: a
  degraded answer from www.oeb.ca (a listing page with no datasets, or an open
  data page with no yearbook links) is no longer cached, so one bad answer no
  longer fails every call for the next six hours. A listing whose pager still
  has a next page after the page limit now fails with an upstream error
  instead of being cached as the whole catalogue.
- `transit_get_route_summary`: a trip whose first stop departs at `00:00:00`
  (with a blank arrival time) is no longer left out of the directions, the
  hourly counts and the first and last departures while `trips_on_date` still
  counted it.
- `nrcan_geo_search_names`: `radius_km` is rounded up to the whole kilometre
  the place-name service takes, not to the nearest (`0.4` and `2.5` were
  searched as 1 and 2 km, so places between 2 and 2.5 km were missed). When
  the radius is rounded, the result's limits say which radius was searched.
- `nl_stats_read_file`: a date-only Excel cell now reads as `2026-01-01`
  rather than `2026-01-01 00:00:00`; cells that carry a time keep it.
- `socrata_query_dataset_rows` and `opendatasoft_vancouver_query_records`: two
  queries whose free-text parameters differ only in where a `:` falls (for
  example `select="a"`, `where="b:c"` and `select="a:b"`, `where="c"`) no
  longer share a cache entry, so one is no longer answered with the other's
  cached rows.
