# Discovery benchmark

A fixed set of natural-language questions, in English and French, scored against
`search_tools` (BM25 over tool docstrings) and `plan_query` (the rule-based planner).
It exists so that any change to discovery (an index, embeddings, new docstring
keywords, planner terms) is judged against numbers, not impressions. Phase 1 of the
discovery plan: nothing new is added to discovery until a reproducible baseline is on
record. The baseline is [`baseline.md`](baseline.md); the review checklist for the
fixtures is [`REVIEW.md`](REVIEW.md).

Offline and deterministic: both systems read the registry and bundled maps, no
network, no model, no new dependency.

## Run it

```bash
uv run python -m tests.discovery_benchmark            # writes latest/results.json and latest/results.md
uv run python -m tests.discovery_benchmark --out some/folder
uv run pytest tests/test_discovery_benchmark.py       # fixtures sound, floors held
```

`latest/` is gitignored; the committed record is `baseline.json` (every query's top 10
and plan, one line each) and `baseline.md`. To compare a change with the baseline, run
the benchmark and diff `latest/results.json` against `baseline.json` (the summaries come
first, then one line per query).

The optional live pass asks the sources' own lexical search the same questions
(`wds_search_cubes`, `ckan_search_datasets`), paced by the server's per-source rate
limits plus `--pause`. It needs the network and is never run by pytest:

```bash
uv run python scripts/discovery_benchmark_live.py --category statcan --limit 10
```

## Fixtures: `queries.json`

One object per question. Keys other than these are rejected, so a typo cannot silently
drop an expectation.

| key | meaning |
|---|---|
| `id` | `<category>-<lang>-NN`, unique |
| `query`, `lang` | the question as a user types it; `en` or `fr` (also sent to `plan_query` as `lang`) |
| `category` | `statcan`, `boc`, `cmhc`, `ckan_federal`, `ckan_provincial`, `municipal`, `multi_source`, `ambiguity` |
| `search_expected` | tools a correct `search_tools` answer names; any one counts (a hit) |
| `search_alternatives` | other tools that also answer it; a hit on one counts for the main metrics, not for the `strict` ones |
| `plan_topics` | planner topic keys (`TOPICS` in `modules/planner/topics.py`) the plan should return |
| `plan_expected`, `plan_alternatives` | the same split, for the tools anywhere in the plan; `plan_expected` is also scored as coverage (all of them) |
| `plan_portals` | portal keys (`portal='on'`) a step of the plan should name |
| `geography`, `period` | notes for the reviewer; not scored |
| `ambiguous`, `ambiguity_kind` | the question has more than one reasonable reading (for example LFS vs SEPH, MBM vs LIM, Census vs survey) |
| `flag_terms` | for ambiguous questions: words that show the plan names an alternative reading |
| `live_expected` | table or dataset ids verified in this repo's tests or smoke scripts, for the live pass only |
| `reviewed` | `false` until a person other than the author has checked the expectations |
| `notes` | where an expectation came from or why it is doubtful |

Expectations are at tool level. A StatCan table id appears only where this repo's
tests, docs or smoke scripts already use it; nothing else is invented.
`tests/test_discovery_benchmark.py` fails if an expected tool is not in the live
registry, a topic or portal does not exist, or an id is duplicated.

## Metrics

All are computed per query, then averaged by category and by language.

- **Recall@k**: an accepted tool (expected or alternative) is within the first k results.
  `search_tools` returns at most 5 tools, so ranks 6 to 10 come from a second
  `BM25SearchTransform(max_results=10)` over the same catalogue; the runner checks that its
  first five equal the server's on every query (`parity`).
- **MRR**: mean of 1 / rank of the first accepted tool (0 when absent).
- **strict**: the same with `search_expected` only, alternatives not counted.
- **source@1**: the top-1 tool belongs to the same source (the agency or module family, for
  example `statcan` or `boc`) as an accepted tool. Looser than R@1.
- **error / abstain**: a raised error; an empty `search_tools` answer, or a plan that matched
  no topic and no place (only the generic fallback steps) or was marked out of scope.
- **plan_query ranks**: the plan's tools flattened in the order shown: topics (best first,
  each topic's steps in order), then the named places' steps, then the fallback steps.
  `anywhere` ignores order. `routed` also ignores the fallback steps, which every
  unmatched question receives. `coverage` is the share of `plan_expected` present.
  `topic` is any expected topic returned; `portal` is every expected portal named.
- **ambiguity**: for `search_tools`, the share of the accepted tools found in the top 5; for
  `plan_query`, whether the plan's text names one of the `flag_terms` (lenient: any one).
- **latency**: wall time of one in-process call, including serialisation; reported, never
  asserted. The first search builds the BM25 index of 356 tools and is timed apart.

## The regression floor

`tests/test_discovery_benchmark.py` fails when a headline metric falls below a floor set a
little below the baseline (about 0.04 overall, 0.05 per language, 0.10 per category: one
flipped query in a small category is tolerated, two are not). Raise a floor when a change
improves the numbers on purpose. Do not lower one without recording why in `baseline.md`.
The test takes about 1.5 s beyond the server import every test file pays.

## Adding or changing a question

Add a line to `queries.json`, keep `reviewed: false`, run the test, and rerun the benchmark.
Decide the expectation from the tool catalogue and the question, before running it, and
record any later correction in `baseline.md`; an expectation edited to match a result makes
the benchmark measure itself.
