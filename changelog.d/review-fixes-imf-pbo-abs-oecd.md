### Fixed

- `imf_get_data`: when an answer had more observations than the row cap, the cut also
  shortened the copy kept for repeat calls, so the same question asked again within the cache
  time came back with the shorter history and without the "only the last N of each series are
  returned" note. The cut is now made on a copy, so every call says what was cut. An
  observation the IMF sends as `NaN` or infinite is no longer read as the latest value of its
  series; it is left out like any observation without a number.
- `pbo_get_publication`: a table whose variables share a label (the same fiscal year under two
  scenarios) no longer loses a column. The later one is named "2025-26 (2)" and so on, in
  `columns` and in each row, so its values no longer overwrite the first one's. An HTML table's
  `cells` now repeat a header across the columns of a colspan and down the rows of a rowspan,
  so each header sits over its data, and a cell held by a rowspan keeps its column when a later
  row ends before it. A span is capped (a colspan at 1000 columns, a rowspan at the rows the
  table has left), so a broken table cannot grow into millions of cells.
- `pbo_search_information_requests`: with `lang="fr"`, the count by department used only the
  French acronym, so departments without one were counted as "unknown" while the requests
  listed the English acronym. The count now uses the same acronym as the requests.
- `abs_get_data`, `abs_get_indicator`, `oecd_get_data`, `oecd_compare_countries`: an HTTP 200
  answer that is not SDMX-CSV (an outage page, an empty body) is now an upstream error and is
  not cached; it used to be kept and replayed for 6 hours (ABS) or 12 hours (OECD), which for
  the OECD also hid the next try from its hourly download budget. An answer with a header and
  no rows is still "no values".
- `abs_get_indicator`, `oecd_compare_countries`: each observation now carries its `status`
  (for example an estimate), as the rows of `abs_get_data` and `oecd_get_data` do; the
  indicator and comparison dropped it, so an estimated value looked like any other. The new
  `status` field is optional and null when the source gives none.
