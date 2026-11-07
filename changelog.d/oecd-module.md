### Added

- OECD Data Explorer module, `oecd_` (4 tools): `oecd_compare_countries` puts Canada
  beside the G7 or other OECD countries on 16 preset indicators (Economic Outlook
  projections, GDP per hour worked, productivity growth, GDP per capita, unit labour
  costs, PPPs, tax-to-GDP, real house prices, price-to-income and price-to-rent ratios,
  the composite leading indicator); `oecd_search_datasets`, `oecd_describe_dataset`
  and `oecd_get_data` reach any of the OECD's 1,552 dataflows by SDMX key as tidy rows.
  The module keeps to the OECD's limit of 60 data downloads an hour (at most 50, cached)
  and flags datasets whose metadata point to third-party owners.
