# The Maple Test

Fifteen questions on Canadian economic and social statistics, with an answer key read
from the publishers' own APIs, for measuring how often an AI with a data tool gets the
number, the source and the call right.

It exists because MapleStats' first public result, 14 of 15 on CanData's GTA housing
benchmark ([`docs/findings/candata-gta-benchmark.md`](../../docs/findings/candata-gta-benchmark.md)),
was reached after fixing MapleStats against those questions. The Maple Test asks
different questions (labour, population, prices, output, trade, wages, markets) that were
written before MapleStats was run on them. **Rule: no fix may be tuned against these
questions without writing a new set to check the fix on.**

## The questions

| ID | Kind | Topic |
| :-- | :-- | :-- |
| M-01 | numeric | Canada's unemployment rate, September 2026 vs a year earlier |
| M-02 | comparison | Province with the highest unemployment rate, September 2026 |
| M-03 | numeric | Canada's population on July 1, 2026, and its growth |
| M-04 | comparison | Alberta vs Ontario population growth to July 1, 2026 |
| M-05 | numeric | Non-permanent residents, July 1, 2026 vs 2025 |
| M-06 | numeric | Canada's inflation for 2025 (annual average, not December) |
| M-07 | numeric | CPI-trim and CPI-median, September 2026 |
| M-08 | numeric | Real GDP change, August 2026 (essentially flat) |
| M-09 | numeric | Merchandise trade balance, August 2026 |
| M-10 | numeric | Average weekly earnings (SEPH), August 2026, and the year's rise |
| M-11 | numeric | Bank of Canada USD/CAD rate, October 30, 2026 |
| M-12 | numeric | 10-year Government of Canada benchmark yield, October 30, 2026 |
| M-13 | refusal | Real GDP growth in Q4 2026 (not published yet) |
| M-14 | refusal | USD/CAD on November 1, 2026 (a Sunday: no rate) |
| M-15 | flag | Unemployed people from a 2021 Census base and a 2026 rate |

Kinds, as in CanData's benchmark: **numeric** (values within tolerance), **comparison**
(the right call plus the values), **refusal** (say the figure does not exist; a number
fails), **flag** (state the problem with the requested calculation, or give the
published figure instead). Each question in [`maple_test_v1.json`](maple_test_v1.json)
lists its expected values, tolerance, traps and citations (table, vector, reference
period, value, release date, URL).

## Running it

You need a logged-in `claude` CLI.

```bash
uv run python -m tests.maple_test.build_key --check     # has any source revised the key?
uv run python -m tests.maple_test run --arm maplestats  # also mcp_statcan, no_tools
uv run python -m tests.maple_test grade                 # writes results.md and results.json
uv run pytest tests/test_maple_test.py                  # offline checks of the key and grader
```

`run` asks each question in an empty folder through headless Claude Code with built-in
tools off and `ENABLE_TOOL_SEARCH=false`, the setup CanData used, so the two benchmarks'
scores are read the same way. `--server-dir` serves a MapleStats checkout other than this
one (a frozen copy of `main`, for a fair before and after).

The grader reads numbers and phrases from the text, so a correct answer worded oddly can
be missed: read every grade that is not `correct`, and record a re-grade with its reason
in `overrides.json` (`{"<arm>/<question id>": {"outcome": ..., "reason": ..., "false_claim": ...}}`).

## First results, 2026-11-02

Eight arms on `claude-sonnet-5-5`, MapleStats at `main` (`11fcb84`). Full table in
[`results.md`](results.md), every answer in [`runs/`](runs/), re-grades with reasons in
[`overrides.json`](overrides.json).

| Arm | Correct | Partial | Abstained | Hallucinated |
| :-- | --: | --: | --: | --: |
| OpenMCP | 15 | 0 | 0 | 0 |
| CanData-MCP | 15 | 0 | 0 | 0 |
| MapleStats | 14 | 1 | 0 | 0 |
| arose26 (statcan-mcp and bank-of-canada-mcp) | 14 | 1 | 0 | 0 |
| mcp-canada | 14 | 1 | 0 | 0 |
| mcp-statcan | 12 | 2 | 1 | 0 |
| Pipeworx (StatCan and Bank of Canada servers) | 12 | 2 | 1 | 0 |
| No tools | 2 | 0 | 13 | 0 |

