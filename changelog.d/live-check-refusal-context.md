### Fixed

- The live check runs `senate_get_vote`'s wrong-session check again. Since
  2026-11-21 each step cleared its tool's earlier result before the call, including a
  step that must be refused and so stores nothing; the refusal of
  `senate_list_votes` for session 41-2 left the next step with no input, and it was
  skipped on every run. A step that must be refused now keeps the earlier result.
- A step that reads the result of a step blocked by Cloudflare on the GitHub runner
  is now skipped as that runner's block, like the blocked step itself, not counted as
  an outage. The Yukon Stats and PUMF file-list blocks used to end every live check
  as "skipped, not a pass" with a warning, hiding the runs where a source was
  really down.
