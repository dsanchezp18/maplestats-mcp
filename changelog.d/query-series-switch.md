### Security

- `wds_query_series` can be turned off with `MAPLE_QUERY_SERIES=0`, and the hosted server
  turns it off: DuckDB's memory limit does not cover scalar functions that build large
  lists or strings, so a single query could exhaust a small instance's memory, and the
  time limit does not interrupt one long operator. Local installs keep the tool.