**What it shows:** on core Statistics Canada and Bank of Canada questions the leading
servers are tied within one answer, and no server invented a figure. With 15 questions
and one run per arm, a one-answer gap is not a meaningful difference. The test asks
nothing outside StatCan WDS tables and Bank of Canada Valet series, so it cannot show
coverage of other sources; a larger second version is planned for that.

- **M-15 (the census trap) decides the top row.** MapleStats, arose26 and mcp-canada did
  the mixed 2021/2026 calculation first and flagged it after (partial). OpenMCP and
  CanData-MCP did not compute it and flagged the mismatch (correct under the key), but
  only because a lookup failed (a timeout; a census table with no vector ID), not by
  choice. No server fetched the survey's own count of unemployed people.
- Pipeworx gave not seasonally adjusted earnings from another table (M-10), and its
  connection dropped on M-04 and asked to re-authenticate; a single retry of M-04
  (`runs/retries/`) answered correctly, but the score keeps the official run.
- mcp-statcan gave the customs-basis trade balance (M-09) and declined the October 30
  exchange rate because the StatCan table it read stopped at October 29 (M-11).
- MapleStats got M-06 (2025 inflation) right by averaging the monthly CPI itself; arose26
  and OpenMCP read the published annual-average table, the cleaner method.
- CanData-MCP answered 3 of 15 on CanData's own GTA benchmark in October 2026; the version
  run here (their repository on 2026-11-02) has clearly improved since.
- The no-tools arm's 93% table citations are tables named from memory, not checked.
- Seventeen automatic grades were wrong and are re-graded by hand; the reasons are in
  `overrides.json`.

## Version 2 (November 2026)

v1 is fifteen questions on StatCan tables and Bank of Canada series only, run once per
server: a one-answer gap is noise, and it cannot show coverage of other sources. v2 is
built to answer both:

- **48 questions in two halves.** *Core* (24): Statistics Canada's regular data tables
  and Bank of Canada Valet series, where most Canadian data servers compete. *Beyond*
  (24): the 2021 Census of Population, Environment and Climate Change Canada (climate
  stations, river flow), the World Bank, BIS, Health Canada's Drug Product Database and
  IRCC's Express Entry rounds. Results are reported for each half, so breadth shows
  without being the whole score.
- **Every question asked three times** (`run --repeat 3`), so the report gives the mean,
  the worst and best run, and how consistently a server answers the same question.
- **Citation meta-metrics** for both versions: every cited StatCan vector or table and
  Bank of Canada series is looked up (`grade --verify`, cached in `citation_checks.json`)
  for invented IDs, IDs cited beside the wrong table, and IDs that actually hold a figure
  the answer states (precision, traceability).
- Traps in both halves: unreleased periods (October 2026 CPI, Q3 2026 GDP, a 2025 World
  Bank value, an Express Entry round not yet held), a cancelled drug, a closed weather
  station, an annual rate presented as a monthly count, and a 2026 figure asked of the
  2021 Census.

The key is `maple_test_v2.json`, built by `build_key_v2.py` (core) and `key_v2_beyond.py`
(beyond, from `sources_v2_a.py` and `sources_v2_b.py`); every value is read from the
publisher's own API with httpx, never through MapleStats.

```bash
uv run python -m tests.maple_test.build_key_v2 --check
uv run python -m tests.maple_test run --version v2 --repeat 3 --arm maplestats
uv run python -m tests.maple_test grade --version v2 --verify
```

After the first runs, five *analyst* questions were added (A-01 to A-05), from an
analyst's working week: child poverty for a province (the annual Canadian Income Survey
has it), provincial public administration wages (only SEPH has NAICS 912; correct only
when the answer uses SEPH), "average income" (the median belongs beside it), median
household income (a household is a Census unit; the income survey counts economic
families), and the poverty rate of people with disabilities in Alberta (not published:
11-10-0090 is Canada only). They are graded as their own group, so the 48-question
halves stay comparable.

## Version 2 results, 2026-11-03

Eleven arms, every question asked three times with `claude-sonnet-5-5`; the MapleStats arm
ran a frozen checkout (commit 298692b). Mean correct answers per run:

