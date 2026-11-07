### Added

- Calculations across series, done by MapleStats with the formula shown instead of by
  the assistant: `calc_ratio` divides one StatCan or Bank of Canada series by another,
  period by period, after applying StatCan's scale factors (a province's share of
  national employment, rent over income with `frequency='annual'`); `calc_rank` ranks
  places for one period, from a list of series or a table coordinate with `*` at the
  dimension to rank across, with ties sharing a rank; `calc_cagr` gives the compound
  annual growth between two periods, with the number of years; `calc_count_changes`
  counts and lists the times a series moved in a window, such as the Bank of Canada's
  policy rate decisions (Valet `V39079`). Every result carries each input's citation
  (table, vector, release or retrieval date) and the values used. Series of different
  frequencies are refused unless `frequency` and `aggregation` convert both; an index
  divided by another unit, current by constant dollars, a ranking across units and the
  compound growth of a rate are refused with the fix.
