### Fixed

- `bc_env_list_wells`: when the groundwater-trends table that gives each well's region
  failed, every well came back without a region and that list was cached for 6 hours, so a
  `region=` filter returned 0 wells. The list now says the regions are missing, is not
  cached, and a `region=` filter raises an error instead.
- `aer_get_well_licence_archive_link` and `aer_get_production_volumes_link`: any answer
  other than 200 (a 403, a 429 or a 5xx) was reported as "no file at this address" and
  cached. Only 404 and 410 mean the file is absent now; anything else raises an error and
  is not cached.
- `arcgis_hub_get_dataset`: when the portal's layer list or download API failed,
  `download_urls` was an empty list with nothing to tell it from an item with no downloads.
  `provenance.limits` now says the lookup failed (and, for Red Deer, that the portal's
  download API fails for every item), and a failed lookup is no longer cached for an hour.
- `ourcommons_get_party_standings` and `ourcommons_get_ministry`: a row without a seat
  count or an order of precedence read as 0; it is now an error naming the missing field.
- `electricity_ontario_*`: an hour or interval number missing from an IESO file became
  hour 0; it is now an error naming the missing field.
