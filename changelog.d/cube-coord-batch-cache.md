### Added

- `wds_get_data_from_cube_coord` takes `coordinates`, a list of up to 300 coordinates of one table, and fetches them in one WDS request (`getDataFromCubePidCoordAndLatestNPeriods` accepts a list of pairs). Each series comes back in the new `series` field, in the order asked, with its own context and, with `transform`, its own computed values; a coordinate WDS cannot serve is listed in the new `failed` field with the reason instead of failing the call. `coordinate` still works as before and keeps the single-series shape. One benchmark question made ten single calls per run.

### Changed

- `wds_get_data_from_cube_coord` caches its data for an hour, as `wds_get_data_from_vectors` does (it was never cached). It fetches the table's metadata beside the data instead of after it, and a `transform` reads the series' frequency from that cached metadata instead of a separate `getSeriesInfoFromCubePidCoord` request, so a cold call waits for two rounds of requests instead of three or four.
- `wds_search_cubes` parses the table inventory and folds its titles once per fetched inventory instead of on every search (about 8,000 tables and 16,000 titles, about 245 ms per search on the hosted server, blocking other requests).
