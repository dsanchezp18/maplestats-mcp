### Added

- `wds_query_series`: computes on the server instead of in the assistant's head.
  It fetches up to 20 StatCan vectors for a reference-period range or the latest
  N periods, loads them into a table `obs` (vector, table, reference period, value,
  scale, status, series title, unit, frequency, geography) and runs one SQL query
  with DuckDB, returning only the result: an annual average, a sum, a ranking, a
  peak. Each series used comes with its citation. The query is read-only and
  sandboxed: a single SELECT (or WITH ... SELECT), no file, network or extension
  access, at most 500 result rows and a 20-second limit. Any other statement, or
  SQL that DuckDB rejects, is an invalid-input error that lists the columns of
  `obs`.
