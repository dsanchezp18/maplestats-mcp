### Fixed

- StatCan tools: when the vector, SDMX or CIMT endpoints on `www150.statcan.gc.ca` timed
  out, the circuit breaker paused the whole host, so The Daily, the indicators, table
  metadata and the file downloads failed too although StatCan was answering them. The
  breaker now keeps one state per path group on that host (WDS, SDMX, CIMT, The Daily,
  files, pages), so a slow group pauses only itself. `/stats` and `docs://status` list
  these as `www150.statcan.gc.ca/<group>`.
