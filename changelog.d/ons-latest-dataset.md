### Fixed

- `ons_get_series` without `dataset` now reads the dataset ONS released most
  recently, not the first search hit. ONS search began ranking PGDP (last
  released 2018) first for IHYQ, so a request for 2025 quarters found nothing.
  The other datasets are still listed in `other_datasets`.
- The modules smoke test reads AER's and CWFIS's `note` with `.get()`: brief
  results leave out a null field.
