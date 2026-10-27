### Added

- `wds_get_data_from_vectors`, `wds_get_data_from_cube_coord`,
  `wds_get_data_by_reference_period_range`, `wds_get_bulk_vector_data_by_range`,
  `wds_get_changed_series_data` and `wds_get_series_as_of`: each observation now says
  what its codes mean, beside the integers: `status` ("use with caution", "too
  unreliable to be published"), `symbol` ("preliminary", "revised") and
  `security_level`, in the call's language, decoded from WDS getCodeSets (the same
  wording `statcan_delta`'s legend uses). When getCodeSets does not answer, the codes
  come back undecoded and provenance.limits says so.

### Fixed

- `sdmx_get_data`, `sdmx_get_vector_data`: each observation's own SDMX attributes
  (STATUS_CAN, SYMBOL, SECURITY_LEVEL) are read and decoded into `status_code`/`status`,
  `symbol_code`/`symbol` and `security_level_code`/`security_level`. A suppressed or
  estimated value used to come back as a bare null or number, and a value StatCan
  writes as "NaN" (status F) came back as NaN instead of null.
- `boc_get_observations`, `boc_get_group_observations`: a value Valet sends as text
  that is not a number is still null in `values`, but its text now comes back in the
  row's `non_numeric`, and provenance.coverage counts them; before, it became a null
  with no note. `series` entries also carry Valet's `unit` and `frequency` metadata.
