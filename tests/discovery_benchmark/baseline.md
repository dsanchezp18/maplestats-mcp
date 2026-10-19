# Discovery baseline, 2026-10-19

The Phase 1 gate of the discovery plan: a reproducible measurement of how well
`search_tools` and `plan_query` route 129 natural-language questions before any index or
embedding is added. Nothing in `src/` was changed to produce it.

- Run: fastmcp 4.1.0, 357 registered tools (356 searchable; `plan_query` is always visible),
  fixtures `c50fda6d6a28635d`, Windows, one process, in-process client.
- Raw record: [`baseline.json`](baseline.json) (summaries, then one line per question with the
  top 10 tools and the flattened plan). Regenerate with
  `uv run python -m tests.discovery_benchmark`; method and metric definitions are in
  [`README.md`](README.md).
- Status of the fixtures: **0 of 129 reviewed**. The expected answers were written by an AI
  session that had read the tool catalogue, so every number below is conditional on a review that
  has not happened ([`REVIEW.md`](REVIEW.md)). Read them as a first measurement, not a verdict.

## The fixtures

129 questions: 76 English, 53 French. 120 carry a `plan_query` expectation, all 129 a
`search_tools` one.

| category | en | fr | total |
|---|---:|---:|---:|
| statcan | 15 | 10 | 25 |
| boc | 7 | 5 | 12 |
| cmhc | 7 | 5 | 12 |
| ckan_federal | 7 | 5 | 12 |
| ckan_provincial | 7 | 5 | 12 |
| municipal | 9 | 7 | 16 |
| multi_source | 12 | 8 | 20 |
| ambiguity | 12 | 8 | 20 |

Expected tools were written before the first run. Changes made after it (only the first
touched a search expectation):

1. `boc-en-04`: `boc_get_group` and `boc_get_group_observations` swapped as expected and alternative (a
   wrong pick, noticed on rereading; no score moved).
2. `flag_terms` on nine ambiguous questions tightened and matched as whole words (the first
   version took any substring, for example "census" or "estimate", as naming an alternative; it
   read 0.71 on 17 questions, 0.59 on the same 17 once tightened, and 0.50 with item 3).
3. `plan_expected` added to the three poverty questions (`ambiguity-en-03`, `-en-04`, `-fr-01`) so
   their flag terms are scored; the plan sample went from 117 to 120.
4. `live_expected` added to three StatCan questions (live pass only), and the `routed` plan metric
   added. Neither changes an offline score.

## Results

`R@k`: an accepted tool is in the first k. `strict R@5`: expected tools only, alternatives not
counted. `source@1`: the top tool is from the right agency. Plan ranks flatten the plan in the
order it shows the steps; `anywhere` ignores order; `routed` leaves out the generic fallback
steps; `coverage` is the share of `plan_expected` present; `topic` and `portal` are the shares
that named an expected topic or portal; `abstain` is a plan with no topic and no place.

### search_tools (n = 129)

| | n | R@1 | R@5 | R@10 | MRR | strict R@5 | source@1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| **all** | 129 | 0.58 | 0.87 | 0.92 | 0.70 | 0.81 | 0.80 |
| statcan | 25 | 0.80 | 0.96 | 1.00 | 0.88 | 0.96 | 0.88 |
| boc | 12 | 0.83 | 0.83 | 0.92 | 0.85 | 0.75 | 0.83 |
| cmhc | 12 | 0.83 | 1.00 | 1.00 | 0.92 | 1.00 | 1.00 |
| ckan_federal | 12 | 0.33 | 0.75 | 0.92 | 0.51 | 0.58 | 0.58 |
| ckan_provincial | 12 | 0.25 | 0.75 | 0.83 | 0.43 | 0.75 | 0.67 |
| municipal | 16 | 0.62 | 1.00 | 1.00 | 0.78 | 1.00 | 0.88 |
| multi_source | 20 | 0.40 | 1.00 | 1.00 | 0.64 | 1.00 | 0.85 |
| ambiguity | 20 | 0.50 | 0.60 | 0.70 | 0.56 | 0.40 | 0.65 |
| English | 76 | 0.62 | 0.89 | 0.92 | 0.73 | 0.86 | 0.83 |
| French | 53 | 0.53 | 0.83 | 0.92 | 0.66 | 0.75 | 0.75 |

Errors 0, empty answers 0 for every group. The accepted tool was first for 75 of 129 questions,
second to fifth for 37, sixth to tenth for 7, and absent from the top ten for 10.

### plan_query (n = 120)

