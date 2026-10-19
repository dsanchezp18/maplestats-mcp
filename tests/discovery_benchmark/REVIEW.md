# Review checklist for the discovery benchmark fixtures

All 129 questions in `queries.json` are `reviewed: false`. The author of the fixtures
(an AI session) read the tool catalogue first and then wrote the expected tools, so it
cannot be the independent reviewer the discovery plan requires. This list is where the
author was least sure. Set `reviewed: true` on a question once you have checked its
expectation; the test accepts either value.

How to check one: read the question, decide which tool you would call first and which
others you would accept, and compare with `search_expected`, `search_alternatives`,
`plan_expected` and `plan_topics`. Disagreement is a finding about the fixture, not about
the system. The baseline numbers move when you change an expectation, so rerun
`uv run python -m tests.discovery_benchmark` and note the change in `baseline.md`.

## 1. Rules that touch many questions

- [ ] **Any-of for `multi_source` search.** `search_expected` lists two tools and one is
  enough (all 20 questions). Should `search_tools` be expected to surface every source of a
  cross-source question, or is that `plan_query`'s job? (`plan_expected` is also scored as
  coverage of all listed tools.)
- [ ] **What counts as an acceptable alternative.** `wds_search_cubes` is listed as an
  alternative to a dedicated tool in many places (for example `statcan_indicators_get_indicators`
  for unemployment). Is a table search an acceptable first answer, or should it be a miss?
- [ ] **Single-tool lookups scored against `plan_query`.** 120 of the 129 questions carry a
  `plan_expected`, including plain "find the tool" questions (`boc-en-03`, `cmhc-en-04`,
  `cmhc-fr-04`, `statcan-en-10`, `statcan-fr-08`). The planner is described as the first call
  for substantive questions; should these be search-only?

## 2. Expectations the author doubts

Ambiguous questions (`ambiguity-*`):

- [ ] `ambiguity-en-03`, `-04`, `ambiguity-fr-01` (poverty rate, child poverty). No tool covers
  poverty directly; `wds_search_cubes` is expected and the SDG tools are alternatives. Is there
  a better route? The MBM vs LIM split cannot be scored at tool level.
- [ ] `ambiguity-en-05` (population of Calgary). Primary is the 2021 Census profile; annual
  estimates through `wds_search_cubes` are the alternative. Which should come first?
- [ ] `ambiguity-en-06` vs `ambiguity-fr-02` (median household income). Province: table search
  first, Census as alternative. City: Census first, table search as alternative. Intentional
  (the surveys do not reach city level), but check it.
- [ ] `ambiguity-en-07`, `ambiguity-fr-04` (house prices). `crea_get_hpi_links` is primary, yet
  it returns links and terms only, no values. The StatCan price index (`wds_search_cubes`) and
  CMHC are alternatives.
- [ ] `ambiguity-en-08` (core inflation). `boc_search_series` is primary; CPI-trim, CPI-median
  and CPI-common are documented in `modules/boc/resources.py`. StatCan's CPI tools are alternatives.
- [ ] `ambiguity-en-01`, `ambiguity-fr-03` (how many jobs), `ambiguity-en-02` (weekly earnings).
  `wds_search_cubes` primary for the LFS/SEPH choice.
- [ ] `ambiguity-en-10`, `ambiguity-fr-07` (immigration). `ircc_monthly_query` vs
  `ircc_monthly_list_tables` as the first call; Express Entry and the Census as alternatives.
- [ ] `ambiguity-en-12`, `ambiguity-fr-08` (oil production). AER monthly volumes, StatCan tables
  and CER are all accepted; the AER tool returns a link to a file, not values.
- [ ] `flag_terms` on every ambiguous question: any one found in the plan's caveats, purposes
  or guidance counts. Are these the words a good plan would use? French terms are written
  without accents (the runner folds both sides).

Single-source questions:

- [ ] `statcan-en-07`, `statcan-fr-06` (next release date): `statcan_daily_get_release_calendar`
  expected from the plan too. May be too demanding of the planner.
- [ ] `statcan-en-09` (household-spending microdata): `statcan_pumf_search` primary,
  `statcan_surveys_search_surveys` alternative. `statcan-fr-10` (survey methods):
  `statcan_surveys_get_survey_metadata` needs a survey id first, so `search_surveys` may be the
  better first call.
