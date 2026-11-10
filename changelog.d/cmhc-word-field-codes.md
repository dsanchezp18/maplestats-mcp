### Fixed

- `cmhc_get_table_data` refused field codes that are words, such as Core Housing
  Need's `column_field="HouseholdType"` and `row_field="Province"`, even though
  `cmhc_get_table_options` lists exactly those codes. It treated only numbers and
  `TIMESERIES` as codes and looked anything else up as a label. A value is now
  matched against the table's own codes first (in any case, sent in HMIP's
  spelling), then against its labels.
