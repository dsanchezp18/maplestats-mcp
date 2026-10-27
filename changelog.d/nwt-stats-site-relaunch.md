### Changed

- `nwt_stats_list_files`, `nwt_stats_search_files`: the NWT Bureau of
  Statistics relaunched statsnwt.ca, and every topic page now answers a
  redirect or 404 at its old address. The topics point at the new pages, and
  each file's `section` now starts with the collapsible block it sits in
  (for instance "2021 Census > February 9, 2022: Population and Dwelling
  Counts"). Exports of a table shown on a page (`/en/download-xlsx/...`)
  are listed and read as .xlsx files. "(Excel)" and "(Excel File)" are
  dropped from link titles. The module lists about 375 files on 39 topics,
  down from about 630 on 49.

### Removed

- `nwt_stats_*` topic slugs: `census-2021`, `census-2016`, `census-2011`,
  `census-2006`, `census-2001` and `census-1996` are merged into `census`,
  one page for all six censuses; `oil-gas` and `minerals` are merged into
  `oil-gas-minerals`. `manufacturing`, `community-data` (the statistical
  profile of each community), `statistics-quarterly`, `socio-economic-scan`
  and `community-statistics-summary` are removed: the relaunched site has no
  page for them. A call naming a removed slug is refused with the list of
  current topics.

### Fixed

- `nwt_stats_read_file`: the census and community survey pages link their
  files on bearnet.gov.nt.ca, a staging host that asks for a login. Those
  links are read from the same path on www.statsnwt.ca, where the files
  answer.
