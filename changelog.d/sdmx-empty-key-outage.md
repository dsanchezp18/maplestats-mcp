### Fixed

- `sdmx_get_data` no longer says StatCan "does not publish this combination" when
  StatCan itself is not answering. A key matching no series comes back as an empty
  document, and the error names what is missing from the table's structure; when
  that structure does not load either (a timeout, a refusal, a locked table), the
  call now fails as upstream unavailable and asks to try again in a few minutes. On
  2026-11-24, near midnight Eastern, StatCan answered `18100004` key `2.2` (Canada,
  all-items CPI, which exists) with an empty document while `getCubeMetadata` timed
  out, and the server told the caller the series was not published.
- The live check against Azure counts a `check_answer` result whose figure was not
  re-read because WDS did not answer as a skip, as it already did for an
  upstream-unavailable error, not as a failure.
