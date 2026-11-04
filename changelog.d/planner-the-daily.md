### Added

- `plan_query` has a topic for The Daily: a question about what StatCan said in a release ("What
  did StatCan say about the September trade numbers?", "note to readers", "communiqué de
  Statistique Canada") now plans `statcan_daily_get_releases`, then `statcan_daily_get_article`
  for the full text and PDF, then the tables for the figures. "The daily", "le quotidien",
  "press release" and "communiqué" count only next to a word naming StatCan, so the daily
  average temperature or a city's press release stays off it.
