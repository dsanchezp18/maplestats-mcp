### Fixed

- `dfo_iwls_get_water_levels`: with only `end` given, the window is now the 24 hours up to
  it; a past `end` used to be refused ("end must be after start") because `start` fell back
  to now. With neither bound, the observed series "wlo" now covers the last 24 hours (up to
  the last 10-minute mark, so repeated calls share one cached answer), not now to +24 hours,
  a window with no points and no note; every other series ("wlp", "wlp-hilo", forecasts)
  keeps now to +24 hours.
- `dfo_iwls_search_stations`: the name match ignores accents ("pointe-au-pere" finds
  "Pointe-au-Père"), and a code without its leading zeros ("7120") finds the station
  ("07120"), as `dfo_iwls_get_station` already did.
- `cra_digital_economy_registry_search`: a business number typed with spaces or dashes
  ("751950577 RT9999", "751950577-RT-9999") now matches the registry's compact form instead
  of reporting no match, and names match without regard to accents ("societe" finds
  "Société"). The registry page is also checked before it is cached: an error or
  maintenance page answered with HTTP 200 is an upstream error and is no longer replayed
  for six hours.
- `nrcan_energy_use_list_products`, `nrcan_energy_use_list_tables` and
  `nrcan_energy_use_get_table`: a maintenance or error page answered with HTTP 200 is no
  longer cached for 24 hours (tables) or 7 days (menus). A page without the site's own
  markers is now reported as the site being unavailable, not as a missing table or a survey
  with no tables, and the next call asks the site again. A normal page of the site with no
  table or no table links is still "not found", as before.
  `nrcan_energy_use_list_products` leaves the comprehensive menus out with its usual note
  while the site is down.
- `cra_tax_stats_get_t1_table`, `cra_tax_stats_get_t1_series`, `cra_tax_stats_get_fsa_table`
  and `cra_tax_stats_get_fsa_series`: a web page answered in place of a CSV file is an
  upstream error, in French too with `lang="fr"`, and is no longer kept in the file cache for
  24 hours. The series tools no longer take it for a missing year (it showed as "no matching
  row in" that year).
- `bc_stats_read_file`: a web page, or any body that is not an Excel archive, answered in
  place of the workbook is an upstream error, not "not found", and is no longer cached for
  six hours under the file's address. A bad page that another reader of the same file
  (`ckan_read_resource`) stored is refused as well.
- `dfo_landings_get_landings`: `include_totals=False` now also leaves out the region sums
  (the Atlantic total and Canada for sea fisheries, the Canada columns for freshwater), so
  adding up the rows returned no longer counts the provinces three times. `is_total` is
  true for those rows, and the result says how many total rows were left out. To read the
  Canada rows themselves, leave `include_totals` on.
- `cra_charities_*`: the search for the yearly "List of charities" packages asks for the
  newest first and reads up to five pages of results, so the newest list is found even when
  it would be ranked past the first 100; and two lists of the same year no longer raise a
  `TypeError` when the fallback note is built.
- `nrcan_geo_search_names`: when the service returns as many places as `limit` asked for
  (it sends no total), the result now says more may exist and how to narrow the search or
  raise `limit` (only to narrow it when `limit` is already the largest allowed).
