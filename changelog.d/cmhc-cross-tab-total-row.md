### Fixed

- `cmhc_get_table_data`: the total row of a cross-tab table (one row per
  province or centre) came back with an empty `period`, because CMHC's CSV
  export leaves that row's label cell blank. It is now labelled with the
  requested geography's name ("Canada", or the province for a centre
  breakdown), like every other row is with its own.
