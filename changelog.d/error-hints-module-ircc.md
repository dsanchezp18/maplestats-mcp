### Changed

- `ircc_get_express_entry_round` without `draw_number` returns the latest
  round, as `ircc_get_latest_express_entry_round` does, instead of refusing
  the call (8 of its 16 calls on the hosted server by 2026-11-10 were errors).

### Fixed

- A tool whose module failed to import on the server now answers
  `[module_unavailable]`, naming the module and the import error, instead of
  `Unknown tool: 'call_tool'`, and `/stats` counts it under that code.
