### Changed

- `ircc_list_express_entry_rounds`, `ircc_get_express_entry_round` and
  `ircc_get_latest_express_entry_round`: `invitations_issued`, `crs_cutoff` and every
  `crs_distribution` count (`band_*`, `total`) are now nullable. A blank or missing figure
  in IRCC's feed used to come back as 0, which reads as "no candidates" or "a cutoff of
  0"; it is now null. Every round in the feed had all figures on 2026-10-27, so current
  answers are unchanged.
- `eccc_datamart_npri_facilities`: a record's `year` is now nullable; a row with a blank
  reporting year came back as year 0.
- `hc_device_search_devices` and `hc_device_get_licence`: a device's `licence_number` is
  now nullable; a device with no published licence number came back as licence 0.
