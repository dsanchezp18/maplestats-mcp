### Added

- Every tool error starts with a machine-readable code, then the message, then the
  suggested fix: `[invalid_input]`, `[not_found]`, `[upstream_error]`,
  `[upstream_unavailable]`, `[data_locked]`, `[unknown_tool]` (else `[error]`), so an
  assistant can branch on the kind of failure without parsing the sentence.
- `provenance.lang`: the language MapleStats wrote the result's own text in (`en` or `fr`).
- The weekly live workflow (`smoke.yml`) rebuilds the Maple Test v1 and v2 answer keys
  from the sources (`--check`) and opens the smoke-failure issue when a published value
  was revised or a trap no longer holds.

### Fixed

- Live smoke scripts that stop at an upstream outage no longer report PASSED: they say
  SKIPPED and exit 75, so a source that is down week after week shows in the weekly run.
