### Fixed

- `borealis_odesi_search_variables`: any HTTP 403 from the DDI export read as "no
  variable-level DDI" and was cached. Only Borealis's own "Export Failed" answer means that
  now; another 403 (a proxy or firewall refusing the request) is an error, not cached.
- `cimt_get_trade`, `cimt_get_top_commodities`, `cimt_get_series`, `cimt_search_commodities`:
  when StatCan's commodity or unit code list failed to load, descriptions and units were
  silently missing (top commodities were named by their code). The trade values are still
  returned, and `provenance.limits` now says which names could not be loaded.
- `cbsa_tariff_list_editions`, `cbsa_tariff_lookup`, `cbsa_tariff_search`: a year page
  answering HTTP 404 read as "no editions that year" and was cached for six hours, so
  `latest` could fall back to an older edition without saying so. A year asked for with no
  page is now a NotFound naming the page, never cached; the default two-year listing returns
  the year it could read, with a new `missing_years` and a limits note; and an edition by
  date only steps back past the current year when that year's page is not posted yet.
- `crea_get_hpi_links`: a failed check for the month's zip (no answer, HTTP 403 or 5xx)
  looked like "no zip yet" and was cached for the month. A new `zip_check` (`found`,
  `not_found`, `failed`) and a limits sentence tell the two apart, and a failed check is not
  cached.
