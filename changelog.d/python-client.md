### Added

- A Python client, `clients/python/` (`maplestats`, not on PyPI yet): `search_tools`,
  `plan_query`, `call_tool`, `get_data` (a polars frame with citation and provenance)
  and `reproduce_code` over the hosted `/mcp` endpoint, with no MCP SDK. Its row rule
  is `reproduce_workbook`'s, and `tests/test_client_tidy_parity.py` keeps the two equal.
  Design in `docs/clients.md`.
