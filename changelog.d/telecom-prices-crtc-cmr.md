### Added

- CRTC Communications Market Reports, tools prefixed `telecom_` (4 tools):
  `telecom_get_plan_prices` gives the CRTC's year-end average advertised monthly
  prices of mobile plans by data allowance (talk-only, 1 GB to 200 GB; 3G, LTE, 5G or
  the lowest price) and of home Internet plans by speed, for Canada, each province and
  territory, urban and rural areas, 2016 to 2025; `telecom_list_market_tables` and
  `telecom_get_market_table` read the annual retail mobile and fixed Internet sector
  tables (revenue per GB, ARPU, data usage, subscribers, market shares of Bell, Rogers,
  TELUS and other providers, churn, plan size distribution) as tidy series by year, in
  English or French, flag the years that count mobile phone services only (2020 on) and
  leave out the derived growth columns; `telecom_get_quarterly_trends` gives quarterly
  revenues, subscribers, lines, minutes and data traffic for mobile, Internet, wireline
  and TV distribution from 2014 Q1, sorted by quarter. Open Government Licence - Canada.
- `plan_query`: a telecom topic (mobile and Internet plan prices, subscribers and
  competition) in English and French, which also points to StatCan's cellular services
  CPI (vector v1212387935) and notes that ISED's price comparison studies and the
  CRTC's low-cost plan reports are not read by any tool.
