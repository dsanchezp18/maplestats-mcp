### Fixed

- Tool time limit: a call made through `call_tool` (every HTTP client's path) that ran
  out of time waiting on a publisher was reported as the server's own slow work;
  nested calls now share one count of pending requests. A deadline that falls in a
  retry's backoff, a Retry-After wait or a publisher's rate-limit wait, within 35 s of
  the last request, also counts as waiting on the source.
- `/stats`: two processes saving the counts at once (old and new replica during a
  deploy) no longer lose one's counts on Linux: the read-add-replace runs under an
  advisory lock.
- `oecd_` inflation preset: where a country publishes both, the national CPI is kept
  over the harmonised index.
- ISED corporations: the landing-page link points to the current federal corporation
  search page (the old page answers 404).
- Python client: `citations()` runs in linear time (a 200-series result took 87 s).
