### Added

- `cmhc_get_table_data` takes an optional `aggregate`: `"annual"` sums a monthly
  flow time series (housing starts (actual), completions, absorbed units, with
  `row_field="TIMESERIES"`) into calendar-year totals, and `"ytd"` into January
  to the latest month for every year, so Edmonton's January to September 2026
  starts compare with the same months of 2025. Agents had been adding up the
  monthly rows by hand. `aggregation_note` (also in `provenance.coverage`) says
  the totals were summed by MapleStats from CMHC's monthly values and which
  incomplete years were left out. Stocks (inventories), rates (starts SAAR),
  prices and rental-market values are refused, never summed. The annual totals
  match HMIP's own annual export of the same table.
- `cmhc_get_table_options` says which axis each label names (`breakdown`:
  `"column"` for HMIP's "By:" list, `"row"` for "Display Options:"), and keeps
  the row label of the default table ("Survey Zones") as well as its column
  label ("Bedroom Type").

### Fixed

- A Rental Market Survey table fetched without a `dwelling_type_desc_en` filter
  is CMHC's combined row and apartment figure (Edmonton's 2025 average rent:
  $1,493, against $1,464 for apartments only), and nothing in the result said
  so. `applied_filters` now includes CMHC's own defaults, `default_filters` names
  the ones CMHC chose, and `filter_notes` gives, for each filter, the value
  applied and the other values that can be passed.
- `cmhc_get_table_data` refused `column_field="Bedroom Type"` on "% Change of
  Average Rent", although "Average Rent ($)" accepts it: that table has a single
  column breakdown, so HMIP lists no column labels for it. The label is now
  accepted there when the table's own title names it, a column code HMIP lists
  only in a link (`RENTQUARTILE`) is accepted as given, and a wrong label is
  refused with the valid column and row labels and their codes listed
  separately.