| | n | R@1 | R@5 | anywhere | routed | coverage | topic | portal | abstain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **all** | 120 | 0.53 | 0.83 | 0.88 | 0.83 | 0.85 | 0.88 | 0.96 | 0.11 |
| statcan | 25 | 0.28 | 0.64 | 0.68 | 0.64 | 0.64 | 0.76 | - | 0.20 |
| boc | 11 | 0.91 | 0.91 | 0.91 | 0.91 | 0.82 | 0.91 | - | 0.09 |
| cmhc | 11 | 0.73 | 0.82 | 0.82 | 0.82 | 0.73 | 0.82 | - | 0.18 |
| ckan_federal | 5 | 0.40 | 0.80 | 0.80 | 0.60 | 0.60 | 0.67 | - | 0.20 |
| ckan_provincial | 12 | 0.33 | 0.58 | 0.83 | 0.83 | 0.83 | - | 0.89 | 0.08 |
| municipal | 16 | 0.69 | 0.88 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 |
| multi_source | 20 | 0.45 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 |
| ambiguity | 20 | 0.65 | 1.00 | 1.00 | 0.80 | 1.00 | 0.94 | 1.00 | 0.15 |
| English | 70 | 0.51 | 0.84 | 0.90 | 0.86 | 0.86 | 0.90 | 1.00 | 0.10 |
| French | 50 | 0.56 | 0.82 | 0.86 | 0.80 | 0.84 | 0.85 | 0.91 | 0.12 |

Errors 0. The plan contained an accepted tool for 106 of 120 questions and listed it first for 64.
`ckan_federal` has only 5 plan-scored questions.

### Ambiguity questions (n = 20)

- `search_tools`: the top 5 hold on average 0.23 of the accepted tools, that is, a result list
  rarely offers more than one of the readings.
- `plan_query`: the plan's text names one of the alternative readings (`flag_terms`) for 0.50 of
  the 20 questions (lenient: any one term).

### Cost

In-process, one call: `search_tools` p50 about 12 to 14 ms and p95 about 15 to 18 ms; `plan_query`
p50 about 5 ms and p95 about 8 ms. The first search builds the BM25 index of 356 tools: 0.7 to 1.1 s.
A single call in each system took about 90 ms once (a scheduling or garbage-collection spike; not
investigated). The server itself takes about 13 s to import.

## Weakest areas

1. **Ambiguity questions in `search_tools`**: R@5 0.60, R@10 0.70, strict R@5 0.40. Six of the ten
   questions with no accepted tool in the top ten (`ambiguity-en-01`, `-en-02`, `-en-04`, `-en-05`,
   `-fr-03`, `-fr-04`) are short, general questions.
2. **`ckan_provincial` and `ckan_federal` in `search_tools`**: R@1 0.25 and 0.33, MRR 0.43 and 0.51.
   The right tool is usually in the top five (0.75) but seldom first.
3. **StatCan lookups in `plan_query`**: R@1 0.28, anywhere 0.68, abstain 0.20. Many are plain
   tool-finding questions, and 8 of the 14 plans without an accepted tool matched no topic.
4. **French**: R@5 0.83 against 0.89 in English, strict R@5 0.75 against 0.86, MRR 0.66 against 0.73. At
   rank 10 the two are equal (0.92), so French answers are found but lower down. Largest category
   gaps: `boc` French R@5 0.60 against 1.00 in English (5 and 7 questions) and `ckan_provincial`
   French 0.60 against 0.86 (5 and 7).
5. **Ordering inside `plan_query`**: an accepted tool is present for 106 of 120 plans but first for
   64. Overall R@1 is 0.53 while anywhere is 0.88.

## Worst failing questions

`search_tools`, accepted tool outside the top five (17 of 129; 10 not in the top ten):

