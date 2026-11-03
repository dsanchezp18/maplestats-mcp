### Added

- `check_answer`: the last call before replying with figures. It takes the
  question and each figure the answer will report (value, unit, period,
  geography, and a StatCan vector, a table and coordinate, or a Bank of Canada
  series), re-reads them from the source and returns only the problems, each
  with a fix: a value that differs from the published one, a missed scale
  factor (thousands, millions), a newer period, a series for another place than
  the question names (with the right coordinate when the table has it), an
  unadjusted series where an adjusted one exists, E, F or suppressed flags,
  current against constant or chained dollars, an index given as dollars,
  chained or not-additive components added together, and surveys a fitness rule
  says not to compare. A figure not published at the asked geography gets the
  route: public microdata when its codebook has the variables (the Canadian
  Income Survey PUMF has no disability variable), else a custom tabulation,
  RTRA or a Research Data Centre, with their access conditions and a pointer to
  `statcan_surveys_search_rtra_datasets` and `statcan_surveys_search_rdc_holdings`.
  `plan_query`'s guidance and the server instructions point to it.
- WDS and SDMX series context: short reading notes derived from StatCan's own
  metadata, added only when it shows the issue: three-month moving averages,
  chained and constant dollars, E, F and x periods named, footnotes saying
  totals are not the sum of their components, archived tables (with the table
  that replaced them) and terminated series, and unadjusted series whose table
  also has the seasonally adjusted one.

### Fixed

- WDS and SDMX series context no longer calls chained (2017) dollars or
  constant dollars "current (nominal) dollars": 36-10-0104 and 34-10-0292 give
  those series the plain "Dollars" unit, and the price basis is now read from
  the member.
