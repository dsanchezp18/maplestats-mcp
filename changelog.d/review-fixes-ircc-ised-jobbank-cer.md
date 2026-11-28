### Fixed

- `ised_ip_horizons_list_files`, `ised_ip_horizons_get_dictionary`, `ised_ip_horizons_get_patent`
  and `ised_ip_horizons_search_patents`: `lang="fr"` now returns the French provenance
  (freshness, limits, coverage and the `/data/fr/` dataset page) and French errors. The tools
  dropped `lang` before calling the client, so a French call got English text although the
  client had the French wording.
- `ircc_monthly_query`: with `period="year"` or `"quarter"` the result now says when a
  period is the sum of only part of its months (for example the latest year, or a first year
  that starts in October), naming the period and the months covered, so the latest period no
  longer looks like a sharp drop next to full ones. The sums are unchanged. Month cells written
  as full English or French names, and quarters written as "Q1 2024" or "T1", are now read.
  Rows whose month, quarter or year still cannot be read are counted in the note instead of
  being pooled into one `period: null` row without a word. When `limit` cuts through the
  earliest period of a chronological result, the note says how many of its rows are shown.
- `ircc_processing_get_time`: a time written "About 1,234 days" is now 1,234 days and not 234,
  and decimals ("1.5 years", "1,5 an") are read. A compound time such as "1 year 6 months" is
  summed (18 months) instead of read as "6 months", so the longest-first sort by country is
  right. A range such as "3 to 6 months" still gives its upper bound, and "10 business days"
  and "10 working days" are read like "10 jours ouvrables".
- `cer_query_file`: `start` and `end` compare at the precision of each row's date, so a file
  whose only date column is a year keeps its 2024 rows for `start="2024-06"`, and a month row
  is kept when its month overlaps a day bound. Quarters ("2024-Q1", "Q1 2024") and
  month/day/year dates that can be read in only one order ("01/31/2024") are now read. Rows
  whose date still cannot be read are no longer dropped or sorted as the oldest without a
  word: `provenance.limits` says how many there are.
- `ircc_list_express_entry_rounds`, `ircc_get_express_entry_round` and
  `ircc_get_latest_express_entry_round`: a feed that answers `{"rounds": []}` (an outage stub)
  is now an upstream error and is not cached for six hours; it used to be returned as zero
  rounds. `ised_cipo_search_trademarks`: a 200 answer without `docs` is no longer cached for
  an hour, so the next call asks CIPO again.
- `jobbank_*` tools: a wages release whose resource `name` does not match "<year> Wages" but
  whose English `name_translated` does is now found, instead of being skipped in favour of the
  older pinned release.
- `ircc_backlog_get_percentages`: the `since`, `until` and `program` argument errors are now
  in French when `lang="fr"`.
