### Fixed

- `reproduce_code` and `reproduce_workbook`: when the tool being reproduced fails, the
  error keeps that tool's code. An outage of open.canada.ca on 2026-11-07 came back as
  `[invalid_input]`, which tells an agent to change its arguments; it is now
  `[upstream_unavailable]` (retry later), and likewise for `[not_found]`,
  `[upstream_error]` and `[data_locked]`.
