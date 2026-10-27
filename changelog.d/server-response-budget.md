### Added

- One response-size budget for every tool. When a result's JSON is larger than
  `MAPLE_RESPONSE_MAX_BYTES` (default 200,000 bytes), the server keeps a prefix
  of its largest lists (the most recent rows for a time series listed oldest
  first, and an even share across lists of the same field, such as each
  series' observations), so the result still matches the tool's output schema,
  and adds a sentence to `provenance.limits` saying what was cut and how to get
  the rest: narrower arguments, the source's download tool, or
  `reproduce_code`. Results within the budget are unchanged; geometry is never
  cut. Tools that had no bound of their own, and per-tool caps set above the
  budget, are now held to it.
