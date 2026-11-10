### Added

- `/stats` now says why calls failed: `error_codes` (failures by code) and
  `by_error` (failures per tool, by code), using the codes that lead every tool
  error (`not_found`, `invalid_input`, `upstream_unavailable`, `upstream_error`,
  `data_locked`, `unknown_tool`, `error`). Only that fixed list is kept, never the
  message or the arguments. The codes are saved to `MAPLE_USAGE_STATS_FILE` with the
  call counts; failures counted before this release show as `uncoded`.
