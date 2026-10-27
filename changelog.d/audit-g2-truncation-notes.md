### Fixed

- Lists cut for size now say so. `eccc_search_collections` gives the number of all
  matches in `coverage` and a `provenance.limits` sentence when `limit` cut them;
  `gazette_list_issues` has a new `total_in_feed` and says when `limit` cut the feed;
  `nrcan_geo_locate` has a new `total_found` and says when `limit` cut the results or the
  Geolocator sent results without coordinates; `pmra_search_products` says when
  `by_product_type` lists only the 15 most frequent types, and `pmra_get_residue_limits`
  when `chemicals` lists only the first 50; `hc_drug_search_ingredients` has a new
  `strength_count` per ingredient and says when `strengths` was cut to 8;
  `recalls_summarize` says when a cut on years leaves out the undated ("unknown") group.
- `hc_device_search_devices`: a name search returning more than 25 devices skips the
  model-number lookups, so every `identifiers` list was empty with nothing saying why. A
  new `identifiers_included` field and a `provenance.limits` sentence now say so.
- `tc_recalls_search`: when a search matches more than the 100,000 rows read, a new
  `all_rows_read` field is false and `note` says that `total_matched` is a lower bound and
  that the newest recalls may be missing (it was said only in `provenance.limits`).
- `eccc_coverages_get_data`: a request (one scenario, percentile or season) that returned
  no value is named in `notes`, rather than its rows being silently absent.
