### Added

- `boc_search_series`, `boc_get_series` and `boc_get_observations` say whether
  a Valet series is still updated: each series carries `status` (`active` or
  `discontinued`), `last_observation` and, where the Bank's replacement is
  known, `successor`. A series counts as discontinued when its newest
  observation is far older than its frequency allows, found from one
  `recent=1` request per 50 series, not from a fixed list. The legacy noon and
  closing exchange rates (e.g. `IEXE0101`, the USD/CAD noon rate, last value
  2017-04-28) name their daily-average successors (`FXUSDCAD`, and
  `FXM{ccy}CAD`/`FXA{ccy}CAD` for the monthly and annual averages). Valet still
  serves these series; before, nothing said they had stopped.
- Bank of Canada `FX*` exchange rates carry a caveat (in each series' `note`,
  or `provenance.caveats` for observations): a single indicative daily average
  per currency, published by about 16:30 ET, not a transactional rate.

### Changed

- `boc_search_series` and `boc_search_groups` also match entries holding every
  word of a query, after the exact substring matches: "US dollar noon" now
  finds "U.S. dollar (noon)".
