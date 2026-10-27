# Review of the discovery benchmark fixtures

## Who reviewed, and what that is worth

The 129 questions in `queries.json` and their expected tools were written on 2026-10-19 by an
AI session that had read the tool catalogue first, so it could not review its own answer key.
On 2026-10-27, at the owner's request, **a second, independent AI session** (a different
session from the author) reviewed all 129 and set `reviewed: true` on each. **No person has
reviewed them.** The French questions were reviewed for their expected tools only: the owner,
who is not francophone, decided to assume the French wording is fine, so it has not been read
by a francophone.

Limits of this review: the reviewer is the same kind of model as the author and read the same
docstrings; it read the old expectations while reviewing, so the review was not blind; and it
decided every change before running the benchmark on the new key. Where two tools looked
plausible it called them through the server in-process against the live sources and kept the
one that returned what the question asks for ("checked live" in a question's notes).

How to check a question, for the next reviewer: read the question, decide which tool you would
call first and which others you would accept, and compare with `search_expected`,
`search_alternatives`, `plan_expected` and `plan_topics`. Disagreement is a finding about the
fixture, not about the system. Rerun `uv run python -m tests.discovery_benchmark` after a
change and record it in `baseline.md`.

## What changed

83 of 129 questions changed (47 English, 36 French); the other 46 were confirmed as written.
Each changed question carries a "Review 2026-10-27:" sentence in its `notes`.

| | search_tools | plan_query |
|---|---:|---:|
| questions scored | 129 (unchanged) | 105 (was 120; 15 made search-only) |
| questions whose accepted tools changed | 61 | 41 (of the 105) |
| tools added as accepted answers | 76 | 58 |
| tools no longer accepted | 20 | 10 |
| questions whose expected list changed | 21 | 8 |
| portals dropped from `plan_portals` | - | 2 |
| ambiguous questions whose `flag_terms` changed | - | 4 |

Most changes widen the key: tools that return the asked-for data by another route were missing
(the indicators feed, the Daily archive, LODE, ODESI, Alberta's dashboard, `wds_get_series_as_of`).
The removals are tools that cannot answer: a label for a rate, a past-release list for a future
date, a tool that needs the answer as its input, a source with no such data.

Corrections where the old key named a tool that cannot return the answer:

- `statcan-en-13` (total exports to the US by month): `cimt_get_trade` with no HS code returns
  commodity rows, 12,018 for one quarter and truncated, not monthly totals; the total is table
  12-10-0011 (`wds_search_cubes`) or `cimt_get_top_partners` for one month. Both checked live.
- `statcan-en-10` (NAICS code for software publishers): `rdaas_get_classification_indexes` is the
  tool that returns the code (513211); `rdaas_get_classification_categories_detailed` returns
  nothing for NAICS 2022. Checked live.
- `boc-en-01`, `-en-02`, `-en-03`, `boc-fr-01`, `-fr-02`, `-fr-05`: `boc_get_series` returns a
  series' label, not its observations, so it is no longer accepted for a rate.
- `statcan-en-07`, `statcan-fr-06` (next release): `statcan_daily_get_releases` covers past
  releases only; `statcan_daily_search_archive` also holds scheduled ones (LFS on 2026-11-06,
  checked live).
- `ambiguity-en-08` (core inflation): the indicators feed has no core measure (checked live).
- `ambiguity-fr-08` (oil production in Canada): AER covers Alberta only. A judgment call:
  Alberta is most of Canada's output, but the question is national.
- `multi_source-fr-07` (federal spending and deficit since 2015): aligned on
  `finance_frt_get_table`, the tool that returns the annual numbers; the `list_*` steps the plan
  expectation named are alternatives.
- `multi_source-en-10` (hospital wait times, Quebec): ISQ has no wait-time table (checked live),
  so it moved to the alternatives and CIHI alone is expected.
- `multi_source-en-03`, `multi_source-fr-02` ("since 2024", "depuis 2019"): the indicators feed
  gives the latest value only, so table search (and ISQ) became expected and the feed an
  alternative.
- Others: `wds_get_data_from_cube_coord` for a vector (`statcan-en-03`), `wds_get_cube_metadata`
  to find a vector's table (`statcan-en-15`), `boc_get_group` to search for a group
  (`boc-fr-04`), `ckan_get_organization_or_group` to list organizations (`ckan_federal-en-03`,
  `-fr-02`), `yukon_stats_list_tables` for roads (`ckan_provincial-fr-04`, no such table),
  `statcan_pumf_get_codebook` for the files (`statcan-fr-05`), `statcan_surveys_search_surveys`
  for microdata (`statcan-en-09`), `wds_search_cubes` for articles (`statcan-en-11`, plan),
  `eccc_query_items` to find datasets (`ckan_federal-fr-01`, plan), `statcan_delta_list_files`
  for tables (`statcan-en-06`, `-fr-09`, plan).

## 1. Rules that touch many questions

- [x] **Any-of for `multi_source` search.** Kept. `search_tools` is asked for one tool and a hit
  on one source of a cross-source question is a fair first answer; covering every source is
  `plan_query`'s job and is scored by `coverage`. The schema cannot express "one tool per
  source, any of these": `plan_expected` names one tool per source and the rest are
  alternatives (`multi_source-en-05`, `-fr-04` say so in their notes).
- [x] **What counts as an acceptable alternative.** An expected tool returns what the question
  asks for. An alternative also returns it by another route, or is the documented first step of
  the expected tool when the question does not give the id that tool needs: so
  `wds_search_cubes` is an acceptable alternative to the indicators feed (it leads to the table),
  and so are `cmhc_list_categories` and `boc_search_series`. A table search is accepted for the
  main metrics and not for the `strict` ones, which is the distinction the two metrics exist to
  make. Tools that only describe, or need the answer as input, are not accepted.
- [x] **Single-tool lookups scored against `plan_query`.** `plan_query`'s docstring says "Use
  search_tools instead to find a single tool for a narrow, single-source need." Questions that
  name an identifier or ask about one source's catalogue mechanics are now search-only (15):
  `statcan-en-03`, `-en-04`, `-en-05`, `-en-10`, `-en-15`, `statcan-fr-03`, `-fr-08`, `boc-en-03`,
  `-en-04`, `boc-fr-04`, `cmhc-en-04`, `-en-05`, `-en-07`, `cmhc-fr-04`, `-fr-05`. Questions about
  a subject in one source stay plan-scored, including the release-calendar, "updated today",
  Daily and survey-methods questions (the planner has a `statcan_updates` topic, and a subject
  plan can reasonably name them). Five of the 15 had no accepted tool anywhere in their plan
  and two more lacked the expected one, so this raises the plan scores; `baseline.md` shows the
  numbers with and without it.

## 2. Expectations the author doubted

Ambiguous questions (`ambiguity-*`):

- [x] `ambiguity-en-03`, `-04`, `ambiguity-fr-01` (poverty). Table search stays expected (table
  11-10-0135 has both MBM and LIM); SDG and indicators-feed alternatives kept; the 2021 Census
  Profile (LIM-AT for ages 0 to 17) added to `-en-04`. Still no planner topic for poverty.
- [x] `ambiguity-en-05` (population of Calgary). Neither comes first: the Census count and the
  annual estimate are both expected. "census metropolitan area" added to the flags.
- [x] `ambiguity-en-06` vs `ambiguity-fr-02` (median household income). The split is right
  (surveys stop at province, the Census reaches the city). Added: the indicators feed for the
  province, and the Montréal CKAN portal, which holds census household profiles with income
  (checked live), for the city.
- [x] `ambiguity-en-07`, `ambiguity-fr-04` (house prices). `wds_search_cubes` is now expected
  beside `crea_get_hpi_links`: it returns values (NHPI by CMA), CREA returns links and terms.
- [x] `ambiguity-en-08` (core inflation). `boc_search_series` and `wds_search_cubes` (table
  18-10-0256) both expected; BoC group tools added; the indicators feed removed (no core
  measure). Flag `core` replaced by `cpi-common`: `core` is a word of the question.
- [x] `ambiguity-en-01`, `ambiguity-fr-03` (jobs), `ambiguity-en-02` (weekly earnings). The
  indicators feed answers directly (employment level, average weekly earnings, checked live), so
  it is expected beside table search.
- [x] `ambiguity-en-10`, `ambiguity-fr-07` (immigration). Both IRCC tools expected in both
  languages (they disagreed); the indicators feed's quarterly immigrant flow added.
- [x] `ambiguity-en-12`, `ambiguity-fr-08` (oil production). Alberta's dashboard (`OilProduction`)
  added to `-en-12`; AER removed from `-fr-08` (Canada), the indicators feed added there.
- [x] `flag_terms`. Kept lenient (any one term). Removed terms that are words of the question or
  name the primary reading (`core`, `affordab*`, `statistique canada`). They remain a weak
  signal: a term can appear in a plan that does not explain the distinction.

Single-source questions:

- [x] `statcan-en-07`, `statcan-fr-06` (next release date): kept plan-scored; the calendar is
  still expected; the Daily archive replaces `statcan_daily_get_releases` as the alternative.
- [x] `statcan-en-09` (household-spending microdata): `statcan_pumf_search` stays; the Data
  catalogue, RDC holdings and ODESI added (all return the survey's microdata, checked live); the
  survey directory removed. `statcan-fr-10` (survey methods): `statcan_surveys_search_surveys`
  and `statcan_surveys_get_survey_metadata` both expected for search.
- [x] `statcan-en-11` (gender wage gap articles): confirmed; the Daily archive added.
- [x] `statcan-en-13`, `statcan-fr-07`: corrected (see above); for crude oil, `cimt_get_series`
  is expected beside `cimt_get_trade` (its own docstring example). CER's export file was checked
  and has volumes only, so it does not answer "valeur".
- [x] `boc-en-04`: confirmed (`boc_get_group` lists members); now search-only.
- [x] `ckan_federal-en-02`: `ckan_search_datasets` added (its results carry each dataset's licence,
  checked live). `ckan_federal-fr-01`: the ECCC Data Catalogue added; `eccc_query_items` removed
  from the plan alternatives.
- [x] `municipal-en-08`: easy, kept as is.

Multi-source questions:

- [x] `multi_source-en-10`: CIHI alone expected (see above).
- [x] `multi_source-fr-07`: aligned (see above).
- [x] `multi_source-en-02`, `-en-05`, `-en-09`, `-fr-02`, `-fr-05`: pairs kept except `-fr-02`;
  alternatives added for the other sources that hold the data. `multi_source-fr-06` asked three
  things and named two tools: `cdc_get_component_prices` (milk prices) added.

## 3. Places and portals

- [x] Every portal key exists in its family's `PORTALS` (the fixture test checks it) and each
  province or city is on the family the question expects (Socrata for Nova Scotia, New Brunswick,
  Calgary, Edmonton and Winnipeg; ArcGIS Hub for Manitoba, PEI and Ottawa; CKAN for Ontario,
  BC, Québec, Yukon, Toronto, Montréal and Gatineau through Québec; Newfoundland and Labrador,
  Open Alberta and Vancouver have modules of their own).
  Live searches were run only for the portals of the multi-source and ambiguity questions:
  Toronto (`multi_source-en-01`)
  and Montréal (`multi_source-fr-01`) were dropped from `plan_portals`: neither portal has rent
  or rate series. BC (`multi_source-en-06`, housing starts on the BC portal) and Ontario
  (`multi_source-fr-03`, housing supply) were kept, and Montréal's portal was found to hold
  census household income (`ambiguity-fr-02`). Whether every portal holds every
  `ckan_provincial` and `municipal` topic was not searched one by one; the portal metric still
  partly checks the planner against its own maps.
- [x] `municipal-en-09`, `municipal-fr-07`: OC Transpo and the STM are both in
  `transit_list_agencies` (checked live). `transit_get_route_summary` added to `-fr-07`.
- [x] `municipal-en-07` (Edmonton police occurrences by neighbourhood): no tool groups by
  neighbourhood (the summary groups by category, type, month or intersection, and occurrences
  carry coordinates), and Edmonton's Socrata portal has no neighbourhood crime set (checked
  live). Both EPS tools are expected.

## 4. Wording and coverage

- [ ] **French wording.** Not reviewed: the owner decided to assume it is fine. A francophone
  should still read `municipal-fr-02`, `ckan_provincial-fr-01` and the rest.
- [ ] **Overlap with pinned tests.** Unchanged: nine questions paraphrase pinned discovery tests.
- [ ] **Missing kinds of question.** Still none of: out-of-scope or nonsense questions (which
  should abstain), misspellings, one-word queries, table ids in prose, tool descriptions as
  queries. Add them before an embedding index is tested.
- [x] **Sample size.** Unchanged, and smaller for the plan: `cmhc` has 6 plan-scored questions,
  `ckan_federal` 5 and `boc` 8, so one question moves those by 12 to 20 points.

## 5. Ids used in the live pass (`live_expected`)

- [x] `statcan-en-01`, `statcan-fr-01`: 14100287, the Labour Force Survey table. Confirmed.
- [x] `statcan-en-13`: 12100011 is the right table for total exports to the US by month: it is
  what `wds_search_cubes` returns for "merchandise trade principal trading partners monthly"
  (checked live), and it is now the question's expected route.
