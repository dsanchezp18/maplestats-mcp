# CanData's GTA housing benchmark, 2026-11-02

MapleStats run through CanData's public 15-question ground-truth benchmark on Greater
Toronto housing and economic data, before and after the fixes it led to.

**Credit.** The benchmark, its questions and answer key, the grading harness and the
other arms' results are the work of the CanData team (Canadian Open Data Agentic
Platform, https://github.com/neobenjax/Canadian-Open-Data-Agentic-Platform, Apache 2.0):
`collaboration/benchmarks/build_ground_truth.py`, `gta_ground_truth_v1.json`,
`run_baseline.py` and `baseline/`. None of their code or data is copied into this
repository. The comparison arms (mcp-statcan, CanData-MCP, no tools) are their runs of
2026-10-22, read from their results; we did not rerun them.

## Result

Same 15 questions, same system prompt, same agent loop (headless Claude Code, built-in
tools off), same model (`claude-sonnet-5-5`), same `ENABLE_TOOL_SEARCH=false`, graded by
their `run_baseline.py grade`.

| Arm | Run date | Correct | Partial | Abstained | Hallucinated | False claims | Table citations | Vector citations | Tool calls |
| :-- | :-- | --: | --: | --: | --: | --: | --: | --: | --: |
| no tools (Sonnet / Opus / Haiku) | 2026-10-22 | 3 / 3 / 2 | 0 | 12 | 0 / 0 / 1 | 1 / 1 / 2 | 67-77% | 7% | 0 |
| CanData-MCP | 2026-10-22 | 3 | 0 | 12 | 0 | 0 | 63% | 10% | 4.5 |
| mcp-statcan | 2026-10-22 | 11 | 3 | 1 | 0 | 1 | 70% | 57% | 12.5 |
| MapleStats, before (`16c0de8`) | 2026-11-02 | 10 | 5 | 0 | 0 | 1 | 67% | 53% | 9.8 |
| MapleStats, round 2 (`42967f3`) | 2026-11-02 | 13 | 2 | 0 | 0 | 1 | 90% | 83% | 9.7 |
| **MapleStats, after (`0365c3d`)** | 2026-11-02 | **14** | **1** | 0 | **0** | **0** | **97%** | **90%** | 7.6 |

Citations are the share of the answer key's table and vector IDs the answer names.

### Per question

| Question | mcp-statcan | CanData-MCP | MapleStats before | round 2 | after |
| :-- | :-: | :-: | :-: | :-: | :-: |
| GT-01 two-bedroom rent 2025 | correct | abstained | correct | correct | correct |
| GT-02 vacancy rate 2025 vs 2023 | correct | abstained | correct | correct | correct |
| GT-03 Oshawa vs Toronto rent | abstained | abstained | partial | partial | partial |
| GT-04 highest vacancy of three CMAs | partial | abstained | partial | correct | correct |
| GT-05 housing starts 2025 vs 2024 | correct | abstained | correct | correct | correct |
| GT-06 new home prices Dec to Dec | correct | abstained | correct | correct | correct |
| GT-07 rent share of median income | partial* | abstained | partial* | partial* | correct |
| GT-08 rent growth vs income growth | correct | abstained | correct | correct | correct |
| GT-09 2021 Census income (flag) | correct | correct | correct | correct | correct |
| GT-10 rent inflation vs CPI | correct | abstained | correct | correct | correct |
| GT-11 shelter inflation, Toronto vs Canada | partial* | abstained | partial* | correct | correct |
| GT-12 shelter inflation Aug 2026 | correct | abstained | correct | correct* | correct* |
| GT-13 Bank of Canada rate changes | correct | correct | correct | correct | correct |
| GT-14 Toronto mortgage interest cost (refusal) | correct | abstained | partial* | correct | correct |
| GT-15 rent in 1985 (refusal) | correct | correct | correct* | correct | correct* |

`*` re-graded by hand. Their re-grades are in their `manual_overrides.json`; ours are in
[`candata-gta-benchmark/maplestats_overrides.json`](candata-gta-benchmark/maplestats_overrides.json),
each with its reason. Before our re-grades, the automatic grade was 9 correct and 4
hallucinated (before), 12 and 2 (round 2), 12 and 2 (after). Every one of those
"hallucinated" grades was a pattern miss, not a wrong figure:

