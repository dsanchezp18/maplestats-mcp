### Changed

- README and home page claims say what the server does: every StatCan series carries a
  citation and every other result names its source and licence; `check_answer` re-reads
  the StatCan and Bank of Canada figures the assistant sends it, when it calls it; quality
  flags are spelled out on StatCan values; the server only reads, the scripts it writes
  run only if the user runs them, and saving a workbook is opt-in. The README's coverage
  table lists `jobbank_`, `cra_charities_` and `telecom_`, and "Using it" names
  `check_answer`.
- Server instructions: `check_answer` takes the StatCan and Bank of Canada figures cited;
  the full-table script is offered and run only if the user agrees; `wds_query_series`
  for averages, sums and rankings over a few series where the server offers it; `lang='fr'`
  for a French question.
- `plan_query` answers a question written in French in French when `lang` is left at its
  default.
- `plan_query`: a department's spending or headcount ("How much did ESDC spend in
  2023-24 and how many employees") is planned as government spending, GC InfoBase first;
  it had no plan before. "Spend" and "employees" count only beside a department, so
  household spending and payroll employment questions are not affected.
- `search_tools`: GC InfoBase now ranks first for federal spending by department and for
  public servants by department, above proactive disclosure, whose tools say they hold
  contracts, grants, travel and hospitality, not total spending or headcount.
  `wds_search_cubes` ranks first for "unemployment rate Toronto CMA" and "GDP by industry
  monthly", and `jobbank_get_wages` (not the Ontario electricity price history) for an
  occupation's average hourly wage; `jobbank_get_wages` points to LFS table 14-10-0417
  and SEPH (14-10-0223) for StatCan's own wage figures.
- The moving-average reading note for a seasonally adjusted series (14-10-0459) no longer
  says to compare with the same months a year earlier; that advice is for unadjusted
  series. The French unadjusted-series note reads "d'ordinaire celle qu'on compare d'une
  période à l'autre".
- Fitness caveats: SEPH's exclusions name military personnel of the defence services;
  the Job Bank caveat says the LFS sample leaves out the three territories, some remote
  regions and First Nations reserves, and calls the median "salaire en vigueur" in French.

### Fixed

- Job Bank covers 86 geographies: Canada, nine provinces and 76 economic regions (Prince
  Edward Island and each territory are one economic region), not "86 economic regions".
- Website: the home page search counts every tool ("Top 5 of 395 tools", as the other
  pages say), and an open tool card on the Tools page no longer runs past the screen at
  360 px.
