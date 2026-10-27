# Discovery baseline, 2026-10-27 (reviewed fixtures)

The Phase 1 gate of the discovery plan: a reproducible measurement of how well
`search_tools` and `plan_query` route 129 natural-language questions before any index or
embedding is added. Nothing in `src/` was changed to produce it. The first baseline was
recorded on 2026-10-19 against an unreviewed answer key; its numbers are kept below for
comparison.

- Run: fastmcp 4.1.3, 375 registered tools (374 searchable; `plan_query` is always visible),
  fixtures `5846d2758d0a2c2d`, Linux, one process, in-process client. The 2026-10-19 run had
  fastmcp 4.1.0, 357 tools (356 searchable), fixtures `c50fda6d6a28635d`, on Windows.
- Raw record: [`baseline.json`](baseline.json) (summaries, then one line per question with the
  top 10 tools and the flattened plan). Regenerate with
  `uv run python -m tests.discovery_benchmark`; method and metric definitions are in
  [`README.md`](README.md).
- Status of the fixtures: **129 of 129 reviewed, by a second, independent AI session** on
  2026-10-27, at the owner's request. The author of the expected answers was an AI session that
  had read the tool catalogue; the reviewer was a different session. **No person has reviewed
  them.** The French questions were reviewed for their expected tools only; their wording was not
  read by a francophone (the owner decided to assume it is fine). What the review decided and
  changed is in [`REVIEW.md`](REVIEW.md).

## The fixtures

