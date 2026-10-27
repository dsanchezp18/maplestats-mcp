### Fixed

- `isc_get_registered_population`: a residence's `total` was `men + women` with a missing
  figure read as 0, so a blank sex made the other one the total; it is now null when either
  is missing, and the all-residence `men` and `women` sums are null when any residence lacks
  the figure. These fields, and `isc_get_first_nation_profile`'s `total_reserve_hectares`,
  are now described as computed by MapleStats; the profile adds `reserves_without_hectares`,
  the reserves with no published area that the total leaves out.
- `elections_provincial_get_results`: vote shares, valid votes and Manitoba's turnout that
  MapleStats computes (where the source publishes none) read as published. New
  `vote_share_computed`, `valid_votes_computed` and `turnout_computed` flags say which ones
  are computed, and `elections_provincial_get_seats` describes its totals and shares as
  computed.
