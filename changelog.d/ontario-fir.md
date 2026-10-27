### Added

- Ontario's municipal Financial Information Return (`on_fir_`, 5 tools), from the
  Ministry of Municipal Affairs and Housing's yearly CSV files, 2000 to 2025 (Open
  Government Licence - Ontario). `on_fir_get_schedule` reads one municipality's
  schedule with its labels (revenue, expenses by function, taxation, reserves, debt,
  tangible capital assets, statistics); `on_fir_compare` puts one line side by side
  across municipalities or up to 10 years, per capita and within one tier;
  `on_fir_list_schedules`, `on_fir_search_municipalities` and `on_fir_search_lines`
  find the year, the MUNID and the line code. A year is downloaded once (about 10 MB)
  and kept as Parquet in `MAPLE_ON_FIR_CACHE_DIR` (cap `MAPLE_ON_FIR_CACHE_MAX_MB`,
  default 500). The newest year is incomplete until every return is filed, and each
  result says how many of the 444 municipalities have filed.
