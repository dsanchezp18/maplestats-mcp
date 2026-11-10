### Changed

- Requests to `www150.statcan.gc.ca` (WDS, SDMX, CIMT) through the shared HTTP
  helpers keep their connection open between calls; a retry still goes out on
  a fresh connection so it can reach another backend. Measured from the hosted
  container on 2026-11-09: median 20 ms per request instead of 109 ms.
