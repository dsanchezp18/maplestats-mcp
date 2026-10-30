### Fixed

- `statcan_reference_search_documents`, `statcan_reference_search_analysis`,
  `statcan_reference_search_data`, `statcan_pumf_search` and
  `statcan_surveys_search_surveys`: since 2026-10-29 StatCan's listing pages
  (`/n1/{lang}/type/...`) answer 404 while its own menus still link them. These
  tools now say the StatCan page is unavailable and point to a tool that still
  works (`wds_search_cubes`, or `statcan_surveys_get_survey_metadata` for a known
  id) instead of a bare "returned HTTP 404".
- `statcan_surveys_get_survey_metadata`: an unknown survey id raises NotFound
  again, at once. StatCan's 404 page, where IMDB sends it, answers 503 since
  2026-10-29 instead of 500, so the call retried for about 100 seconds and
  ended in a generic upstream error.
- `statcan_delta_list_files` with `include_sizes`: checks file sizes 4 at a
  time instead of all 46 at once, which timed out in bulk and paused every
  other www150.statcan.gc.ca tool for a minute.