| id | question | accepted tool (rank) | top 5 returned |
|---|---|---|---|
| ambiguity-en-01 | How many Canadians have a job? | wds_search_cubes (absent) | drivebc_summarize_events, electricity_ontario_get_adequacy_outlook, ab_economic_list_indicators, borealis_odesi_get_dataset, ab_wildfire_get_fire_restrictions |
| ambiguity-fr-03 | Nombre d'emplois au Canada | wds_search_cubes (absent) | drivebc_summarize_events, ab_economic_list_tables, cwfis_list_situation_reports, recalls_summarize, hc_vigilance_search_reactions |
| ambiguity-en-02 | Average weekly earnings in Canada | wds_search_cubes (absent) | nwt_stats_search_files, cwfis_list_situation_reports, ab_wildfire_get_season_statistics, electricity_ontario_get_hoep_history, gazette_list_issues |
| ambiguity-en-04 | Child poverty by province | wds_search_cubes (absent) | statcan_census_profile_search_characteristic, finance_fiscal_monitor_get_tables, cimt_get_province_breakdown, sdmx_get_structure, ourcommons_get_party_standings |
| ambiguity-en-05 | Population of Calgary | statcan_census_profile_get_data (absent) | ab_economic_get_data, socrata_list_portals, socrata_search_datasets, ab_opendata_read_resource, transit_get_feed_info |
| ambiguity-fr-04 | Prix des logements à Montréal | crea_get_hpi_links (absent) | ckan_search_datasets, ckan_list_portals, nwt_stats_search_files, cmhc_list_provinces, cmhc_list_categories |
| boc-fr-05 | Cours de l'euro par rapport au dollar canadien depuis 2020 | boc_get_observations (absent) | finance_fiscal_monitor_list_issues, nrcan_minerals_get_production, cdc_query_market_data, bc_lobbyists_search_activity_reports, bc_lobbyists_summarize_activity |
| ckan_federal-en-05 | CRA T1 income tax return statistics datasets by tax year | ckan_search_datasets (absent) | cra_digital_economy_registry_search, finance_frt_get_table, finance_fiscal_monitor_get_tables, ckan_describe_resource, ckan_read_resource |
| ckan_provincial-en-02 | British Columbia provincial datasets on water quality | ckan_search_datasets (absent) | bc_stats_list_files, elections_provincial_list_elections, epcor_get_daily_water_quality, ckan_list_portals, bc_env_list_streamflow_gauges |
| ckan_provincial-fr-05 | Données ouvertes de l'Île-du-Prince-Édouard sur les écoles | arcgis_hub_search_datasets (absent) | statcan_lode_list_databases, arcgis_hub_list_portals, statcan_lode_query, bc_env_get_aqhi, ckan_list_licenses |
| ambiguity-en-03 | What is the poverty rate in Canada? | wds_search_cubes (8) | boc_search_series, boc_get_series, worldbank_get_indicator, fcac_search_credit_cards, boc_get_group_observations |
| ckan_federal-en-06 | Find federal datasets tagged climate change | ckan_search_datasets (8) | eccc_coverages_search, eccc_search_collections, eccc_coverages_describe, eccc_datamart_search, worldbank_list_topics |
| ckan_provincial-fr-02 | Données ouvertes de la Colombie-Britannique sur les parcs provinciaux | ckan_search_datasets (8) | ckan_list_portals, opendatasoft_vancouver_search_datasets, bc_env_list_streamflow_gauges, bc_stats_list_files, bc_env_get_streamflow |
| ckan_federal-fr-03 | Données de l'ARC sur les déclarants de l'impôt des particuliers | ckan_search_datasets (9) | cra_charities_get_directors, cra_charities_get_charity, cra_charities_search, cra_digital_economy_registry_search, competition_bureau_search_mergers |
| statcan-fr-07 | Valeur des exportations de pétrole brut vers les États-Unis | cimt_get_trade (6) | cer_list_datasets, cimt_search_commodities, cer_query_file, cgc_exports_query, cimt_get_top_partners |
| boc-fr-02 | Taux de change du dollar américain en dollar canadien | boc_get_observations (6) | cimt_get_trade, bc_stats_read_file, fcac_search_credit_cards, worldbank_get_indicator, fcac_search_bank_accounts |
| ambiguity-fr-02 | Revenu des ménages à Montréal | statcan_census_profile_get_data (6) | ckan_search_datasets, ckan_list_portals, cmhc_dt_list_tables, nrcan_energy_use_list_products, nrcan_energy_use_get_table |

`plan_query`, no accepted tool anywhere in the plan (14 of 120). The full list is in
`baseline.json`; the groups are:

| group | questions | what the plan returned |
|---|---|---|
| no topic and no place, fallback tools only (`statcan_reference_search_data`, `wds_search_cubes`, `ckan_search_datasets`, `ckan_read_resource`) | `statcan-en-06`, `statcan-en-10`, `statcan-fr-08`, `statcan-fr-09`, `boc-en-03`, `cmhc-en-04`, `cmhc-fr-04`, `ckan_provincial-fr-03` | the same four tools for every one |
| a topic matched, but the topic has no step for the tool wanted | `statcan-en-07`, `statcan-fr-06` (release calendar: labour and prices topics), `statcan-en-12` (the Daily: prices topic), `statcan-fr-10` (survey metadata: population topic), `ckan_federal-en-06` (environment topic), `ckan_provincial-fr-05` (facilities topic) | topic steps for another source |

