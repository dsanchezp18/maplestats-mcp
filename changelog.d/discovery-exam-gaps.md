### Changed

- `boc_search_series` and `boc_search_groups` find the Bank of Canada's core
  inflation measures whatever the query adds or how it spells them: when no
  entry holds every word of the query, they read each hyphenated word run
  together ("CPI-X" as `CPIX`, "cpitrim"), then rank entries by the rarer query
  words they hold, and `provenance.coverage` says the result is that partial
  match. "CPI-trim inflation", "core inflation CPI-trim" and "CPI-trim
  year-over-year" returned nothing before; they now start with `CPI_TRIM`.
- `boc_search_groups` with "Banking and Financial Statistics" or "BFS" in the
  query searches only the groups named by a BFS table code (`A4_RATES_MONTHLY`,
  `C1_MONTHLY`, `E1_MONTHLY` and 82 more), since no group label names the
  publication.
- `statcan_surveys_search_surveys` matches a survey's acronym and whole words
  of its name: "IPPI" gives 2318 (Industrial Product Price Index), "RMPI" 2306,
  "LFS" 3701, "EICS" 4428, "SEPH" 2612, and the French "EPA", "IPMB" and "ECAE".
  Before, the query was a plain substring of the name, so "IPPI" found only the
  Coastwise Shipping Survey and "LFS" or "EICS" found nothing.
- `plan_query` routes questions on core inflation (CPI-trim, CPI-median,
  CPI-common, also table 18-10-0256-01), price levels across cities (the
  discontinued inter-city index, table 18-10-0003-01), hedonic quality
  adjustment (the CPI Reference Paper), Labour Force Survey definitions such
  as involuntary part-time (the Guide to the Labour Force Survey), the Bank of
  Canada's Banking and Financial Statistics, and IMDB survey ids (a new
  survey-metadata topic), in English and French.
- Docstring keywords so `search_tools` finds `boc_search_series` and
  `boc_search_groups` for core inflation and Banking and Financial Statistics,
  `statcan_surveys_search_surveys` for survey ids and acronyms, and
  `statcan_surveys_get_survey_metadata` for survey definitions, which names the
  survey guides that hold them.
