### Added

- `statcan_daily_get_article` reads one Daily article in full, in English or French: its text
  by section (including the Note to readers), chart titles, the StatCan tables it links to with
  their product ids for the `wds_` tools, and links to the article's PDF, its Tables and
  Related information pages and the previous release. It takes the id (`dq261104a`) or the URL
  that `statcan_daily_get_releases` and `statcan_daily_search_archive` return, and flags
  articles StatCan has marked archived. Checked against articles from 2013 to 2026. Until now
  the Daily tools gave only the feed's one-paragraph summary.