129 questions: 76 English, 53 French. All 129 carry a `search_tools` expectation; 105 carry a
`plan_query` one (120 before the review, which made 15 identifier and catalogue-mechanics
lookups search-only, as `plan_query`'s docstring asks).

| category | en | fr | total | plan-scored |
|---|---:|---:|---:|---:|
| statcan | 15 | 10 | 25 | 18 |
| boc | 7 | 5 | 12 | 8 |
| cmhc | 7 | 5 | 12 | 6 |
| ckan_federal | 7 | 5 | 12 | 5 |
| ckan_provincial | 7 | 5 | 12 | 12 |
| municipal | 9 | 7 | 16 | 16 |
| multi_source | 12 | 8 | 20 | 20 |
| ambiguity | 12 | 8 | 20 | 20 |

### History of the answer key

Before the review (2026-10-19, by the author, after the first run; only the first touched a
search expectation):

1. `boc-en-04`: `boc_get_group` and `boc_get_group_observations` swapped as expected and
   alternative (no score moved).
2. `flag_terms` on nine ambiguous questions tightened and matched as whole words (0.71 on 17
   questions before, 0.59 after, 0.50 with item 3).
3. `plan_expected` added to the three poverty questions (`ambiguity-en-03`, `-en-04`, `-fr-01`);
   the plan sample went from 117 to 120.
4. `live_expected` added to three StatCan questions (live pass only), and the `routed` plan
   metric added.

The review (2026-10-27, second AI session) changed 83 of 129 questions (47 English, 36 French),
deciding every change before running the benchmark on the new key:

- `search_tools`: accepted tools changed on 61 questions; 76 tools added as correct answers, 20
  removed; the expected list changed on 21.
- `plan_query`: 15 questions made search-only (120 to 105); accepted tools changed on 41 of the
  105 (58 added, 10 removed); the expected list changed on 8; 2 portals dropped from
  `plan_portals`; `flag_terms` changed on 4 ambiguous questions.

## Results

`R@k`: an accepted tool is in the first k. `strict R@5`: expected tools only, alternatives not
counted. `source@1`: the top tool is from the right agency. Plan ranks flatten the plan in the
order it shows the steps; `anywhere` ignores order; `routed` leaves out the generic fallback
steps; `coverage` is the share of `plan_expected` present; `topic` and `portal` are the shares
that named an expected topic or portal; `abstain` is a plan with no topic and no place.

### What moved the numbers: registry or answer key

The same benchmark run three ways. "2026-10-19" is the first baseline. "Old key" is the
unreviewed key run on 2026-10-27, against today's registry. "Reviewed" is this baseline. Old key
to reviewed isolates the review; 2026-10-19 to old key isolates the 18 tools added since (the
BIS, CBSA tariff, ISC and Ontario FIR modules, and `wds_get_series_as_of`).

| search_tools (n = 129) | 2026-10-19 | old key | reviewed |
|---|---:|---:|---:|
| R@1 | 0.58 | 0.56 | 0.56 |
| R@5 | 0.87 | 0.86 | 0.87 |
| R@10 | 0.92 | 0.91 | 0.91 |
| MRR | 0.70 | 0.69 | 0.69 |
| strict R@5 | 0.81 | 0.81 | 0.80 |
| source@1 | 0.80 | 0.78 | 0.80 |

| plan_query | 2026-10-19 (n = 120) | old key (n = 120) | old key, same 105 | reviewed (n = 105) |
|---|---:|---:|---:|---:|
| R@1 | 0.53 | 0.53 | 0.54 | 0.55 |
| R@5 | 0.83 | 0.83 | 0.86 | 0.86 |
| anywhere | 0.88 | 0.88 | 0.91 | 0.91 |
| routed | 0.83 | 0.83 | 0.86 | 0.86 |
| MRR | 0.66 | 0.66 | 0.68 | 0.68 |
| coverage | 0.85 | 0.85 | 0.90 | 0.89 |

Read together: the review hardly moves `search_tools` overall, because its additions (tools that
were right and unlisted) and removals (tools that were credited and cannot answer) cancel out;
it moves single questions and categories (below). The `plan_query` gain comes entirely from
making 15 lookups search-only, five of which had no accepted tool in their plan: on the same 105
questions the old and the reviewed keys score the same. The registry growth cost `search_tools`
about one or two points at rank 1 and rank 10 (new BIS tools now outrank the Bank of Canada for
French exchange-rate questions, for example).

### search_tools (n = 129), reviewed key

| | n | R@1 | R@5 | R@10 | MRR | strict R@5 | source@1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| **all** | 129 | 0.56 | 0.87 | 0.91 | 0.69 | 0.80 | 0.80 |
| statcan | 25 | 0.76 | 1.00 | 1.00 | 0.85 | 0.92 | 0.88 |
| boc | 12 | 0.50 | 0.75 | 0.92 | 0.64 | 0.75 | 0.75 |
| cmhc | 12 | 0.83 | 1.00 | 1.00 | 0.92 | 1.00 | 1.00 |
| ckan_federal | 12 | 0.42 | 0.75 | 0.83 | 0.57 | 0.58 | 0.58 |
| ckan_provincial | 12 | 0.25 | 0.75 | 0.92 | 0.46 | 0.67 | 0.75 |
| municipal | 16 | 0.62 | 1.00 | 1.00 | 0.78 | 1.00 | 0.88 |
| multi_source | 20 | 0.50 | 1.00 | 1.00 | 0.70 | 1.00 | 0.90 |
| ambiguity | 20 | 0.45 | 0.60 | 0.65 | 0.52 | 0.40 | 0.60 |
| English | 76 | 0.59 | 0.87 | 0.91 | 0.71 | 0.83 | 0.83 |
| French | 53 | 0.51 | 0.87 | 0.92 | 0.66 | 0.75 | 0.75 |

2026-10-19 values for comparison (old key, old registry): statcan R@1 0.80 / R@5 0.96, boc 0.83 /
0.83, cmhc 0.83 / 1.00, ckan_federal 0.33 / 0.75, ckan_provincial 0.25 / 0.75, municipal 0.62 /
1.00, multi_source 0.40 / 1.00, ambiguity 0.50 / 0.60, English 0.62 / 0.89, French 0.53 / 0.83.

Errors 0, empty answers 0 for every group. The accepted tool was first for 72 of 129 questions
(75 on 2026-10-19), second to fifth for 40 (37), sixth to tenth for 6 (7), and absent from the
top ten for 11 (10).

### plan_query (n = 105), reviewed key

| | n | R@1 | R@5 | anywhere | routed | coverage | topic | portal | abstain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **all** | 105 | 0.55 | 0.86 | 0.91 | 0.86 | 0.89 | 0.92 | 0.96 | 0.08 |
| statcan | 18 | 0.17 | 0.56 | 0.61 | 0.56 | 0.61 | 0.78 | - | 0.17 |
| boc | 8 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | - | 0.00 |
| cmhc | 6 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | - | 0.00 |
| ckan_federal | 5 | 0.40 | 0.80 | 0.80 | 0.60 | 0.60 | 0.67 | - | 0.20 |
| ckan_provincial | 12 | 0.33 | 0.67 | 0.92 | 0.92 | 0.83 | - | 0.89 | 0.08 |
| municipal | 16 | 0.69 | 0.88 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 |
| multi_source | 20 | 0.65 | 1.00 | 1.00 | 1.00 | 0.95 | 1.00 | 1.00 | 0.00 |
| ambiguity | 20 | 0.55 | 1.00 | 1.00 | 0.80 | 1.00 | 0.94 | 1.00 | 0.15 |
| English | 60 | 0.55 | 0.85 | 0.92 | 0.87 | 0.92 | 0.95 | 1.00 | 0.07 |
| French | 45 | 0.56 | 0.87 | 0.91 | 0.84 | 0.84 | 0.89 | 0.90 | 0.09 |

2026-10-19 `anywhere` for comparison (n = 120): statcan 0.68 (n = 25), boc 0.91 (11), cmhc 0.82
(11), ckan_federal 0.80 (5), ckan_provincial 0.83, municipal 1.00, multi_source 1.00, ambiguity
1.00, English 0.90, French 0.86.

Errors 0. The plan contained an accepted tool for 96 of 105 questions (106 of 120 before) and
listed it first for 58 (64). `ckan_federal` has only 5 plan-scored questions and `cmhc` 6.

### Ambiguity questions (n = 20)

- `search_tools`: the top 5 hold on average 0.22 of the accepted tools (0.23 before): a result
  list rarely offers more than one reading.
- `plan_query`: the plan's text names one of the alternative readings (`flag_terms`) for 0.45 of
  the 20 questions (0.50 before). The drop is `ambiguity-en-08`: its plan was credited for
  echoing "core", a word of the question, and names no core measure.

### Cost

In-process, one call: `search_tools` p50 13 ms and p95 17 ms; `plan_query` p50 6 ms and p95
9 ms. The first search builds the BM25 index of 374 tools in about 0.7 s.

## Weakest areas after the review

1. **Ambiguity questions in `search_tools`**: R@5 0.60, R@10 0.65, strict R@5 0.40. Seven of the
   eleven questions with no accepted tool in the top ten are ambiguous, short and general
   ("How many Canadians have a job?", "Population of Calgary", "Prix des logements à Montréal").
2. **StatCan questions in `plan_query`**: R@1 0.17, anywhere 0.61, abstain 0.17. After the
   review, these are subject questions (release dates, updates today, Daily releases, articles,
   survey methods), not lookups: 7 of the 9 plans without an accepted tool are StatCan ones.
3. **Bank of Canada in `search_tools`**: R@1 0.50 (0.83 before). `boc_get_series`, which
   returns a label, is first for three English data questions (`boc-en-01`, `-02`, `-03`), and
   the old key credited it; `boc_get_observations` is first for no question. Both French
   exchange-rate questions fall outside the top five (`boc-fr-05` absent), behind the new BIS
   tools.
4. **CKAN questions in `search_tools`**: R@1 0.42 (federal) and 0.25 (provincial). The portal
   tool is usually in the top five but seldom first.
5. **French**: R@5 now equal to English (0.87), but R@1 0.51 against 0.59, strict R@5 0.75 against
   0.83, and the plan's coverage 0.84 against 0.92.

## Worst failing questions

`search_tools`, no accepted tool in the top five (17 of 129; 11 not in the top ten):

| id | question | accepted tool (rank) | top 5 returned |
|---|---|---|---|
| ambiguity-en-01 | How many Canadians have a job? | wds_search_cubes, statcan_indicators_get_indicators (absent) | drivebc_summarize_events, ab_economic_list_indicators, electricity_ontario_get_adequacy_outlook, on_fir_list_schedules, borealis_odesi_get_dataset |
| ambiguity-fr-03 | Nombre d'emplois au Canada | wds_search_cubes, statcan_indicators_get_indicators (absent) | drivebc_summarize_events, ab_economic_list_tables, cwfis_list_situation_reports, recalls_summarize, hc_vigilance_search_reactions |
| ambiguity-en-02 | Average weekly earnings in Canada | wds_search_cubes, statcan_indicators_get_indicators (absent) | nwt_stats_search_files, cwfis_list_situation_reports, ab_wildfire_get_season_statistics, electricity_ontario_get_hoep_history, gazette_list_issues |
| ambiguity-en-03 | What is the poverty rate in Canada? | wds_search_cubes (absent) | boc_search_series, boc_get_series, worldbank_get_indicator, fcac_search_credit_cards, boc_get_group_observations |
| ambiguity-en-04 | Child poverty by province | wds_search_cubes (absent) | statcan_census_profile_search_characteristic, finance_fiscal_monitor_get_tables, cimt_get_province_breakdown, sdmx_get_structure, ourcommons_get_party_standings |
| ambiguity-en-05 | Population of Calgary | statcan_census_profile_get_data, wds_search_cubes (absent) | ab_economic_get_data, socrata_list_portals, socrata_search_datasets, transit_get_feed_info, ab_opendata_read_resource |
| ambiguity-fr-04 | Prix des logements à Montréal | crea_get_hpi_links, wds_search_cubes (absent) | ckan_search_datasets, ckan_list_portals, nwt_stats_search_files, bis_compare_countries, cmhc_list_provinces |
| boc-fr-05 | Cours de l'euro par rapport au dollar canadien depuis 2020 | boc_get_observations (absent) | bis_compare_countries, bis_get_series, finance_fiscal_monitor_list_issues, nrcan_minerals_get_production, cdc_query_market_data |
| ckan_federal-en-05 | CRA T1 income tax return statistics datasets by tax year | ckan_search_datasets (absent) | cra_digital_economy_registry_search, finance_frt_get_table, finance_fiscal_monitor_get_tables, ckan_describe_resource, ab_opendata_read_resource |
| ckan_federal-fr-03 | Données de l'ARC sur les déclarants de l'impôt des particuliers | ckan_search_datasets (absent) | on_fir_get_schedule, cra_charities_get_directors, cra_charities_get_charity, on_fir_search_lines, cra_charities_search |
| ckan_provincial-en-02 | British Columbia provincial datasets on water quality | ckan_search_datasets (absent) | bc_stats_list_files, elections_provincial_list_elections, epcor_get_daily_water_quality, ckan_list_portals, isc_list_short_term_advisories |
| boc-en-02 | USD to CAD exchange rate for the last 30 days | boc_get_observations (6) | boc_get_series, electricity_ontario_get_prices, bis_get_series, cihi_get_indicator_data, bis_compare_countries |
| ambiguity-fr-08 | Production de pétrole au Canada | wds_search_cubes (6) | aer_get_production_volumes_link, nrcan_minerals_get_production, nrcan_minerals_get_series, cdc_get_national_quota, cdc_query_market_data |
| boc-fr-02 | Taux de change du dollar américain en dollar canadien | boc_get_observations (7) | bis_get_series, cimt_get_trade, bc_stats_read_file, fcac_search_credit_cards, worldbank_get_indicator |
| ckan_provincial-en-01 | Ontario open data on long-term care homes | ckan_search_datasets (7) | crea_get_hpi_links, isc_list_drinking_water_advisories, on_fir_list_schedules, on_fir_get_schedule, ckan_list_portals |
| ckan_federal-en-06 | Find federal datasets tagged climate change | ckan_search_datasets (8) | eccc_coverages_search, eccc_search_collections, eccc_coverages_describe, eccc_datamart_search, worldbank_list_topics |
| ckan_provincial-fr-02 | Données ouvertes de la Colombie-Britannique sur les parcs provinciaux | ckan_search_datasets (8) | ckan_list_portals, opendatasoft_vancouver_search_datasets, bc_env_list_streamflow_gauges, bc_stats_list_files, bc_env_get_streamflow |

`plan_query`, no accepted tool anywhere in the plan (9 of 105):

| group | questions | what the plan returned |
|---|---|---|
| no topic and no place, fallback tools only | `statcan-en-06`, `statcan-fr-09` (updated today), `ckan_provincial-fr-03` | `statcan_reference_search_data`, `wds_search_cubes`, `ckan_search_datasets`, `ckan_read_resource` |
| a topic matched, but it has no step for the tool wanted | `statcan-en-07`, `statcan-fr-06` (release calendar), `statcan-en-11` (analysis articles), `statcan-en-12` (the Daily), `statcan-fr-10` (survey methods, matched `population`), `ckan_federal-en-06` (environment topic) | topic steps for another source |

## Where the search tool and the old key disagreed

Questions where `search_tools` ranked a tool the old key did not accept, and the review found
that tool correct: `statcan-en-14` (`wds_get_series_as_of` first, a tool added after the
fixtures), `ckan_federal-en-02` (`ckan_search_datasets` first; its results carry each licence),
`ambiguity-fr-02` (`ckan_search_datasets` first; Montréal's portal has census household income),
`multi_source-en-02` (`ab_economic_get_indicator_series` first), `multi_source-en-12`
(`eps_list_occurrences` first), `multi_source-fr-08` (`statcan_census_profile_search_characteristic`
first), `statcan-fr-07` (`cimt_search_commodities` second), `ckan_provincial-fr-05`
(`statcan_lode_query` third), `multi_source-en-06` (`bc_stats_list_files` fourth).

The reverse, where the old key credited a tool `search_tools` ranked high and the review found it
cannot answer: `boc-en-01`, `boc-en-02`, `boc-en-03` (`boc_get_series` first: a label, not a
rate), `statcan-en-13` (`cimt_get_trade` first: commodity rows, not monthly totals),
`statcan-en-10` (`rdaas_get_classification_categories_detailed` first: empty for NAICS 2022),
`statcan-fr-06` (`statcan_daily_get_releases` second: past releases only), `ambiguity-fr-08`
(`aer_get_production_volumes_link` first: Alberta only, for a Canada question).

## Observed patterns

These are what the numbers and the returned lists show. None is a diagnosis.

1. **Place and agency names decide the ranking.** For "British Columbia provincial datasets on
   water quality" the top five are BC Stats, provincial elections, Edmonton water quality, a list
   of portals and First Nations water advisories; `ckan_search_datasets` is absent.
2. **Conversational wording is scored on function words.** `STOP_WORDS` in `shared/search.py`
   holds French words only. "How many Canadians have a job?" returns tools unrelated to employment,
   although the indicators feed answers it in one call.
3. **New sources displace old ones on shared words.** The BIS tools added since 2026-10-19 now
   rank above the Bank of Canada for both French exchange-rate questions and the English USD/CAD
   one, and `on_fir_*` appears in three failing top-five lists.
4. **The right source is found more often than the right tool.** `source@1` is 0.80 against R@1
   of 0.56: in 31 of the 103 questions whose top tool is from the right agency, it is not an
   accepted tool, often a label, list or options tool where a data tool was wanted
   (`boc_get_series` three times).
5. **`plan_query` is strong where a topic exists and blind where none does.** `multi_source`
   plans name every source in 19 of 20 (coverage 0.95; `multi_source-fr-07` lists the Fiscal
   Reference Tables' list step but not the read), and `boc` and `cmhc` subject questions are all
   routed. StatCan questions about releases, updates, articles and methods are not.
6. **A topic can match for the wrong reason.** "Ontario open data on long-term care homes" returns
   the `housing` topic ("home" matches "homes"); "Définitions, sources et méthodes de l'Enquête
   sur la population active" returns `population`.
7. **Ambiguity is rarely surfaced.** The top five of `search_tools` hold 22% of the accepted tools
   for ambiguous questions; the plan text names an alternative reading for 45%.
8. **`search_tools` never says "nothing matched".** It returned a non-empty list for all 129
   questions, including the 11 with no accepted tool in the top ten.

## Not measured, and limits

- The answer key was reviewed by a second AI session, not by a person, and not blind (it saw the
  old key). French wording was not reviewed by a francophone.
- No out-of-scope, misspelled, one-word or nonsense questions, so abstaining correctly is
  untested.
- Nine questions paraphrase queries already pinned in the existing discovery tests.
- Sample size: 5 to 25 questions per category (one question is 4 to 20 points); no confidence
  intervals. Differences under about 10 points between categories are not reliable.
- Tool-level expectations cannot score the intended distinction in an ambiguity question (MBM or
  LIM, LFS or SEPH); both readings are the same tool.
- The schema cannot say "one tool per source, any of these", so `coverage` for a multi-source
  question requires the one tool per source that `plan_expected` names.
- Ranks 6 to 10 come from a second BM25 index that matched the server's top five on every
  question; it relies on fastmcp internals (`BM25SearchTransform._search`).
- The registry changes between runs; the comparison above separates its effect from the review's
  only for this pair of runs.
- Live pass (`scripts/discovery_benchmark_live.py`) not rerun for this baseline.

## Regression floors

`tests/test_discovery_benchmark.py` fails below: `search_tools` R@1 0.53, R@5 0.83, R@10 0.88,
MRR 0.66 overall, R@5 0.84 English and 0.81 French, and per category 0.10 below the table above;
`plan_query` R@5 0.81, anywhere 0.87, routed 0.81, MRR 0.63, coverage 0.84, topic 0.88, portal
0.91 overall, `anywhere` 0.86 for each language, and per category 0.10 below, or 1/n below for
`boc`, `cmhc` and `ckan_federal` (fewer than 10 plan questions each). Raised with this baseline:
French search R@5 (0.78 to 0.81), StatCan search R@5 (0.86 to 0.90), every overall plan floor,
both language plan floors, and the plan floors of `boc`, `cmhc` and `ckan_provincial`. Overall
search floors were left where they were (still within 0.03 of the baseline).

**Two floors were lowered, by the review and not by any change to discovery:**

- `boc` search R@5, 0.73 to 0.65. The reviewed key no longer credits `boc_get_series` (a label)
  for `boc-en-02`, so the category measures 0.75; the old floor would have failed on one more
  flipped question.
- `statcan` plan `anywhere`, 0.58 to 0.51. Seven StatCan lookups the planner answered became
  search-only, so the category measures 0.61 on 18 questions; the old floor tolerated no flip.

The test also fails on any raised error, a fixture naming an unregistered tool, topic or portal,
a parity mismatch, or two runs that disagree.
