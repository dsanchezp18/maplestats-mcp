### Added

- `dfo_landings_*` (2 tools): Fisheries and Oceans Canada commercial fisheries
  landings from open.canada.ca (Open Government Licence - Canada, commercial
  use allowed). `dfo_landings_get_landings` returns tidy rows (year, province
  or territory, species group, species, quantity in tonnes, value in dollars,
  suppressed and total flags) for sea fisheries 1990-2024 and freshwater
  fisheries 1990-2019, in English or French; `dfo_landings_list_tables` lists
  the years and files.
