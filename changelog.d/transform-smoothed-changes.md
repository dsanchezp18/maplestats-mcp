### Added

- `window` now also smooths a change: with `transform` set to `diff`, `pct_change`,
  `yoy_diff`, `yoy_pct_change` or `annualized_pct_change`, the six data tools
  (`wds_get_data_from_vectors`, `wds_get_data_from_cube_coord`,
  `wds_get_data_by_reference_period_range`, `sdmx_get_data`, `sdmx_get_vector_data`,
  `boc_get_observations`) compute the change first, then its trailing moving average
  over `window` periods, matched by date and null when any change in the window is
  missing. So `transform="yoy_pct_change", frequency="annual", window=3` gives the
  3-year moving average of yearly inflation in one call (or `window=36` on the
  monthly 12-month rate). The formula says so ("Computed by MapleStats: moving
  average over 3 years of yoy_pct_change = mean(y_{t-2}, y_{t-1}, y_t), y_t = 100 *
  (x_t / x_{t-1} - 1)"), the history fetched covers both the lag and the window, and
  for a series in percent or a rate the percentage-point change is what gets
  averaged, as the notes say. `transform="moving_average"` is unchanged (the moving
  average of the levels). `window` with `index` is refused with an explanation:
  averaging the index and indexing the average differ, so neither is guessed.
  Checked live: for CPI all-items (v41690973), 2025 is 2.78, the mean of the yearly
  changes in the annual averages for 2023 (3.88), 2024 (2.38) and 2025 (2.07); the
  SDMX tool gives the same.
- `reproduce_code` repeats the smoothing in R, Python, Julia and Stata (in its Python
  block); the generated Python, run live, matched the tool for a WDS call and two
  Bank of Canada calls (monthly CPI, and daily series averaged to months, one of them
  a rate).
