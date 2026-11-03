### Added

- `wds_get_leaf_members`: the lowest-level members of one dimension of a StatCan
  table (members that are no other member's parent), so a sum or ranking across
  provinces, industries or product groups leaves out totals and subtotals. It
  returns each leaf with its parent, the number of parents left out, the ids as a
  list and comma string, an SDMX `+` key fragment and full key for
  `sdmx_get_data`, and example coordinates for `wds_get_data_from_cube_coord`.
  `dimension` takes the position or the name ("Geography", "Géographie").
  `under_member_id` keeps one branch (a NAICS sector, the CPI's "Food");
  `member_query` filters leaf names. Leaves that may still double-count are set
  aside in `flagged_leaves`: names that read as totals ("Canada" alone, "Total
  private dwellings"), StatCan's T-coded NAICS aggregates ("Goods-producing
  industries", "Energy sector") and leaves outside the main hierarchy (the CPI's
  "All-items excluding food"). Notes say when the leaves mix geographic levels
  (the CPI's leaves are cities, not provinces), mix units, or come from a
  dimension with no parent links (age groups).