- [ ] `statcan-en-11` (articles on the gender wage gap): `statcan_reference_search_analysis`.
- [ ] `statcan-en-13`, `statcan-fr-07` (exports to the United States, crude oil): `cimt_get_trade`
  primary, `cimt_get_series` and WDS as alternatives.
- [ ] `boc-en-04` (list the series of a group): expected `boc_get_group` (lists members), with
  `boc_get_group_observations` as an alternative. The author first wrote them the other way round
  and swapped them after the first run, on rereading the fixtures; no score changed.
- [ ] `ckan_federal-en-02` (licence of a dataset): `ckan_get_dataset`, alternative
  `ckan_list_licenses`. `ckan_federal-fr-01` (air quality datasets): `ckan_search_datasets`, with the
  ECCC tools as plan alternatives.
- [ ] `municipal-en-08` (Edmonton water hardness) is close to the wording of the tool's own
  docstring, so it is an easy question.

Multi-source questions:

- [ ] `multi_source-en-10` (hospital wait times and statistics for Quebec): `isq_search_tables` is
  expected because the planner lists it for Quebec. CIHI alone may be enough.
- [ ] `multi_source-fr-07` (federal spending and deficit): the plan expectation names the
  `list_*` tools the planner shows, the search expectation names the `get_*` tools that return
  numbers. Align them?
- [ ] `multi_source-en-02`, `-en-05`, `-en-09`, `-fr-02`, `-fr-05`: the pair of tools chosen is one
  reasonable pair among several.

## 3. Places and portals (circular with the planner)

The portal keys in `plan_portals` come from the planner's own province and city maps and the
portal constants, so the portal metric partly checks the planner against itself. Nothing was
checked live.

- [ ] Nova Scotia and New Brunswick on Socrata (`ckan_provincial-en-03`, `-en-04`); Manitoba
  and Prince Edward Island on ArcGIS Hub (`-en-06`, `-fr-05`); Ontario, British Columbia, Québec
  and Yukon on CKAN (`-en-01`, `-en-02`, `-fr-01`, `-fr-02`, `-fr-04`). Does each portal hold the
  topic asked about?
- [ ] Municipal portals: Toronto and Montréal on CKAN, Ottawa on ArcGIS, Gatineau through the
  Québec portal (`municipal-en-05`, `-en-06`, `-fr-01`, `-fr-06`), Calgary/Edmonton/Winnipeg on Socrata.
- [ ] `municipal-en-09`, `municipal-fr-07` (Ottawa and STM timetables): whether those agencies
  are in the GTFS feeds was not checked; the expectation is tool-level only.

## 4. Wording and coverage

- [ ] **French wording.** The French questions were written by the same author and have not been
  read by a francophone. Look for unnatural phrasing (`municipal-fr-02` "Permis de construire de la
  Ville de Calgary", `ckan_provincial-fr-01` "garderies subventionnées") and for questions a Québec
  user would phrase differently.
- [ ] **Overlap with pinned tests.** No question is identical to one in `test_english_discovery.py`,
  `test_french_discovery.py` or `test_planner_questions.py`; nine are close paraphrases (for example
  `statcan-en-01`, `cmhc-en-01`, `municipal-en-01`, `municipal-en-02`).
- [ ] **Missing kinds of question.** None of these is in the set: out-of-scope or nonsense
  questions (which should abstain), misspellings, one-word queries, questions naming a table id in
  prose, and questions in the other direction (a tool description as the query). Add some before an
  embedding index is tested, because an embedding index never returns "nothing".
- [ ] **Sample size.** Categories hold 12 to 25 questions, so one question moves a category by 4 to
  8 points. Treat differences under about 10 points as noise.

## 5. Ids used in the live pass (`live_expected`)

- [ ] `statcan-en-01`, `statcan-fr-01`: 14100287 (Labour Force Survey table 14-10-0287-01, from
  `scripts/smoke_test_bc_stats.py` and `tests/test_planner_questions.py`).
- [ ] `statcan-en-13`: 12100011 (merchandise trade table 12-10-0011-01, from
  `scripts/smoke_test_statcan_cimt.py`). Is this the right table for "total exports to the United
  States by month"?