## Observed patterns

These are what the numbers and the returned lists show. None is a diagnosis.

1. **Place and agency names decide the ranking.** For "British Columbia provincial datasets on
   water quality" the top five are BC Stats, provincial elections, Edmonton water quality, a list of
   portals and BC streamflow gauges; `ckan_search_datasets` is absent. For "Revenu des ménages à
   Montréal" and "Prix des logements à Montréal" the top result is `ckan_search_datasets`, the portal
   tool, ahead of the statistical tools. A `*_list_portals` tool is in the top
   five of 3 of the 6 CKAN-category misses and of 3 ambiguity misses.
2. **Conversational wording is scored on function words.** `STOP_WORDS` in
   `shared/search.py` holds French words only. "How many Canadians have a job?" is indexed as
   `how, many, canadian, have, job`, and its top five are tools unrelated to employment. The
   shortest ambiguous questions are the ones that fail (pattern 1 of the weakest areas).
3. **French exchange-rate questions miss the Bank of Canada tools.** Both French `boc` exchange-rate
   questions fall outside the top five (rank 6 and absent); the other three French `boc` questions
   are first. n is 5.
4. **The right source is found more often than the right tool.** `source@1` is 0.80 against R@1 of
   0.58: in 28 of the 103 questions whose top tool is from the right agency, it is not an accepted tool,
   for example a list or options tool where a data tool was wanted.
5. **`plan_query` is strong where a topic exists and blind where none does.** `multi_source` plans hold
   every expected tool (coverage 1.00) and `municipal` plans every portal (1.00), but 13 of 120
   plans (11%) match no topic and no place and return the same four generic tools, and 6 of the 106
   plans that contain an accepted tool contain it only there.
6. **A topic can match for the wrong reason.** "Ontario open data on long-term care homes" returns the
   `housing` topic (the term "home" matches "homes"), so its eight CMHC and housing steps come before
   the Ontario portal steps, and `ckan_search_datasets` is ninth. The `ckan_provincial` plans hold the
   portal tool in 83% of cases but first in 33%.
7. **"Job" is not "jobs".** "How many Canadians have a job?" matches no planner topic, while "How many
   jobs are there in Canada?" matches `labour`.
8. **Ambiguity is rarely surfaced.** The top five of `search_tools` hold 23% of the accepted tools for
   ambiguous questions, and the plan text names an alternative reading for half. The three poverty
   questions (MBM against LIM) have no planner topic at all.
9. **`search_tools` never says "nothing matched".** It returned a non-empty list for all 129
   questions, including the 10 with no accepted tool in the top ten. `plan_query` falls back to four
   generic tools for 13 of 120 and marked none out of scope. No question in the set should be
   declined, so whether a wrong answer would be recognised as one is not measured.

## Not measured, and limits

- No out-of-scope, misspelled, one-word or nonsense questions, so abstaining correctly is untested.
  `plan_query` can abstain; `search_tools` and an embedding index never return nothing.
- Fixture bias: written after reading the tool descriptions, by the same author as the baseline;
  nine questions paraphrase queries already pinned in the existing discovery tests.
- Sample size: 5 to 25 questions per category (one question is 4 to 20 points); no confidence
  intervals. Differences under about 10 points between categories are not reliable.
- Tool-level expectations cannot score the intended distinction in an ambiguity question (MBM or LIM,
  LFS or SEPH); both readings are the same tool.
- Ranks 6 to 10 come from a second BM25 index that matched the server's top five on every question;
  it relies on fastmcp internals (`BM25SearchTransform._search`), so a fastmcp upgrade can break the
  parity test before it breaks any number.
- Live pass (`scripts/discovery_benchmark_live.py`) smoke-tested on six questions only (3 StatCan,
  3 CKAN federal); it was not run on the full set and no live result is recorded here.

## Regression floors

`tests/test_discovery_benchmark.py` fails below: `search_tools` R@1 0.53, R@5 0.83, R@10 0.88, MRR
0.66 overall, R@5 0.84 English and 0.78 French, and per category 0.10 below the table above;
`plan_query` R@5 0.78, anywhere 0.83, routed 0.78, MRR 0.61, coverage 0.80, topic 0.83, portal 0.90
overall, plus per-language and per-category `anywhere` floors. The test also fails on any raised
error, a fixture naming an unregistered tool, topic or portal, a parity mismatch, or two runs that
disagree.
