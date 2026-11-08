### Added

- `aer_st98_list_tables` and `aer_st98_get_table`: AER's ST98 Alberta Energy
  Outlook, from the executive-summary data workbook of each edition (2022 to
  2026; a new edition linked on the ST98 page is picked up without a release).
  Reserves and resources, WTI, WCS and Henry Hub prices, capital expenditure,
  primary energy production, demand and removals, crude oil and bitumen supply,
  bitumen upgrading and drilling, as tidy rows (series, year or month or item,
  value, unit, edition) with AER's ten-year forecast flagged (`forecast` is true
  from the edition year on) and estimated years marked from AER's own notes.
  Checked against the reports: the 2026 workbook gives 16 007 PJ of primary
  energy production in 2025 and 18 503 PJ in 2035, the 2025 workbook 16 969 PJ
  (base case) and 16 723 PJ (tariff case) in 2034. AER's copyright terms apply
  (non-commercial reproduction with attribution), as for ST1 and ST3.

### Fixed

- The AER licence text now links AER's current copyright page
  (aer.ca/copyright-and-disclaimer; the old address answers a redirect).
