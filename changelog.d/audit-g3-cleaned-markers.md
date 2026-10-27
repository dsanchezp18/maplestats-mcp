### Fixed

- `finance_frt_get_table`, `finance_fiscal_monitor_get_tables`: cells published as "-",
  "..", "n/a" or "s.o." all became null, so nil and not available looked the same. A new
  `symbols` list keeps each marker as published, with its row and column; a Fiscal Monitor
  column holding only markers is no longer dropped as empty.
- `isc_*`: whole numbers were read by stripping every non-digit, so "12.5" became 125 and
  "-3" became 3. Only thousands separators are dropped now; anything else that is not a
  whole number is null.