| Arm | Total (53) | Core (24) | Beyond (24) | Analyst (5) | False claims | Cost per question (USD) |
| :-- | --: | --: | --: | --: | --: | --: |
| **MapleStats** | **49.7** | 22.7 | **23.3** | 3.7 | **0** | 0.116 |
| Pipeworx (StatCan and Bank of Canada servers) | 42 | 22.7 | 16.7 | 2.7 | 7 | 0.074 |
| OpenMCP | 37.7 | 22 | 12 | 3.7 | 4 | 0.053 |
| mcp-canada | 33 | 22 | 9.3 | 1.7 | 7 | 0.075 |
| mcp-statcan | 33 | 22 | 7 | 4 | 6 | 0.034 |
| statcan-mcp and bank-of-canada-mcp (Kole Harvey; arm `arose26`) | 33 | 22.7 | 7 | 3.3 | 6 | 0.022 |
| OpenCanadaPublicDataMCP (nine federal servers) | 29 | 21.3 | 6 | 1.7 | 3 | 0.037 |
| canada-data-agent | 28.7 | 20.7 | 4 | 4 | 5 | 0.026 |
| CanData-MCP | 27.3 | 20.7 | 4 | 2.7 | 6 | 0.032 |
| statcan2 | 19.3 | 8.7 | 8.3 | 2.3 | 8 | 0.059 |
| No data tool | 6 | 2.3 | 2.7 | 1 | 5 | 0.013 |

False claims are counted over all three runs (a statement about the data that is
verifiably false, such as "Statistics Canada publishes this by province"). No arm cited a
StatCan vector or table that does not exist, except mcp-canada once. Full tables,
citation precision and per-question outcomes: [`results_v2.md`](results_v2.md).

What it shows:

- **On Statistics Canada's regular tables the servers are close.** Every tool-using arm
  but statcan2 scores 20.7 to 22.7 of 24. v1's finding holds: on core questions the
  leading servers are tied.
- **The difference is everything else.** On the Census, ECCC, World Bank, BIS, Health
  Canada and IRCC questions MapleStats answers 23.3 of 24; the next best is Pipeworx at
  16.7, and most arms 4 to 9.
- **The analyst traps split the field.** Household income was the hardest: every arm,
  MapleStats included, gave the income survey's economic-family median as household
  income. MapleStats with the caveats added after these questions (`maplestats-current`,
  analyst questions only) scores 4.7 of 5.
- **MapleStats costs the most per question** (USD 0.116 against 0.013 to 0.075): its
  results carry more text. The payload cut made after these runs (about 45% fewer
  characters for a search, data and plan sequence) is not in these figures.

How it was graded: the regex grader first, then a blind hand review of the 346 answers it
marked hallucinated or partial, or abstained on refusal and flag questions. The reviewer
saw each answer beside the key without the arm's name and graded all answers to a
question by one rule; every re-grade is in `overrides_v2.json` with its reason. The
review changed outcomes for every arm, in both directions. It also fixed the key: X-21 and
X-22 required a second value the question did not ask for (now reference values).

Notes on the arms:

- statcan2 serves its own copy of StatCan data, which ended in August 2026, so it declined
  most September questions.
- OpenCanadaPublicDataMCP's servers do not start on a fresh install (their pyproject
  allows mcp 2.x, which removed the FastMCP import they use); they were run with
  `mcp[cli]<2`.
- canada-data-agent caches StatCan responses in PostgreSQL; a local database with its
  `http_cache` table was created, and its code was not changed.
- OpenMCP's first run stopped at the two-hour job limit after 72 answers; the missing
  answers were asked again with the same settings and recorded with their pass numbers.
- With no tools, the model often wrote out tool calls that never ran; those count as
  declined.

Third-party code was run from local clones or published packages outside this repository
and is credited here, not copied: OpenMCP (opendatafyi), CanData-MCP (neobenjax,
Apache 2.0), mcp-canada (ReyemTech, MIT), mcp-statcan (Aryan Jhaveri), Pipeworx, Kole
Harvey's statcan-mcp and bank-of-canada-mcp, statcan2 (hemaaanth), canada-data-agent
(gcode33) and OpenCanadaPublicDataMCP (MIT).

## Shelf life

Two questions depend on today's calendar: M-13 holds until StatCan publishes Q4 2026 GDP
(about late February 2027), and `build_key` refuses to rebuild once it has. Values can be
revised (population and wages especially); `--check` reports any change, and a changed
key means earlier runs are graded against the new figures only after a person reviews them.

Built 2026-11-02 by MapleStats, credits to CanData (neobenjax/Canadian-Open-Data-Agentic-Platform)
for the benchmark design this follows.
