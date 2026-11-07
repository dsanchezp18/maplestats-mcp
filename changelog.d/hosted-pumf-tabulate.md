### Changed

- The public endpoint (`https://mcp.maplestats.danielstats.io/mcp`) now offers
  `statcan_pumf_tabulate`. It runs on 1 vCPU and 2 GiB instead of 0.5 vCPU and 1 GiB,
  and keeps downloaded microdata files on its Azure file share (at most 5 GB), so only
  the first table from a file waits for the download. The README, the Connect, FAQ and
  StatCan pages no longer say the tool is off there. The Render backup keeps it off.

### Fixed

- `statcan_pumf_tabulate`: queries run on two DuckDB threads. On a many-core machine
  with `MAPLE_DUCKDB_MEMORY_LIMIT` set, DuckDB's default thread count ran out of memory
  on the Census 2021 individuals file (384MB limit) and on the EICS 2024 bootstrap join
  (384MB and 512MB); two threads finish both inside 384MB.
