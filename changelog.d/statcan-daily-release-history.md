### Fixed

- `statcan_daily_search_archive`: the query matched only as one phrase, so "gross
  domestic product by industry provinces" missed "Gross domestic product by
  industry: Provinces and territories", and a year in the query missed a release
  whose year is its reference period. Every word of the query now has to appear in
  the title or reference period, in any order, accents ignored, with question words
  ("when did", "publish") and short connecting words left out. When no release
  holds every word, the releases matching the most words come back with a `note`
  saying so (at least half of the words, and two).

### Changed

- `statcan_daily_get_release_calendar`: with `upcoming_only=False` the history now
  includes every past Daily release matching the query (`kind: "daily_release"`,
  from the full archive), not only key indicators and catalogue products. In the
  Maple Test, "when were the provisional poverty estimates for 2025 released"
  searched the calendar's history and found nothing, though The Daily released them
  on 2026-11-04.
- `wds_get_cube_metadata`: `release_time` now says it is the table's latest release
  or revision, not when a reference period was first published, and points to
  `statcan_daily_search_archive` for release dates. An answer gave a table's
  November revision date as the date its year was first published (in May).
