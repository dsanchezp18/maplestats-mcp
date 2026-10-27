### Added

- Six cross-source workflow prompts, in English and French (`lang`), shown in
  a client's prompt menu: `labour_market_snapshot` (Labour Force Survey
  headline and SEPH earnings, with the caution against comparing the two),
  `refresh_with_latest_release` (release calendar, The Daily, changed tables,
  revisions and vintages), `housing_affordability_scan` (CMHC rents and
  vacancy, CPI shelter, Bank of Canada rates), `inflation_check` (all-items
  CPI, the Bank of Canada's core measures and their first estimates with
  `wds_get_series_as_of`), `compare_province_with_peers` and
  `find_and_cite_dataset`. Each ends by asking the assistant to cite the
  provenance and pass on its caveats.
