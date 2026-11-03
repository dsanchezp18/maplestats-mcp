### Added

- Federal proactive disclosure module (`disclosure_*`, 6 tools) over Treasury Board's
  government-wide Proactive Publication tables on open.canada.ca:
  `disclosure_search_contracts` (contracts over $10,000),
  `disclosure_search_grants` (grants and contributions),
  `disclosure_search_travel` and `disclosure_search_hospitality` (ministers, their
  staff and senior officials), `disclosure_summarize` (count and sum of value grouped
  by department, vendor or recipient, program, province, riding, person, title, fiscal
  year and more) and `disclosure_list_datasets` (ids, row counts, last update). Search
  by name, title, department or `owner_org` code, program, province, riding, fiscal
  year, date range and value range, with paging (up to 100 rows per call). Every row
  carries its dataset and resource ids and the open.canada.ca page to cite. The portal
  has no `datastore_search_sql`, so totals are summed by MapleStats from up to 100,000
  matching rows; amendment rows, which restate an agreement's whole value, are
  collapsed to each agreement's latest by default (`value_mode='all_rows'` sums them
  as published).
- Fitness-for-use caveat for every `disclosure_*` result: amendment rows, values in
  CAD with taxes over the whole contract term, and quarterly (contracts, hospitality)
  or monthly (travel) publication with late entries added to past quarters.

### Changed

- The shared CKAN client can send an action as a POST with a JSON body, so a
  DataStore filter listing hundreds of values (every day of a date range) fits.
