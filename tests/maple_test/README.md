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

## Shelf life

Two questions depend on today's calendar: M-13 holds until StatCan publishes Q4 2026 GDP
(about late February 2027), and `build_key` refuses to rebuild once it has. Values can be
revised (population and wages especially); `--check` reports any change, and a changed
key means earlier runs are graded against the new figures only after a person reviews them.

Built 2026-11-02 by MapleStats, credits to CanData (neobenjax/Canadian-Open-Data-Agentic-Platform)
for the benchmark design this follows.
