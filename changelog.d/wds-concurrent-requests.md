### Changed

- `wds_get_data_from_vectors`, `wds_get_data_by_reference_period_range` and
  `wds_get_data_from_cube_coord` ask StatCan's independent requests together instead of
  one after another: the data and the code legend at once, the series information and
  each table's metadata beside them, and several tables' metadata at the same time. A
  cold call for three vectors went from about 3.0 s to 1.3 s (live, 2026-11-06); the
  hosted server's median for `wds_get_data_from_vectors` was 6.4 s. Series information is
  now cached, so a `transform` no longer asks for it twice or again on every repeat.
