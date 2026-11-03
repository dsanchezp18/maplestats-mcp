### Security

- `wds_query_series` is off by default when serving HTTP (`MAPLE_QUERY_SERIES=1`
  turns it back on) and on for local installs: DuckDB's memory limit does not cover scalar functions that build large
  lists or strings, so a single query could exhaust a small instance's memory, and the
  time limit does not interrupt one long operator.
