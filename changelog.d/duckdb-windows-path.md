### Fixed

- `wds_query_series` errors no longer show a Windows path that starts with a single
  backslash (`\.duckdb\extensions\...`); it is replaced by `<path>` like any other path.
