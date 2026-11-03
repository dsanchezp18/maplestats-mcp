### Fixed

- `check_answer`: a figure written as a percent or a change ("percent", "%", "pourcentage",
  "12-month change", "variation", or no unit in a question about inflation or growth) cited
  against an index or level series (the CPI, 2002=100) is compared with the series' 12-month
  and one-period percent changes, not with its level. Until now a correct 3.1% Quebec
  inflation rate for 2026-09 was reported wrong with the fix "Use 167.7", the index level. A
  wrong percent now gets a problem quoting the computed changes, and a percent whose earlier
  period is not published gets a note instead of a problem.
- `check_answer`: places are matched on whole names. "Victoria" no longer matches
  "Victoriaville, Quebec", "London" no longer matches "Londonderry", and the province of
  Quebec no longer matches the Québec CMA (nor Quebec City the province). A question naming a
  city with its province ("Victoria, BC") asks for the city, so a British Columbia series no
  longer passes for it, and the suggested member is the one with the exact name.
