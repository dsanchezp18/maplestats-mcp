### Changed

- StatCan breaker keys: the breaker key for `www12.statcan.gc.ca` is now
  `www12.statcan.gc.ca/census`, as `/stats` and `docs://status` show it, because every
  StatCan path group is keyed `host/group`. A whole-host outage now pauses each path group
  of that host separately, each after its own failures, and not the host as one.

### Fixed

- Weekly live check: a script cut short by a paused path group (a refusal that carries no
  request) is now counted under its host (`www150.statcan.gc.ca`), not under the breaker's
  `host/group` key, so the "skipped hosts" alarm sees a whole-host outage as one host again,
  and compares it with the previous run's file as before.
- StatCan Delta files: `/delta/{date}.zip`, the address `statcan_delta_get_file_link` gives
  and asks for, now belongs to the files group of the breaker and of the challenged-path
  list, like `/n1/delta/`; it fell into the host's leftover key.
- `nrcan_energy_use_get_table` and `nrcan_energy_use_list_tables`: a page in the site's own
  layout with no table or table links (which is also what a maintenance notice in that
  layout looks like) is no longer kept for 24 hours (tables) or 7 days (menus). It still
  answers "not found", but the next call reads the page again.
- `cra_charities_search`, `cra_charities_get_charity` and `cra_charities_get_directors`: when
  a later page of the search for the yearly lists fails, the call now answers from the pages
  already read (newest first) and says in `provenance.limits` that the search was cut short,
  instead of failing; that cut-short search is not kept for a day. The portal's newest-first
  sort was checked live on 2026-11-28.
- `elections_results_get_table`: when `party` filters a candidate or elected-candidate
  column, `provenance.limits` now says what the filter cannot tell apart. The cell holds the
  name and the party as one text, so a party with a single candidate in the table (or whose
  candidates all share a last name) is also matched on that name.
- `recalls_search`: "buses", "gases", "heroes" and "viruses" now also find "bus", "gas",
  "hero" and "virus", and "series" and "species" are no longer cut to "sery" and "specy",
  which found "nursery" and "misery".
- `ircc_monthly_query`: a quarter written right after the year ("2024Q1", "2025T2") is read as
  a quarter and no longer falls into the row with no period.
- `statcan_lode_list_databases`: a product page that is neither a LODE page with a ZIP link
  nor one with a release date (a maintenance page, for one of the databases missing from the
  landing page) no longer fails the whole listing. That database is listed without releases,
  `provenance.limits` names it, and the page is still not kept.
- `bc_stats_read_file`: a stored copy of the file that is not a workbook (a web page that
  `ckan_read_resource` stored under the same shared key) is dropped as it is refused, so the
  next call downloads the file again instead of failing for up to six hours.
