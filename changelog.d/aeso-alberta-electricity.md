### Added

- Alberta electricity from the AESO's public Energy Trading System reports
  (ets.aeso.ca, keyless; the keyed api.aeso.ca is not used), four tools:
  `electricity_alberta_get_pool_price` (hourly pool price, 30-day rolling
  average and Alberta Internal Load since 1999),
  `electricity_alberta_get_daily_pool_price` (daily, on-peak and off-peak
  averages, up to a year per call), `electricity_alberta_get_monthly_summary`
  (the Pool Monthly Summary since 1999) and
  `electricity_alberta_get_supply_demand` (current load, generation by fuel,
  interchange and assets). AESO's terms allow non-commercial use only: every
  result carries them in `provenance.licence`, `commercial_use: not_allowed`
  and a `commercial_use_notice`.
