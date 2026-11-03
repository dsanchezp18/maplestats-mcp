### Added

- Job Bank wages from Employment and Social Development Canada (`jobbank_*`, a new
  module): low, median and high hourly or annual wages for the 516 NOC 2021 occupations,
  for Canada, provinces and territories and 86 economic regions, from the yearly "Wages"
  dataset on open.canada.ca. `jobbank_search_occupations` finds NOC codes by title
  (English or French) or code prefix, `jobbank_get_wages` gives one occupation's wages
  by region or province, `jobbank_compare_occupations` compares 2 to 25 occupations in
  one region, and `jobbank_list_regions` lists the economic regions. The newest release
  is found from the dataset at run time (2025 on 2026-11-03), with `release_year` for
  the 2023 and 2024 releases. Each row carries the wage unit, the data source Job Bank
  names, the reference period and whether the cell is published; each result cites the
  release. A fitness-for-use caution says these are Job Bank estimates from the Labour
  Force Survey and other sources, not a Statistics Canada table. OGL-Canada.
- IRCC application processing times (`ircc_processing_list_application_types`,
  `ircc_processing_get_time`): IRCC's current times for 57 application types read from
  the JSON files behind its "Check processing times" tool (visitor visas, study and work
  permits from inside or outside Canada, by country of residence where they vary; Express
  Entry and other permanent residence programs; sponsorship; refugees; citizenship; PR
  cards and documents), with people waiting for forward-looking types and IRCC's
  last-updated date. The files have no documented API: a change in their shape raises an
  error naming the file. Point-in-time estimates, cached for an hour, with a
  fitness-for-use caution that they are not a time series.
