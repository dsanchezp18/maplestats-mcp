### Added

- Bank of Canada surveys and projections, found without a Valet group name:
  `boc_get_business_outlook` (Business Outlook Survey: the BOS, activity and price
  indicators, balances of opinion and firms' inflation expectations),
  `boc_get_consumer_expectations` (Canadian Survey of Consumer Expectations: inflation
  expectations at 1, 2 and 5 years, wages, job probabilities, spending, interest
  rates), `boc_get_mpr_projection` (the Monetary Policy Report's quarterly projection
  for Canada, contributions to GDP growth and global growth, latest or named Report)
  and `boc_get_staff_projections` (staff economic projections by vintage, with
  forecast quarters marked). Each finds the newest quarter, Report or vintage from
  Valet's live inventory and returns one row per value with its unit and period, plus
  the publication's month, page and chart groups. `plan_query` routes questions about
  expectations and forecasts ("what do businesses expect for inflation", "Bank of
  Canada GDP forecast") to them.
- `boc_get_group` returns the group's page `link`.
