### Added

- `wds_get_full_table_download` (CSV) now also returns Python and R scripts that download
  the zipped table to `data/raw/`, keep the `members` asked for (`{"Geography": ["Canada"]}`,
  dimension and member names checked against the table's metadata) and the periods from
  `start_period` to `end_period` (an end of `2025` keeps all of 2025's months), then print a short summary: the size, each column's
  distinct values and the first and last rows. An assistant runs the script and reads the
  summary instead of pulling a large table's rows into the conversation. The new arguments
  are optional; with `format="sdmx"` they are refused.
- `reproduce_code` takes `summary=True`, which ends the R and Python scripts with the same
  printed summary (no Stata, Julia or Excel version is written then). Reproduction filters
  gain a "one of these values" match, used for the members.
