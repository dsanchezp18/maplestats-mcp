### Fixed

- `isq_get_table`: a zero-padded code such as the "Code" column of table 4948 ("01") now comes
  back as text, not as the number 1. A label or code column holding any zero-padded value
  stays text in every row, so "09" and "10" no longer arrive as a string and a number; a
  value column always parses numbers.
  `isq_get_table` also refuses an empty answer or a web page from ISQ's data engine with an
  upstream error, instead of returning a table of zero rows or one row per line of the page,
  and none of these answers is kept for six hours.
- `isq_search_tables`: a plural query word now finds a singular table name and the reverse
  ("revenus disponibles" finds "revenu disponible ...", "niveau de vie" finds "niveaux de
  vie ..."), including the French words ending in "-us", "-is" and "-eau" that the shared
  search does not fold. A final "x" counts as a plural only after "eu", "au" or "ou", so
  "inde" no longer finds "index".
- `statcan_geo_query_layer` and `statcan_geo_query_spatial_layer`: a query that filled its page
  now reports `exceeded_transfer_limit` as true and says to page with `result_offset`. The
  server sends that flag under a top-level `properties` object in GeoJSON answers, where it was
  not read, so every result looked like the last page. With `lang="fr"`, the error for an
  unknown service or layer is now in French; it came back in English.
- `nl_stats_read_file`, `on_finance_get_population_projection` and
  `on_finance_get_projection_components`: a workbook whose sheet declares its size as just A1
  is read in full, not as a single row, and one with an inflated declared size no longer runs
  into the parse time limit.
- `nwt_stats_list_files` and `nwt_stats_search_files`: a maintenance or error page served with
  HTTP 200 in place of a topic page is now an upstream error, no longer an empty topic
  ("0 files") kept for six hours; `nwt_stats_search_files` names such a topic in its note of
  pages that did not answer.
- `mb_stats_read_file`, `mb_stats_list_files`, `mb_stats_list_indicators`, `sk_stats_read_file`
  and `nwt_stats_read_file`: a web page served in place of a file or a CSV is no longer kept in
  the cache before it is rejected, so the tools work again as soon as the source recovers
  instead of failing until the cache expires. For the Manitoba tools that error is now an
  upstream error, no longer "not found", which wrongly suggested the file did not exist.
