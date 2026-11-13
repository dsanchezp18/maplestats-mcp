### Fixed

- `sdmx_get_data`: with a transform, `end_period` now keeps the whole end period.
  `end_period="2024"` on a monthly series cut the transformed points and the
  observations at 2024-01; it now keeps through 2024-12 (and `"2024-Q1"` keeps
  January to March).
- `sdmx_get_data`: the note that the latest periods are not published ("..")
  now sees the last published period, as `wds_` results do. A ".." gap inside
  or at the start of a series was reported as the latest periods being
  unpublished.
- `statcan_pumf_` codebooks: a Stata value-label set attached to several
  variables (`label values q1 yn`, `label values q2 yn`) now labels every one
  of them, not only the first.
- `reproduce_code` for `statcan_indicators_get_indicators`: the scripts now keep
  the rows the tool keeps. They require every meaningful query word in the
  title in any order (with the tool's alternatives, such as "inflation" for
  "consumer price index"), read a province named in the query, and map a place
  name, abbreviation or SGC code in `geo_code` to the feed's own code. Before,
  `"unemployment rate Alberta"` gave an empty table, `geo_code=48` matched
  nothing and `geo_code="AB"` failed; the Julia and Excel Power Query scripts
  also failed to read the nested title. The scripts compare titles with their
  accents, which the tool ignores, and their notes say so.
- `reproduce_code`: a blank word filter no longer produces a script with an
  empty filter (a syntax error in Python and Stata, an empty condition in
  Power Query). The IRCC Express Entry `program` filter is now matched as one
  phrase across the round's name and program, as the tool matches it, not word
  by word.
- `check_answer`: a Statistics Canada outage while re-reading a figure is now a
  "not re-read" note, not "No value is published", "not a StatCan series" or
  "cannot be computed". When the table's metadata does not answer, a note says
  its geography, seasonal adjustment and unit were not checked, instead of
  skipping them silently.
- `check_answer`: a Bank of Canada figure cited for a year, quarter or month of
  a daily rate now matches the period's average or total, as StatCan figures
  do. A correct annual average was flagged and the fix said to use the last
  day's value.
