### Fixed

- `/stats`: a usage-stats file that exists but cannot be read for a moment (a network
  share's transient error) is no longer treated as missing, so a save can no longer
  replace the saved history with only the latest counts.
- Tool time limit: a call that runs out of time while waiting on a publisher is still
  `[upstream_unavailable]` (retry later), but one that runs out while the server is
  computing (a large tabulation or join) is now `[invalid_input]`, asking for a
  narrower request, since retrying it unchanged would time out again.
- `bls_`: data are fetched and cached in fixed ten-year blocks ending this year, so
  different year ranges for the same series reuse one query instead of spending
  another of the 25 unregistered queries a day that all users of the hosted server
  share. Once BLS refuses a query for the daily limit, later calls fail at once until
  midnight UTC instead of each spending a request.
- `ourcommons_` expenditures: a blank amount in a member's report is returned as
  missing (`null`), not 0, and sorts last; totals add the amounts reported.
- `electricity_quebec_get_trade`: a `limit` near the maximum is filled too when
  Hydro-Québec publishes late (the extra hours are no longer capped).
