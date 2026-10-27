### Changed

- Fields MapleStats computes are now described as computed, with a sentence in
  `provenance.limits` where the computation covers less than the whole result:
  `electricity_ontario_get_realtime_demand` (`average_ontario_demand_mw`, and over how many
  intervals), `electricity_ontario_get_prices` (average, minimum and maximum, unweighted),
  `electricity_ontario_get_adequacy_outlook` (minimum excess and peak forecast),
  `electricity_ontario_get_intertie_flows` (mean flows), `electricity_quebec_get_demand`
  (peak and average over the returned rows only), `electricity_quebec_get_generation`
  (shares are over the returned rows, not every matched row as the schema said),
  `epcor_get_daily_water_quality` (`date` is inferred from a year-less label),
  `senate_get_vote` (yeas, nays and abstentions counted from the ballots, and how many
  malformed rows were skipped) and `ourcommons_get_party_standings` (totals summed by
  province).
