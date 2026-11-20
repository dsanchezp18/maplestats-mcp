### Changed

- `search_tools` finds StatCan's analysis catalogue and release calendar again: on the
  discovery benchmark the StatCan category's R@5 is back to 1.00 (0.92 before PR #330's
  description rules, 0.96 after them) and overall MRR goes from 0.783 to 0.796, with no
  other question moved. Under the description rules, `statcan_reference_search_analysis`
  carries the everyday words for its own content ("Statistics Canada", "analysing",
  "studies", "research"), `statcan_daily_get_release_calendar` the French ones ("prochaine
  publication", "prochain communiqué", "sera publié"), and `wds_get_data_from_vectors`
  "CPI inflation" (EN/FR), which puts it first for "latest CPI inflation Canada" in both
  search profiles (it was third, tied, in the statistics-only one).
