### Added

- `statcan_daily_get_release_tables`: reads the tables published inside a Daily
  release (`t003a-eng.htm` and, before 2014, `t131206a003-eng.htm`) as tidy rows,
  with the values as first published, before later revisions: the free source of
  first estimates for surveys with no real-time table, such as the Labour Force
  Survey. Each row has its heading group (a province), parent rows, row, column,
  unit, the cell as published and as a number; each table its title, units,
  notes, sources and CSV link. `tables`, `search` and `limit` (500 by default,
  5,000 at most) keep responses bounded, and `truncated` says when rows were left
  out. Releases from 2012 on, in English and French.
- `statcan_daily_get_article`: new `release_tables` field listing the release's own
  tables (number, title, page).

### Fixed

- `statcan_daily_get_article`: negative numbers in the text are whole again. StatCan
  wraps the sign and first digit in a separate element, and the text came out with
  a space inside the number ("( -1 37,000)" for -137,000 in the January 2018 Labour
  Force Survey release). A Unicode minus is now written "-", and screen-reader
  labels such as "Catalogue number" stay separate from the number that follows.
