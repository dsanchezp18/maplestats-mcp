### Changed

- `search_tools` puts the tools that take an exact identifier first: a tool's own
  name (`boc_get_observations`), a tool-family prefix (`cmhc_dt_`), a StatCan table
  number (`14-10-0287-01`, `14100287`) or a vector (`v41690973`, also how old Bank of
  Canada series are named). A query that was only a table number (`36100434`) used to
  return nothing. The output format is unchanged, and the reviewed discovery benchmark
  scores the same (the boosts only reorder tools below the first accepted one there);
  29 identifier probes go from 0.59 to 0.76 at rank 1.
