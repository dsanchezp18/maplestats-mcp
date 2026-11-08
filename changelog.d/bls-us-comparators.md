### Added

- US Bureau of Labor Statistics comparators (`bls_`, 4 tools), over the BLS
  Public Data API v2. `bls_get_indicator` gives US nonfarm payrolls, the
  unemployment rate, CPI-U all items and core, average hourly earnings, the
  participation rate, job openings and the PPI, seasonally adjusted or not;
  `bls_get_series` takes any BLS series id; `bls_search_series` and
  `bls_list_surveys` help find one. Rows carry seasonal adjustment, units,
  preliminary flags, the change from the previous period, the per cent change
  from a year earlier and the news release schedule. Uses the API without
  registration, so the BLS's unregistered limits apply (25 queries a day per
  server, 25 series and 10 years per query) and are stated in each result's
  `provenance.limits`. The planner now answers US
  labour and price questions with the BLS plan instead of calling them out of
  scope.
