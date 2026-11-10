### Added

- `socrata_query_dataset_rows` takes optional `group` and `having` (SoQL's
  `$group` and `$having`), so counts and sums by category are computed by the
  portal over every matching row, e.g. Calgary's 2025 building permits by
  permit type with `select="permittype, count(*) AS n"`, `group="permittype"`.
  `order` was already there.

### Fixed

- A SoQL query that Socrata rejects now says why. An aggregate without a
  `group` used to fail with a message cut off inside the dataset's internal
  column list ("SELECT `permitnum`, `statuscurrent`, ..."), which read like a
  complaint about unrelated columns. The error now gives Socrata's own reason
  and code ("Column 'permittype' is not in group by
  (query.soql.column-not-in-group-bys)") with a hint: list the other selected
  columns in `group`, or, for an unknown column, use the `field_name` values
  from `socrata_get_dataset`.
- `reproduce_code` for a grouped `socrata_query_dataset_rows` call now carries
  `$group` and `$having` into the script's URL, so the script returns the same
  grouped counts as the tool instead of raw rows.
