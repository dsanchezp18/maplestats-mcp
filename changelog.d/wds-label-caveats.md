### Fixed

- StatCan WDS data results: a series whose latest periods are ".." (status 1,
  "not available for a specific reference period") now gets a note naming those
  periods and saying StatCan has not published them, instead of only the status
  text on each null value. Only trailing periods count, since rows before a
  series starts are ".." too. For 36-10-0711's current-dollar "All industries"
  series, ".." for 2024 and 2025 in every province and territory while the
  chained-dollar series has both years, the note points to 36-10-0222-01, which
  publishes current-price GDP for those years at market prices rather than basic
  prices.
- StatCan WDS data results: an unadjusted series in a table whose title says
  "seasonally adjusted" (14-10-0287, "seasonally adjusted and trend-cycle") now
  gets a note naming its own Data type member ("Unadjusted"), since the title is
  in every citation. A "Trend-cycle" series gets a note that it is a smoothed
  version of the seasonally adjusted one, which is the headline.

### Changed

- StatCan WDS data results: a percentage change, or a contribution to one, in a
  table "at annual rates" now gets a note that it is the change from the
  previous quarter or month, not an annualized rate. 36-10-0104's "Chained
  (2017) dollars percentage change" for GDP was 0.8 in 2026-Q2, which is
  2,524,127 / 2,503,604 - 1. The note names the table's annualized member when
  there is one ("Contributions to percent change, annualized").
- StatCan WDS data results: a contribution to percent change on a "Less:" line
  or one of its children (36-10-0104's "Less: imports of goods and services")
  now gets a note that StatCan publishes it with the sign of the line's own
  change, so it is subtracted when adding components up to the total. WDS sends
  +0.364 (annualized) for 2026-Q2 while imports rose, and GDP's 3.316 is reached
  only with it subtracted.
