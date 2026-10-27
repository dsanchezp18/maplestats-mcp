### Added

- Fitness-for-use rules: short English and French cautions on when and how a
  number can be used, each resting on an official Statistics Canada, Bank of
  Canada or CMHC page it cites (LFS vs SEPH, LFS sampling variability, the SEPH
  January 2026 level shift, 2021 Census random rounding and boundary changes,
  MBM vs LIM vs LICO and MBM bases, CPI and core-inflation revisions, monthly vs
  quarterly GDP and chained dollars, NAICS and NOC versions, PUMF weights and
  release rules, CMHC Rental Market Survey reliability codes). They match tools
  by name prefix and StatCan tables by product id in any spelling
  (`shared/fitness.py::notes_for`), and are listed with their sources in
  `docs://planner/fitness-rules` (French: `docs://planner/fr/regles-d-usage`).
- `plan_query`: a topic's caveats now end with the fitness-for-use notes for the
  tools and tables its steps name (and for a table number in the question), in
  the plan's language, each note once per plan.
