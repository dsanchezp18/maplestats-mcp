### Added

- US Bureau of Economic Analysis comparators (`bea_`, 5 tools), over the BEA
  Data API. `bea_get_nipa` reads national accounts tables (GDP growth and
  levels, personal income, PCE prices), `bea_get_regional` state, county and
  metro income and GDP, `bea_get_international_transactions` US trade in goods
  and services with Canada (or another country), and `bea_list_datasets` and
  `bea_list_parameter_values` find tables, line codes and indicators. Needs the
  new `MAPLE_BEA_API_KEY` setting (a free BEA UserID); without it every tool
  says the server has no key. Built from BEA's API user guide and not yet
  checked against live responses.
