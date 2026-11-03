### Fixed

- Maple Test version 2 re-graded: every one of the 1,923 answers read under one written
  rule per question, with per-answer overrides (`arm/qid#repeat`), false claims and
  referrals counted apart. The key accepts each country's own series on X-12, grades
  A-04 on the Census household median, no longer requires unasked values on C-03, C-11,
  C-12 and X-24, and needs the figure on flag questions that ask for one; the grader no
  longer joins separate numbers ("July 1, 2026, 399,133"). The benchmarks page and
  `tests/maple_test/README.md` lead with per-half results, show each server's declared
  scope, say the other-sources half was chosen from MapleStats' coverage, label the
  after-fix runs in-sample, and list setup issues and versions.
