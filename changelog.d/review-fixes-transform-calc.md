### Fixed

- `boc_get_observations` with a `transform` (`diff`, `pct_change` and the
  other changes) on a daily series no longer fails with a `ValueError` when
  Valet returns no observations for the dates asked (for example a
  `start_date` after the newest row). It now returns the series with no
  transformed points.
- `wds_get_changed_series_list` and `wds_get_changed_cube_list` no longer fail
  when WDS sends an explicit `null` for an entry's `vectorId`, `coordinate` or
  `releaseTime`: a null becomes `0` for the vector id and an empty string for
  the others, as an absent field already did.
- `calc_rank` and `calc_cagr` now work on bimonthly StatCan series (six
  periods a year, WDS frequency code 7). Before, every `period`, `start` or
  `end` was refused with "give a period of that frequency", which no form
  could satisfy. Write a month (`2025-04`): it names the two-month period that
  contains it (March and April, labelled `2025-03`). Any other form for a
  bimonthly series (a year, a quarter, a day) is still refused.
