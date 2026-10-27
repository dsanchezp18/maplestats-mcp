### Fixed

- `represent_search_representatives` with `level="municipal"`: the scan stopped after 8
  pages of 1,000 and reported `has_more=false` with a partial total. It now says the scan
  stopped and sets `has_more`. A representative set that grows past one page of 1,000 is
  read page by page instead of cut at 1,000. `represent_lookup_postcode` and
  `represent_lookup_point` list boundary sets past the 25 whose details are loaded (marked
  `detail_loaded=false`) instead of leaving them out, and a note says how many lack details.
- `ab_wildfire_get_fire_restrictions`: each layer was read with one page of 2,000 polygons
  and a fuller layer was cut silently; further pages are now read.
- `cwfis_get_weather_stations` by point: when the search box holds more stations than one
  request returns, `provenance.limits` says nearer stations may be missing.
- `bc_env_list_wells` and `bc_env_list_snow_stations`: a BC Geographic Warehouse layer
  that outgrows the 5,000-feature request is now an error rather than a silent cut.
- `transit_get_stop_departures`: a station with more than 50 child stops now says
  departures cover the first 50.
- `bc_lobbyists_get_registration`: a filer-client pair matching more than 20 registrations
  now says how many were left out.
- `ckan_list_organizations` and `ckan_list_groups` (BC portal): a facet roster that fills
  its 500-entry limit now says more may exist.
