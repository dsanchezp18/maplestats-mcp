### Fixed

- `ab_opendata_get_budget_table`: a labelled second table of years with no Actual or
  Forecast line under it ("Calendar Year Assumptions" over 2024, 2025, 2026, after a
  fiscal-year table) was read as a data row, so the rows under it kept the fiscal-year
  column names; and a first line item whose figures rise by one ("Roads" 2020, 2021, 2022)
  right under the header was read as a second header and dropped. A labelled row of years
  is now a header when its label says so (year, fiscal, calendar, assumption, period, and
  their French words) or has a header line under it, and a line item otherwise when the
  header rows above it already name the columns by year.
- `cwfis_get_weather_stations`: `province` accepts the common abbreviations (PEI, NWT, Nfld,
  "Nfld & Labrador", Yukon Territory, and the French IPE, TNO and TNL). Anything that is
  neither a province or territory nor a US state code ("Labrador", a typo) is now refused
  with an error that lists the valid codes, in English and French, instead of being sent as
  a code that matches nothing and returning an empty answer that blamed the fire season.
- `cihi_get_indicator_data`: the newest rows were ranked by year only, so the four quarters
  of one year ("2024 Q1" to "2024 Q4", "T1 2024") tied, and so did the months of a year. The
  quarter, or the month (English and French names), now orders rows within a year. When
  `limit` cuts inside one time frame, the rows kept are that frame's first rows in file
  order, not its last. The year formats "2024–2025", "2024-2025" and "2024–25" rank as
  before.
- `electricity_ontario_get_hourly_demand` and `electricity_ontario_get_supply_by_fuel`: the
  descriptions said the year before is read "in early January". It is read whenever the
  latest `limit` hours (no `year`, `start_date` or `end_date`) exceed the hours the current
  year holds so far, so `limit=2000` in February also reads last year's file (about 8 MB
  for supply by fuel). The behaviour is unchanged and `provenance.limits` already says so;
  the descriptions now match it.
- Python, R and Julia clients: the repeat without `detail` for a server older than 0.6.0
  (and, for `search_tools`, older than 2026-11-09) fired on any error that contained
  "detail" and "unknown" or "unexpected", including a current server's invalid-arguments
  error that lists a parameter called "details". It now fires only on the older server's own
  wording, "detail is not a parameter of this tool" or, in French, "detail n'est pas un
  paramètre de cet outil", still once per call.
