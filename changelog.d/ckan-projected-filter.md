### Fixed

- CKAN DataStore queries can filter by a column that is not in the requested
  output fields. Unknown filter columns are still checked against the full schema.
