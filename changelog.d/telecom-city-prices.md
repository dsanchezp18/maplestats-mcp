### Added

- `telecom_get_city_plan_prices`: CRTC mobile and Internet plan prices by census
  metropolitan area (Edmonton, Toronto, Montréal and the other 21 CMAs), year by year
  from 2016, from the "Prix-Prices" sheet of the CRTC's year-end price workbook. The
  averages are computed by MapleStats (the mean of every reported price, and the mean
  of each provider's lowest price, the CRTC's own method), with the number of prices
  and providers behind each, and optionally the provider and brand rows. `city` takes
  one CMA or several, accents and case ignored ('Montreal', 'Ottawa'). From 2024 the
  CRTC surveys one CMA per province or territory; for a CMA with no rows in a year the
  notes say so and point to the CRTC's provincial urban average.
- `telecom_get_plan_prices`: `province` also takes several provinces or territories at
  once, as a list or a comma-separated string (`['AB', 'ON']`, `'AB, ON, QC'`). A
  single code still works as before.
