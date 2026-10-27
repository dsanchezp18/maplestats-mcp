### Fixed

- Results cut without saying so now say so:
  - `borealis_search_ivt`: new `total_matched` and `truncated`, and `provenance.limits`
    says how many IVT files were left out and that files come from the top 10 datasets.
  - `nl_stats_read_file`: a sheet longer than 20,000 rows was read to that cap with
    `total_rows` counting only the rows read; `truncated` is now true and the limits say
    so, and each entry of `sheets` has a `truncated` flag.
  - `pbo_get_publication`: charts (SVG), images and print-only blocks were dropped
    silently; a new `left_out` counts them by kind and the limits name them. An HTML slice
    without a table, which was dropped, is now part of `text`; a cut text is named in the
    limits too.
  - `phac_infobase_describe_dataset`: `geo_values` stops at 40 places; a new
    `geo_value_count` gives how many there are, and the limits say when it is cut.
  - `statcan_daily_get_releases`: new `total_in_feed` and `truncated`, with a limits note
    when `limit` cut the feed.
  - `sdmx_space_search`: facets stop at 6, each with its 8 most frequent values; a new
    `value_count` per facet and a limits note say when either cap cut them.
- `worldbank_*`: the WDI indicator list was read as one page of 2,000 with no check; the
  next pages are now read when there are more, and a list short of its stated total is an
  error rather than a search that silently misses indicators.
