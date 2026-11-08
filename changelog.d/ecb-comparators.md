### Added

- European Central Bank Data Portal as a euro area comparator (`ecb_`, 5 tools),
  over the ECB's SDMX 2.1 API, no key. `ecb_get_indicator` gives thirteen
  headline series (the deposit facility, main refinancing and marginal lending
  rates, €STR, the euro in Canadian and US dollars, euro area HICP inflation,
  M3, household loans, mortgage rates and the 10-year yield), each with the
  Bank of Canada or Statistics Canada series to set beside it;
  `ecb_list_datasets`, `ecb_describe_dataset`, `ecb_search_series` and
  `ecb_get_series` reach any series of the ECB's 105 datasets by SDMX key.
  Rows are tidy (date, value, unit, frequency, series id). Free reuse,
  commercial included, with "Source: ECB statistics".
