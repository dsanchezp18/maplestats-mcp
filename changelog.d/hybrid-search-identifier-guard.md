### Changed

- `search_tools` with `MAPLE_SEARCH=hybrid` (the optional semantic prototype, off by default):
  a query that names a tool, a tool family, a StatCan table number or a vector is now ranked by
  BM25 and the identifier boosts alone, as in the default mode. Fused with the embedding, such
  queries ranked a wrong tool first more often (identifier probes R@1 0.79 to 0.69). The default
  `search_tools` is unchanged. Phase 2 re-measured on 2026-11-07 (gate still not met) in
  `tests/discovery_benchmark/phase2.md`; Phases 3 and 4 proposed in `docs/discovery-phases-3-4.md`.
