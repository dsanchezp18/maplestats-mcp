### Changed

- `boc_get_observations` and `boc_get_group_observations` say how to read each FX* exchange rate
  against the Canadian dollar. FX{ccy}CAD is Canadian dollars per unit, so a lower value means a
  stronger dollar; FXCAD{ccy} is the reverse. For up to three series they also say which way
  the dollar moved between the first and last rows. In the Maple Test an answer read FXJPYCAD's
  fall as the dollar weakening.
- `wds_search_cubes`, `wds_get_all_cubes_list` and `wds_get_cube_metadata` say in their caveats
  that `release_time` is a table's latest release or revision, not when a reference period was
  first published, and that `statcan_daily_search_archive` gives a release's date.
- New fitness notes: job vacancies (report the seasonally adjusted 14-10-0432, not the unadjusted
  14-10-0371), and Labour Force Survey counts (14-10-0287 publishes them in thousands; do not apply
  an LFS rate to a 2021 Census count). The income note now names 11-10-0239's median member.
  A fitness rule can be marked `in_plans=False` to reach results but not plans; the LFS one is.
- Maple Test v4: N-13 moves from the test set to dev under the rotation rule, because it prompted
  the exchange-rate note. The test set has 20 questions until the replacements are written.
