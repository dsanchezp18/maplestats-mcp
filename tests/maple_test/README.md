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

## Shelf life

Two questions depend on today's calendar: M-13 holds until StatCan publishes Q4 2026 GDP
(about late February 2027), and `build_key` refuses to rebuild once it has. Values can be
revised (population and wages especially); `--check` reports any change, and a changed
key means earlier runs are graded against the new figures only after a person reviews them.

Built 2026-11-02 by MapleStats, credits to CanData (neobenjax/Canadian-Open-Data-Agentic-Platform)
for the benchmark design this follows.
