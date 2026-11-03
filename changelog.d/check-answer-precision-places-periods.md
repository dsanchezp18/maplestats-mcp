### Fixed

- `check_answer` read whole numbers as rounded to their trailing zeros, so 20000
  passed for a published 24000 and 1000 for 1400. A cited value now matches at
  its written precision (170 means 169.5 to 170.5), `value` also takes text
  ("6.50") to keep trailing decimals, and a scale word never widens the match
  beyond 5% of the value ("2 million" no longer passes for 2.4 million).
- `check_answer`: a year cited for a monthly or quarterly series was labelled as
  its first month while the value and flags of its last month were read. The
  year is now compared with its average (said so, with the range of the
  values), a single month's value cited as the year is named as that month, E,
  F and x flags are read for every month, and a newer period is judged at the
  cited granularity.
- `check_answer` scale words follow the language: in French a billion is 10^12
  and a milliard 10^9 ("3,44 billions de dollars" was reported off by a factor
  of 0.001), and a bare "m" (metres) is no longer read as millions ("M$" and
  "$M" are).
- `check_answer` added Canada to the asked places whenever a question said
  "Canadian" or "pays", so a Canada series passed for "Canadian workers in
  Alberta"; Canada now counts only when no province or city is named. Each
  figure is checked against its own `geography` when given, else the places
  asked, instead of the question's first place for every figure.
- `check_answer` told the answer to say a figure is not published (and to go to
  microdata, custom tabulation, RTRA or an RDC) whenever the cited table lacked
  the place, although another table may publish it (Toronto's unemployment rate
  is in 14-10-0459 and 14-10-0460, not 14-10-0287). It now reports that the
  table has no member for the place, with a `wds_search_cubes` query and the
  tables a fitness rule names; the not-published route is kept for cases known
  to be published nowhere (11-10-0090 disability poverty below Canada).
- `check_answer` failed as a whole ("try again") when one vector id was invalid,
  because WDS answers HTTP 500 for the whole series-info batch; the ids are now
  retried one by one and only the bad one gets a `series` problem.
- `check_answer`: a figure from another source than StatCan or the Bank of
  Canada is no longer a problem asking for a source id the answer cannot give;
  it is listed in the new `notes` field as not checked.
- `jobbank_compare_occupations` with `province` and the default region returned
  Canada-wide medians; it now returns that province's.
