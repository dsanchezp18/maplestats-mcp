### Changed

- The transit smoke test accepts a schedule published up to 14 days before it starts (exo
  La Presqu'ile's 2026-11-09 feed), tries the next three Wednesdays for departures, and
  reports a feed whose server is down (STS Sherbrooke, 2026-11-03) as SKIPPED rather than
  stopping the whole run.
