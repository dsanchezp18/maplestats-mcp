### Added

- A Julia client, `clients/julia/` (`MapleStats.jl`, not registered yet): `search_tools`,
  `plan_query`, `call_tool`, `get_data` (a DataFrame with `citation`, `provenance` and
  `left_out` in its metadata) and `reproduce_code` over the hosted `/mcp` endpoint,
  using HTTP.jl. Its row rule is `reproduce_workbook`'s. Design in `docs/clients.md`.
