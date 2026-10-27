### Added

- `wds_get_data_from_vectors`, `wds_get_data_from_cube_coord`,
  `wds_get_data_by_reference_period_range`, `sdmx_get_data`, `sdmx_get_vector_data`
  and `boc_get_observations` take an optional `transform` (`diff`, `pct_change`,
  `yoy_diff`, `yoy_pct_change`, `annualized_pct_change`, or `index` with
  `index_base`) and `frequency` (`monthly`, `quarterly`, `annual`, with `aggregation`
  `average`, `sum` or `end_of_period`). The published values stay in `observations`;
  the computed ones come in a separate `transformed` block with the exact formula
  ("Computed by MapleStats: yoy_pct_change = 100 * (x_t / x_{t-12} - 1)"), the unit
  and notes. History for the lag is fetched before the requested window, year-over-year
  compares the same period a year earlier by date (a gap cannot shift it), missing
  values stay missing, and periods the data only partly cover are not aggregated. A
  percent change of a series already in percent or a rate (StatCan uom "Percent",
  Valet unit "Percent": an unemployment rate, the policy rate) comes back as the
  change in percentage points, and says so. Checked live: CPI all-items
  yoy_pct_change for September 2026 is 3.09, The Daily's 3.1%.
- `reproduce_code` repeats these transforms in R, Python, Stata (in its Python block)
  and Julia: the script fetches the same levels, as far back as the tool did, and
  applies the same formula. No Excel (Power Query) query is given for a transformed
  call, and the notes say why.
