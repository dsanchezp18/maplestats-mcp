### Added

- `eurostat_query_dataset` and `oecd_query_dataset`: one read-only SQL query over a
  slice of a Eurostat or OECD dataset (codes per dimension and the periods; up to 20,000
  series and 150,000 observations), the same shape as `wds_query_table`. The slice loads
  as `obs` (series, period, value, unit, scale, frequency, geography, adjustment, status,
  quality, and each dimension's code and label) and runs in the same DuckDB sandbox. The
  query is refused before it runs when it mixes units, scales or seasonal adjustments,
  sums a total with its own parts, or compares a column with a value no row holds. The
  parts come from the OECD's codelists (areas, ISIC, COICOP, sectors, transactions) and,
  where a source publishes none (all of Eurostat), from the codes themselves: totals,
  age bands, NACE/ISIC sections and ranges, NUTS regions, and the EU, euro-area, OECD and
  G7 aggregates. Behind the same `MAPLE_QUERY_SERIES` switch as the StatCan SQL tools.
  Nothing is cached. Checked live on 2026-11-20 against nama_10_gdp, une_rt_m,
  demo_r_pjangroup, DSD_LFS@DF_IALFS_INDIC and DSD_PRICES@DF_PRICES_ALL.

### Fixed

- `wds_query_series` and `wds_query_table` no longer refuse an aggregate with its own
  `FILTER (WHERE ...)`: the check measured the whole group, so `sum(value) FILTER
  (WHERE geo = 'DE')` beside a total read as a total summed with its parts.
