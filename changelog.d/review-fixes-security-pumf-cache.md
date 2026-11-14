### Fixed

- HTTP transport: a client over the per-client rate limit no longer holds up
  everyone else. Its 429 response used to be sent while the limiter's shared
  lock was held, so a client slow to read that response stalled the rate
  check of every other request until it did.
- `statcan_pumf_tabulate`: a table with bootstrap standard errors (EICS 2024,
  CSWC 2024-2025) downloads the survey's ZIP once instead of twice. The data
  file and the bootstrap weights are now extracted from the same download.

### Security

- `statcan_pumf_tabulate`: the microdata download now checks every redirect
  like the PUMF listing and codebook reads do, and refuses with an error a
  redirect to plain http, an IP address, localhost, or a host that is neither
  the publisher's own site nor a known file host. It used to follow a
  redirect to any host.
