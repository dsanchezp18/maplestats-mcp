### Fixed

- `cra_charities_search`, `cra_charities_get_charity` and `cra_charities_get_directors`:
  when open.canada.ca's search finds no list with the tables a tool needs, the pinned 2024
  list is used as before, but `provenance.limits` now says it is a fallback, why, and
  that a newer list may exist.
- `cra_digital_economy_registry_search`: a registry table with no readable row (a layout
  change) raised nothing and answered 0 registrants; it is now an upstream error. Rows
  skipped for a missing cell are counted in `provenance.limits`.
- `nfd_describe_table`: a data dictionary that failed to download or open left
  `dictionary_title`, `source` and `last_updated` null with no word, and the failure was
  cached for hours. The response now says so in `quirks` and `provenance.limits`, and the
  next call tries the dictionary again.
- Health Canada drug, natural health product, device and vigilance tools: a sub-table
  lookup that answered HTTP 404 with an error message (an endpoint the API no longer has)
  was read as "no rows"; only the empty 404 the API sends for no rows is, and the other is
  now an upstream error.
