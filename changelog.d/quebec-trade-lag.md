### Fixed

- `electricity_quebec_get_trade`: the latest hours fill `limit` again when Hydro-Québec
  publishes exports more than 12 hours late. On 2026-11-07 the lag reached 14 hours,
  and a request for the latest 3 or 6 hours returned fewer; 36 extra hours are now
  fetched before the unpublished ones are dropped.
