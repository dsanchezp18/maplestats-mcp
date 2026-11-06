### Fixed

- Tool errors: an upstream HTTP 5xx now carries the `[upstream_unavailable]` code
  and the "source is down or slow, retry in a minute" fix, for every source. About
  80 call sites raised a 5xx as a plain upstream error, so a Borealis outage on
  2026-11-05 (`borealis_*`, `elections_results_get_historical`) told agents the
  source had answered with an error. A 4xx or an unexpected response is unchanged.