- GT-12 (round 2, after): right figures (-0.5% shelter, +2.1% all-items), but "slightly
  lower" rather than a word the grader's pattern accepts ("fell", "declined", "down").
- GT-15 (before): read the old CANSIM number 027-0040 as a figure. (after): quoted the
  real 1992 value ($755, v3823103, checked live) as the nearest published figure, labelled
  as not a 1985 value; the grader counts any dollar figure as an invented 1985 rent.
- GT-07, GT-11, GT-14 (before): wrong concept or method, re-graded partial the same way
  CanData re-graded mcp-statcan's GT-07 and GT-11.

GT-03 stays partial in every run: the answers say Oshawa is $283 (about 14%) cheaper; the
answer key asks for Toronto's 16.1% premium over Oshawa. We left it as graded.

## What each miss showed, and the fix

| Miss | Cause in MapleStats | Fix |
| :-- | :-- | :-- |
| GT-08 "could not confirm whether income is constant dollars"; GT-07 individual vs family income | Data results carried IDs and numbers but no unit label, series title or member names | Every WDS and SDMX series carries `context`: table number, title and page URL, series title, unit ("2024 constant dollars"), scale, frequency, geography, every member label, release time, and notes on reading the unit |
| GT-07 chose individuals' income (11-10-0238) | No income topic in `plan_query`; table 11-10-0190's title has no "median" | Income topic in `plan_query`, leading with 11-10-0190 for family and household income; caveat rule on families vs individuals |
| GT-04 used the six-units-and-over vacancy table | No guidance on the CMHC tables' universes | Caveat rule: 34-10-0130 is the survey's whole universe; 34-10-0127 is apartments of six units and over only |
| GT-01, GT-03 risk of asking rents | Same | Same rule: survey rent is what tenants pay, not an asking or listing rent |
| GT-11, GT-14 averaged months by hand or used December to December | Caveats attached only when the call named the table, never to calls by vector ID | Caveats follow the tables in the result; rule: annual inflation is the change in the published annual average (18-10-0005) |
| GT-14 hedged "may be a limit of my lookup" | A coordinate with no series gave WDS's bare status | The error names each member and says the combination is not published; caveat rule: mortgage interest cost is Canada only; Toronto has six CPI series (checked over every geography and product member) |
| GT-15 said the Toronto series starts in 1987 | An empty date range came back empty, with no hint | Empty windows state the series' own span (values from 1992); the CMHC caveat says series start later than their table |
| Errors in general | Messages said what failed, not what to do | Every failed call ends with a suggested fix |
| Annotations | `call_tool` was not read-only on a local server, because workbooks saved to Downloads | File saving is opt-in (`MAPLE_EXPORT_DIR`); every tool is read-only and idempotent by default |

## Limits

- One run per arm. Run-to-run variation is not measured; the gains on GT-04, GT-07, GT-11
  and GT-14 each rest on one answer.
- The comparison arms ran on 2026-10-22 and ours on 2026-11-02. The data did not change
  in between: on 2026-11-02, all 35 single-period StatCan citations in the answer key (15
  vectors) still had the release times the key records. Their `build_ground_truth.py
  --check` could not run here, because StatCan resets Python urllib's TLS handshake (see
  "http2=True" in AGENTS.md), so the same comparison was made with curl. GT-05's monthly
  range and the Bank of Canada series were not part of it.
- The fixes were made after seeing the questions. Each one is general (a unit label, a
  table's universe, a published-series check), and each caveat is verified against an
  official source, but the benchmark can no longer show how MapleStats does on questions
  it has not seen. A fresh question set is the next test.

## Reproduce

[`candata-gta-benchmark/run_maplestats.py`](candata-gta-benchmark/run_maplestats.py) adds
a MapleStats arm to CanData's harness without editing it; its docstring has the commands.
Our three run files, with every answer in full, are in
[`candata-gta-benchmark/runs/`](candata-gta-benchmark/runs/).
