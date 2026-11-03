### Security

- `wds_query_series`: one query could exhaust the server's memory. DuckDB's
  `memory_limit` does not cover scalar functions that build one large list or
  string, and its interrupt acts only between operators: with a 256 MB limit,
  `SELECT len(range(100000000))` reached 7 GB, `SELECT repeat('x', 10000000)
  FROM range(500)` 9.6 GB (the 500-row cap did not bound bytes), and `SELECT
  len(range(1000000000))` had the process killed, each running 16-29 s past
  the 5 s limit while holding a worker thread and a request slot. The SQL now
  runs in its own process with one thread, an address-space cap
  (`MAPLE_QUERY_MEMORY_MB`, default 256; enforced on Linux, where those queries
  now fail in under half a second with an invalid-input error) and no disk
  spilling, killed at the time limit, at most `MAPLE_QUERY_MAX_CONCURRENT`
  (default 2) at once; the server waits on it without a thread. Results are
  capped at 1,000,000 characters and one text cell at 50,000, each with an
  error that says what to change. A normal query takes about 0.15 s longer.
- `wds_query_series`: a SELECT holding a data-modifying CTE (`WITH x AS (DELETE
  FROM obs RETURNING *) SELECT ...`) ran; any INSERT, UPDATE, DELETE or MERGE
  in the statement is now refused. Statements are classified on a locked
  connection instead of DuckDB's default one, and duckdb 2.0.0 or later is
  required (1.5.5 read a file while classifying `PRAGMA import_database`).
- `wds_query_series`: DuckDB's error messages are cut to their first line, with
  file paths removed (`duckdb_extensions()` showed the home folder).

### Fixed

- DuckDB spilled to `.tmp` in the working directory, which in the Docker image is
  `/app`, owned by root, so spilling past `MAPLE_DUCKDB_MEMORY_LIMIT` failed
  (patent, open-database, microdata and tariff queries). Spills now go to a
  subfolder per query of the system temp folder (`MAPLE_DUCKDB_TEMP_DIR`),
  removed when the query ends, at most `MAPLE_DUCKDB_TEMP_MAX_GB` (default 1).
