### Fixed

- A tool call that runs past the server's time limit (120 s by default) now carries the
  `[upstream_unavailable]` code and the "retry in a minute" fix, as a request timeout
  does. It was coded `[error]`, so a slow `tc_recalls_search` on 2026-11-07 failed the
  live smoke test instead of being skipped as an outage.
