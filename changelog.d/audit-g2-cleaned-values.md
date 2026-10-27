### Fixed

- `nrcan_minerals_get_production` and `nrcan_minerals_get_series`: 1991-1998 values
  marked revised ("386 ʳ") were read as not available; they are now numbers. A new
  `value_as_published` keeps each cell's text, and `provenance.limits` counts values that
  are not numbers and data rows shorter than the header. `nrcan_minerals_get_series` names
  the years where the commodity matched rows in several groups and the group whose row
  it shows.
- `hc_nhp_get_product`: a dose age, dose or frequency given only as a minimum or a
  maximum lost the figure ("year(s)" for "19+ year(s)"); it is now shown as "19+" or
  "≤12". `provenance.limits` says these texts, and `potency`, are composed by MapleStats,
  and that the source's 0 for "not given" is left out.
- `ised_clean_growth_get_federal_investment`: an amount with a scale word other than
  billion or million was read as plain dollars; it is now null. Each table row has a new
  `value_as_published`, `headline.not_found` lists headline figures whose sentence was not
  found in the page, and `provenance.limits` names both.
- `pmra_get_residue_limits` has a new `mrl_as_published` with the extract's own text, and
  says when a value is not a number. The PMRA tools count extract rows skipped for a wrong
  number of cells in `provenance.limits`, and `pmra_get_product` raises an upstream error
  when the record's row is malformed instead of answering "no product".
- `ised_ip_horizons_get_patent` and `ised_ip_horizons_search_patents` say in
  `provenance.limits` when -1/-2 codes, "Unknown" provinces or non-ISO dates in the files
  were returned as null.
- Rows dropped while reading a file are now counted in `provenance.limits` or `notes`:
  `cdc_get_component_prices` (unreadable class or date), `cdc_query_market_data`
  (unreadable dates, and values that are not numbers), `cgc_exports_describe` and
  `cgc_exports_query` (short rows, unreadable year, month or tonnage),
  `recalls_search` and `recalls_summarize` (rows with no numeric notice id),
  `dfo_iwls_get_water_levels` (time steps with a null value) and
  `eccc_datamart_ghgrp_facilities` (rows with no readable year, new `rows_without_year`).
- `eccc_datamart_ghgrp_facilities`: `total_co2e_sum` counted a blank total as 0 without
  saying so. It is now labelled as computed by MapleStats, and a new `total_co2e_blank`
  (with a note) counts the matching records it leaves out.
