### Added

- `wds_get_series_as_of`: a StatCan series as it was published on a past date, before later
  revisions. Give the series of a regular table (`vector_id`, or `product_id` + `coordinate`)
  and `as_of`; the values come from the latest release on or before that date, read from
  the table's real-time (vintage) table, with `release_date` saying which release. Works for
  the 16 tables WDS pairs with a real-time table (CPI core measures, monthly and quarterly
  GDP, SEPH employment and earnings, retail, wholesale, manufacturing, trade, balance of
  payments, capital expenditures); any other table is an error, not current data.
