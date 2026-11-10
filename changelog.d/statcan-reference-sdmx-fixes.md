### Fixed

- `statcan_reference_search_documents`, `statcan_reference_search_analysis` and
  `statcan_reference_search_data` no longer fail with "missing #ndm-results" when a
  search matches nothing. StatCan's catalogue answers a zero-match search with a
  "found no results" page that has no results list; that page is now an empty result,
  and `provenance.limits` explains that every word of the keyword must match and
  suggests fewer or broader words.
- `sdmx_get_data` now says which requested members came back with no series. A key
  such as Ontario and Canada by mortgage interest cost in table 18-10-0004-01 used to
  return the Canada series alone, with no sign that Ontario was dropped;
  `provenance.limits` now names each missing member (or each missing combination when
  several members per dimension are crossed). A key that matches no series at all is
  a NotFound that names the members asked for, flags ids the table does not have,
  says which members the combination is published for (mortgage interest cost: Canada
  only), and points to `sdmx_get_structure` to check the available members.
