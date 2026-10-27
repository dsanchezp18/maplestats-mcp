### Added

- An optional hybrid `search_tools` (Phase 2 of the discovery plan), off by default:
  with `MAPLE_SEARCH=hybrid` and the `semantic` extra (`pip install
  "maplestats-mcp[semantic]"`, then `python -m maplestats_mcp.shared.semantic build`),
  BM25 is fused with a local multilingual embedding model (multilingual-e5-small, int8,
  MIT) by reciprocal rank fusion. Only tool metadata is indexed and queries are embedded
  on the server, never sent to an API. It ranks more first answers right, French above
  all, but not more in the top five, and costs about 220 MB of memory, so it stays off;
  `tests/discovery_benchmark/phase2.md` has the measurements. Without the extra or the
  index, hybrid mode logs why and searches by BM25.
