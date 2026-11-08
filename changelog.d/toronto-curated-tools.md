### Added

- `toronto_*` (5 tools): City of Toronto open data from the portal's DataStore
  tables, as tidy rows with the dataset citation and the Open Government Licence
  – Toronto. `toronto_get_neighbourhood_profile` gives one of the 140
  neighbourhoods' census indicators (2016, 2011, 2006, 2001) beside the city
  total; `toronto_get_apartment_evaluations` and
  `toronto_summarize_apartment_scores` read RentSafeTO apartment building scores
  by building, ward or property type; `toronto_summarize_short_term_rentals`
  counts registered short-term rentals by ward, property type or FSA;
  `toronto_search_dinesafe` searches DineSafe restaurant inspections.
- `docs/examples/toronto/`: a worked example (RentSafeTO scores by neighbourhood
  beside the 2016 renter share) with a script that re-fetches the data.

### Changed

- `ckan_read_resource` and `ckan_describe_resource` now give the precise reason
  they refuse Toronto's files: the portal's robots.txt disallows
  `/dataset/*/resource/*/download/*` for automated agents (the API stays
  allowed). `plan_query` sends Toronto restaurant inspection questions to
  `toronto_search_dinesafe`, whose table answers again after the HTTP 500
  errors of 2026-10-27.
