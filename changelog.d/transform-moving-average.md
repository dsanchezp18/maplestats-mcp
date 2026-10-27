### Added

- `wds_get_data_from_vectors`, `wds_get_data_from_cube_coord`,
  `wds_get_data_by_reference_period_range`, `sdmx_get_data`, `sdmx_get_vector_data`
  and `boc_get_observations` take `transform="moving_average"` with a new optional
  `window` (2 to 120 periods): a trailing moving average, labelled "Computed by
  MapleStats: moving_average_3 = mean(x_{t-2}, x_{t-1}, x_t)". It composes with
  `frequency` (`frequency="annual", window=3` averages each year first, then takes the
  3-year moving average), is found by date, not by row, so a window that reaches a
  missing or unpublished period is null rather than shorter, and the history the
  window needs is fetched before the requested span, which alone is returned. A
  moving average of a rate (unemployment rate, CPI inflation) stays in the rate's
  unit; no percentage-point conversion applies, and the notes say so. Only trailing
  averages are computed (no centred ones), and daily series need `frequency` first.
  Checked live: the 3-year moving average of the annual unemployment rate (table
  14-10-0327) for 2025 is 6.17, (5.4 + 6.3 + 6.8) / 3. `transformed` gains a
  `window` field.
- `reproduce_code` repeats the moving average in R, Python, Julia and Stata (in its
  Python block).
