### Added

- US Federal Reserve Board releases as comparators for Canada (`fed_`, 5 tools),
  read from each release's complete XML file, no key: H.15 interest rates,
  policy rates, H.10/G.5 exchange rates, G.17 industrial production and
  capacity utilization, H.6 money stock, G.19 consumer credit, household debt
  service ratios, H.8, H.4.1, commercial paper, G.20, charge-off and
  delinquency rates, SLOOS and SCOOS. `fed_get_indicator` gives fifteen
  headline series (the federal funds rate, 2- and 10-year Treasury yields, the
  Canadian dollar per US dollar, industrial production and others), each with
  the Bank of Canada or Statistics Canada series to set beside it;
  `fed_search_series`, `fed_describe_release` and `fed_get_series` reach any
  other series. Rows are tidy (date, value, unit, frequency, series id). The
  module does not use the Data Download Program, which the Board is retiring.
  The planner now answers US interest rate, Treasury yield, dollar, industrial
  production and money questions with a Federal Reserve plan.
