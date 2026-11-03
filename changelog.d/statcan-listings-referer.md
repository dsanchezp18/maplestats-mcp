### Fixed

- `statcan_reference_search_documents`, `statcan_reference_search_analysis`,
  `statcan_reference_search_data`, `statcan_pumf_search` and
  `statcan_surveys_search_surveys` work again. Since about 2026-10-29 StatCan answers its
  404 page (and a redirect loop for the survey directory) to any request without a
  `Referer` header, while the same pages load for a browser following StatCan's own menu.
  These tools now send StatCan's home page as the referrer. The survey search keeps IMDB's
  alphabetical index as a fallback.
