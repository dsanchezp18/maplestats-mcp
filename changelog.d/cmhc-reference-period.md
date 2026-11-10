### Fixed

- `cmhc_get_table_data` dropped the period a table refers to. CMHC states it on
  the line under the export's title ("October 2025", "January 1990 to September
  2026"), and a cross-tab's rows are provinces or centres, so the values came
  back undated. The result now has a top-level `reference_period`, in CMHC's
  words, and a `citation` line that carries it. `provenance.as_of` is set to the
  first of the latest month when the period names a month. Brief mode keeps all
  three.
