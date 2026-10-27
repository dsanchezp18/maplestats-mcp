### Fixed

- `reproduce_code`: for tools that ask the source only for a row count before or after
  their data query (`ab_wildfire_get_fires`, `ab_wildfire_get_fire_perimeters`,
  `eps_list_occurrences` with ArcGIS `returnCountOnly=true`; `electricity_quebec_*` with
  Opendatasoft `limit=0`), the script replayed the count request and returned no rows while
  labelled "exact". Count-only requests are now skipped when choosing the request to replay.
- `reproduce_workbook`: code columns (StatCan coordinates, vector and product ids, DGUIDs,
  postal codes, NAICS, NOC and SGC codes) stay text, as `reproduce_code`'s scripts keep
  them, so coordinates "2.1" and "2.10" no longer collide as the number 2.1. The response's
  notes now say how the rows were cleaned, which columns were converted from text and which
  were kept as codes, and name the fields of the tool's result left out of the rows (a
  total, a truncated flag, a second list); their values go on the Source sheet.
