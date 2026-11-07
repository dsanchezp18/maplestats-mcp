### Added

- An R client, `clients/r/` (`maplestats`, not on CRAN yet): `ms_search_tools()`,
  `ms_plan_query()`, `ms_call_tool()`, `ms_get_data()` (a tibble with `citation`,
  `provenance` and `left_out` attributes) and `ms_reproduce_code()` over the hosted
  `/mcp` endpoint, using httr2. Its row rule is `reproduce_workbook`'s. Design in
  `docs/clients.md`.
