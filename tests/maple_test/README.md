# The Maple Test

Fifteen questions on Canadian economic and social statistics, with an answer key read
from the publishers' own APIs, for measuring how often an AI with a data tool gets the
number, the source and the call right.

It exists because MapleStats' first public result, 93.3% correct on CanData's GTA housing
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

### On every pull request and on a schedule

A run needs a model and the live sources, so two cheaper checks stand in for it:

- **Replayed tool exchanges** (offline, in every `uv run pytest`). For ten questions
  (M-01, M-07, M-09, M-11, M-12, M-14, C-01, C-06, C-19, C-22), [`replay/`](replay/) holds
  the tool call that answers it, as a model makes it through `call_tool`, the HTTP the
  server exchanged with StatCan or the Bank of Canada, and the result.
  `tests/test_maple_test_replay.py` runs those calls against the checkout with the recorded
  HTTP served locally (no source, no model) and fails if the result changed (a value, a
  citation, a caveat, the shape), if it no longer holds the figures the answer key cites
  (or holds one a refusal question says is unpublished), or if the server asks a source for
  something that was not recorded. When a change is meant to alter these results, re-record
  and explain the fixture diff in the pull request:

  ```bash
  uv run python -m tests.maple_test.replay record   # live; refuses if a result misses the key
  ```

  Re-record also after rebuilding a key these questions use. The HTTP bodies are in
  `replay/http.json.gz` (about 100 KB; StatCan's code sets and cube metadata are most of it).
- **[`maple-test.yml`](../../.github/workflows/maple-test.yml)** checks both keys against
  the sources every Thursday (`smoke.yml` does on Mondays). Its benchmark job asks the 15 v1
  questions through MapleStats and grades them; it calls a paid API (about USD 1 to 2 a
  run), so it runs only when started by hand with `benchmark` ticked, and needs an
  `ANTHROPIC_API_KEY` repository secret.

`run` asks each question in an empty folder through headless Claude Code with built-in
tools off and `ENABLE_TOOL_SEARCH=false`, the setup CanData used, so the two benchmarks'
scores are read the same way. `--server-dir` serves a MapleStats checkout other than this
one (a frozen copy of `main`, for a fair before and after).

The grader reads numbers and phrases from the text, so a correct answer worded oddly can
be missed: read every answer, not only the ones it did not mark `correct` (v2's review found
answers wrongly passed too), and record a re-grade with its reason in `overrides.json`
(`{"<arm>/<question id>[#<repeat>]": {"outcome": ..., "reason": ..., "false_claim": ..., "referral": ...}}`).

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
- CanData-MCP answered 20.0% correctly on CanData's own GTA benchmark in October 2026; the version
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
  without being the whole score. The beyond sources were chosen from what MapleStats
  covers; most other servers do not claim them, so that half measures coverage as much
  as accuracy.
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
with SEPH's NAICS 912 figure), "average income" (the median belongs beside it), median
household income (a household is a Census unit, so the Census median is correct; the income
survey's economic-family median alone is partial), and the poverty rate of people with disabilities in Alberta (not published:
11-10-0090 is Canada only). They are graded as their own group, so the 48-question
halves stay comparable.

## Version 2 results, 2026-11-03 (re-graded)

Eleven arms, every question asked three times with `claude-sonnet-5-5`; the MapleStats arm
ran a frozen checkout (commit 298692b). Mean correct answers per run, by half first:

| Arm | Core (24) | Beyond (24) | Analyst (5) | Total (53) | Worst–best | False claims | Referrals | USD per question | Sources it claims |
| :-- | --: | --: | --: | --: | --: | --: | --: | --: | :-- |
| MapleStats | 22.7 | 22.7 | 3.3 | 48.7 | 48–49 | 0 | 0 | 0.116 | All six beyond publishers, StatCan, BoC |
| Pipeworx (StatCan and Bank of Canada servers) | 22.7 | 17.3 | 2.7 | 42.7 | 41–44 | 4 | 18 | 0.074¹ | StatCan, BoC (its gateway also reaches other sources) |
| OpenMCP | 22 | 11 | 3 | 36 | 29–41 | 6 | 16 | 0.053 | StatCan, BoC, open.canada.ca catalogue |
| mcp-canada | 21.3 | 9 | 1 | 31.3 | 28–34 | 2 | 21 | 0.075 | StatCan, BoC, Canadian open-data portals |
| mcp-statcan | 21.7 | 4.3 | 4 | 30 | 29–31 | 1 | 60 | 0.034 | StatCan |
| statcan-mcp and bank-of-canada-mcp (Kole Harvey; arm `arose26`) | 22 | 4 | 3.3 | 29.3 | 28–31 | 1 | 57 | 0.022 | StatCan, BoC |
| OpenCanadaPublicDataMCP (nine federal servers) | 21 | 4.3 | 1.7 | 27 | 25–29 | 7 | 33 | 0.037 | StatCan, BoC, Census, ECCC climate and hydrometric, Health Canada drugs |
| canada-data-agent | 19.3 | 2 | 4 | 25.3 | 25–26 | 6 | 63 | 0.026 | StatCan |
| CanData-MCP | 20.7 | 1.7 | 2.7 | 25 | 23–27 | 0 | 57 | 0.032 | StatCan, BoC |
| statcan2 | 4.7 | 4.3 | 2.3 | 11.3 | 11–12 | 6 | 66 | 0.059 | Its own copy of StatCan tables (to August 2026) |
| No data tool | 2 | 2 | 0 | 4 | 4 | 10 | 56 | 0.013 | None |

¹ Pipeworx's `ask_pipeworx` tools (used in 92 of its 159 answers) run a model on Pipeworx's
side; that cost is not in `total_cost_usd`, so its cost per question is understated.

**Read the beyond half with care.** Its sources (the 2021 Census, ECCC, the World Bank, BIS,
Health Canada's Drug Product Database, IRCC's Express Entry rounds) were chosen from what
MapleStats covers, and most other arms do not claim them (last column). A low beyond score
for a StatCan-only server measures scope, not quality; the core half is where the servers
compete on the same sources. **False claims** are statements about the data that are
verifiably false (a figure said to be published or not published when the opposite is true,
a wrong unit, basis or coverage presented as fact), counted over all three runs.
**Referrals** are answers that gave no figure and sent the user to another publisher's page,
for a source the arm does not claim; they are counted apart, not as false claims. No arm
cited a StatCan vector or table that does not exist, except mcp-canada once. Full tables,
citation precision and per-question outcomes: [`results_v2.md`](results_v2.md).

What it shows:

- **On Statistics Canada's regular tables the servers are close.** Every tool-using arm but
  statcan2 answers 80.6% to 94.4% of the core questions correctly; v1's finding holds.
- **Beyond StatCan and the Bank of Canada, coverage decides.** MapleStats answers 94.4% of
  the beyond questions correctly, Pipeworx 72.2%, OpenMCP 45.8%, the others 6.9% to 37.5%. Most of that gap is that the other
  servers do not cover those publishers.
- **The analyst traps split the field,** but five questions is a small base: 20.0% to 80.0%
  across the tool-using arms, MapleStats 66.7%.
- **Cost per question rewards declining.** An answer that declines in one tool call is cheap;
  the cheapest arms are the ones that answered least. MapleStats cost the most (USD 0.116),
  because its results carried more text.

### MapleStats after these runs (in-sample; not comparable)

After the runs, MapleStats was changed with these questions in view: caveats written for
C-14 (trade basis), C-16 (permits) and the analyst questions after seeing the answers
(commits 5d15f59, 605dfcd, 5a31394), smaller results, metadata notes and `check_answer`. The
rule at the top of this file says no fix may be tuned on these questions without a new set to
check it, so these rows are **in-sample**: they are not comparable with the other arms, and
they do not show that accuracy rose in general. Measuring that needs a fresh question set.

| Run | Core (24) | Beyond (24) | Analyst (5) | Total (53) | USD per question |
| :-- | --: | --: | --: | --: | --: |
| MapleStats as tested above (298692b) | 22.7 | 22.7 | 3.3 | 48.7 | 0.116 |
| MapleStats as merged (`maplestats_after`, 70dfe0d), in-sample | 24 | 23.3 | 5 | 52.3 | 0.074 |
| MapleStats with the analyst caveats (`maplestats-current`, analyst only), in-sample | – | – | 5 | – | 0.175 |

The gains are on C-14, C-16, A-02, A-03 and A-04, the questions the caveats were written
for, and on X-04. The cost comparison is valid, since cost does not depend on knowing the
answers: on the 48 core and beyond questions, cost per question fell from USD 0.107 to 0.069
(36%), with about half a tool call more per question (4.4 to 4.9) and answers two seconds
faster. The other arms were not re-run.

### How it was graded

The regex grader first, then a review of **every** answer in the v2 runs (1,923), one
question at a time, with the arm's name hidden and the answers shuffled. Each question has
one written rule applied to every arm; the rules and each re-grade with its reason are in
`overrides_v2.json` (`"<arm>/<question id>#<repeat>"`, with `outcome`, `reason`,
`false_claim` as text, and `referral`). Blinding was imperfect: many answers name their own
scope ("my tools only reach Statistics Canada"), which reveals the kind of arm.

The review changed 280 grades and fixed the key and the grader:

- **Questions keyed to one reading.** X-12 does not name the BIS, so each country's own
  series (Statistics Canada's 14.68%, the Federal Reserve's 11.32%), labelled, with the right
  call, is correct. A-04: the Census household median ($96,000, income 2020) answers the
  question as asked; the income survey's economic-family median alone is partial. C-03,
  C-11, C-12 and X-24 required values the question did not ask for; those are now reference
  values, as X-21 and X-22 already were.
- **Flag questions need the figure.** Where the question asks for a figure (C-24, X-04, X-24,
  A-02) a flag alone is partial, and A-02 is correct only with SEPH's NAICS 912 figure (the
  latest month or the 2025 annual average); naming SEPH without it is abstained. X-04's flag
  no longer matches a dropped tool connection ("connection closed").
- **Grader bugs.** Numbers separated by ", " were read as one ("July 1, 2026, 399,133"), and
  a status or a refusal word listed among possibilities ("marketed, cancelled or dormant")
  passed X-15 and X-16; both are fixed or re-graded.
- **One rule per question.** Examples: a declined answer that offered the previous month,
  labelled, is abstained everywhere (it was sometimes graded correct because the old month
  fell inside the tolerance); a figure recalled from memory and flagged as unverified is graded
  on its value; unexecuted tool-call text (no-tools arm) is abstained.

The no-tools arm often wrote out tool calls that never ran; those count as declined.

**Which way the review moved each arm.** The grader keeps its own outcome beside every
re-grade, and `results_v2.md` ends with the count. The review took correct answers away
from nine arms (statcan2 19, canada-data-agent 10, mcp-statcan 9, arose26 6, CanData-MCP 6,
OpenCanadaPublicDataMCP 4, mcp-canada 3, OpenMCP 2, no tools 2) and gave some to Pipeworx (5), mcp-canada (3),
CanData-MCP (3) and OpenCanadaPublicDataMCP (2). MapleStats gained and lost none: its 8
re-grades all raised a grade, none of them to correct. The answers that lost a correct grade had
passed on the grader bugs above (a status named only among possibilities, X-15 and X-16),
or gave the previous month in place of the one asked (statcan2's copy of StatCan data ends
in August), or the Bank Rate before the October 29 increase (C-19). The same rules applied
to MapleStats' answers; none of them fell into those patterns.

### Citation traceability (corrected 2026-11-04)

The first report gave MapleStats the lowest traceability of the tool-using arms (48%,
against 53–68%). Two problems in the checker caused most of the gap, not the answers:

- **Scaled series.** WDS stores many series in thousands or millions, so "21,104,800
  employed" never matched v2062811's stored 21,104.8. The checker now reads each vector's
  scalar factor (`scale` in `citation_checks.json`) and accepts the scaled value too.
  Every arm that writes figures in full units was undercounted.
- **IDs that are not checked.** Only StatCan vectors and Bank of Canada series are looked
  up. An answer on ECCC, the World Bank or BIS cites IDs the checker cannot read, so it
  counted as untraceable: MapleStats' 63 beyond answers with figures were all in that
  column, while StatCan-only arms answered fewer of those questions. The report now adds
  **Checked**, the same share among answers that cite a StatCan vector or Valet series.

On checked IDs MapleStats is at 94% (`maplestats_after` 96%), within the 90–98% of the
other tool-using arms, and its precision (94%) is among the highest. No outcome changed.
Checking the other publishers' IDs (ECCC station and climate IDs, World Bank indicator
codes, BIS series keys) would make the first share comparable too; it is not built yet.

### Setup and infrastructure

- statcan2 serves its own copy of StatCan data, which ended in August 2026 (some tables in
  July), so it declined most September questions.
- OpenCanadaPublicDataMCP's servers do not start on a fresh install (their pyproject allows
  mcp 2.x, which removed the FastMCP import they use); they were run with `mcp[cli]<2`.
- canada-data-agent caches StatCan responses in PostgreSQL; a local database with its
  `http_cache` table was created, and its code was not changed.
- OpenMCP's first run stopped at the two-hour job limit after 72 answers; the missing answers
  were asked again with the same settings and recorded with their pass numbers.
- Pipeworx's connection dropped or asked to re-authenticate in 2 answers (A-02, A-04); they
  stand as answered. mcp-canada (2), OpenMCP (3) and the no-tools arm (7) had run errors
  (timeouts), graded abstained.

### Versions

| Arm | What ran |
| :-- | :-- |
| MapleStats | Frozen checkout 298692b; `maplestats_after` 70dfe0d |
| OpenMCP | Local clone of opendatafyi/openmcp at 0756934 |
| CanData-MCP | Local clone of the CanData monorepo at 0eded54 |
| canada-data-agent | Local clone of gcode33/canada-data-agent at 6478ec0 |
| OpenCanadaPublicDataMCP | Local clone at c0a9b49, with `mcp[cli]<2` |
| Kole Harvey's statcan-mcp and bank-of-canada-mcp | `npx -y` (latest npm release at run time) |
| mcp-canada | `uvx mcp-canada` (latest PyPI release at run time) |
| mcp-statcan, Pipeworx, statcan2 | Hosted endpoints, as served on 2026-11-03 (no version exposed) |

The npx and uvx arms used whatever release was latest on 2026-11-03; a re-run may get a
different version.

Third-party code was run from local clones or published packages outside this repository
and is credited here, not copied: OpenMCP (opendatafyi), CanData-MCP (neobenjax,
Apache 2.0), mcp-canada (ReyemTech, MIT), mcp-statcan (Aryan Jhaveri), Pipeworx, Kole
Harvey's statcan-mcp and bank-of-canada-mcp, statcan2 (hemaaanth), canada-data-agent
(gcode33) and OpenCanadaPublicDataMCP (MIT).

## Release questions (added 2026-11-04)

The fixes made after the v2 runs were checked only on the questions they were written for.
The release group (R-01 to R-08) is the fresh set the rule at the top asks for, written and
keyed before MapleStats or any other server was asked them. They ask what analysts ask
before the figures: when a release comes out.

| ID | Question | Key | Trap |
| :-- | :-- | :-- | :-- |
| R-01 | Alberta's 2025 GDP in the provincial and territorial economic accounts (PTEA) | 2026-11-05 | GDP by industry for 2025 came out May 1: another release |
| R-02 | Provincial supply and use tables (SUT): 2022 released, 2023 due | 2025-11-06, 2026-11-05 | The SUT lag the PTEA by two years |
| R-03 | 2025 provincial GDP by industry: when, and in which table | 2026-05-01, 36-10-0711 | 36-10-0402, the usual table, stops at 2024 |
| R-04 | Labour Force Survey, October 2026 | 2026-11-06 | |
| R-05 | Monthly Survey of Manufacturing, September 2026 | 2026-11-13 | |
| R-06 | 2026 PTEA release date | Not announced (refusal) | A date given anyway is invented |
| R-07 | CPI, September 2026 (past) | 2026-10-19 | |
| R-08 | Building permits, September 2026 | 2026-11-12 | |

`key_v2_release.py` reads the dates from StatCan's release archive JSON, which lists past
releases and the major ones ahead, and from the two-week calendar page (cal2), which also
has the PTEA and SUT; table end dates come from WDS. It never goes through MapleStats.
Answers are graded on the dates they state (`eval_type: "date"`; a date written without a
year counts); R-03 also needs the table.

```bash
uv run python -m tests.maple_test.key_v2_release      # rebuild only the release group
uv run python -m tests.maple_test run --version v2 --repeat 3 --arm maplestats \
    --label maplestats-release --only R-01 R-02 R-03 R-04 R-05 R-06 R-07 R-08
```

### Results, 2026-11-05 (MapleStats only)

MapleStats as on `main` before the release-history change (6d1ff7a, served from a frozen
checkout), three passes, run late on 2026-11-04 Toronto time (the prompt's date, in UTC,
was 2026-11-05): **91.7% correct**, 95.8% of the 24 answers right on substance.

- R-01 to R-05, R-07 and R-08: correct in every pass. The calendar tools found the PTEA,
  the SUT (two-week page) and the monthly indicators; R-03 named 36-10-0711 every time.
- R-06 (2026 PTEA, no date set): one correct ("a 2026 edition doesn't exist yet"); one gave
  the 2025 accounts' date as the answer, labelled 2025, without saying no 2026 date exists
  (abstained; the grader had passed it on "is not in the key-indicators calendar"); one was
  a run error. That gap is what the release history added after this run addresses:
  `not_scheduled` now says no date is announced, when the release came out before, and an
  estimate called one. The other arms were not run.
- Infrastructure: the run stopped after 16 answers (a Windows temp-folder error), so pass 3
  was run separately and two failed answers (the MCP server did not start; R-03 hung) were
  asked again with the same settings, merged under their pass numbers; the failed answers
  are kept in `runs_v2/errors/`. One re-asked answer (R-06#1) failed the same way and is
  graded abstained.

## Costs

`cost_usd` is what headless Claude Code reports for each answer (`total_cost_usd`), at
API prices for `claude-sonnet-5-5`; on a Claude subscription it is an equivalent, not a
bill. v1 and the CanData GTA runs did not record it.

- **v2 as published, all arms:** USD 100.19 for 1,923 answers (the 11 arms, three runs, plus
  `maplestats_after` and `maplestats-current`). MapleStats' arm cost the most (USD 18.49 for
  159 answers, 0.116 a question), then mcp-canada (11.93) and Pipeworx (11.71, understated:
  its `ask_pipeworx` tools run a model on Pipeworx's side). The cheapest arms answered least.
- **Why MapleStats cost more:** cost follows the input tokens, and its tool results carried
  more text (table metadata, notes, citations). The changes after the runs cut it to USD
  0.074 a question (`maplestats_after`), with half a tool call more per question.
- **Running the release group:** 24 answers (8 questions, three runs) cost USD 1.06 for
  MapleStats (USD 0.044 a question). At v2 costs, all eleven arms would be about USD 13; the
  local-clone arms need `--alts` set up as described in `run.py`.

### Cost check after the 2026-11-04 changes

Two changes, chosen because they cannot change which tool is found or what it returns:
`search_tools` results lost each tool's title and a read-only tool's annotations (about 12%
smaller), and the instructions say plainly that found tools run through `call_tool` (in the
v2 runs, a third of answers had tried to call one by its own name). One pass of the 48 core
and beyond questions (`maplestats-cost`), against the earlier runs of the same questions:

| Run | Answers | USD per question | Median | Tool calls | Failed direct calls per question |
| :-- | --: | --: | --: | --: | --: |
| As tested (298692b) | 144 | 0.107 | 0.066 | 4.4 | 0.24 |
| As merged (70dfe0d) | 144 | 0.069 | 0.048 | 4.9 | 0.37 |
| With these changes | 48 | 0.057 | 0.040 | 4.0 | 0.08 |

Cost per question fell 18% and failed direct calls 78% against the merged version; one pass
of 48 is a small sample, so read it as a direction. Accuracy held: 95.8% of the 48 correct (100.0% of
the core), against 98.6% for the merged version. The two not correct are a run error (X-22, the MCP server
did not start) and X-04 flagged without the replacement station's figure (partial, as in one
earlier pass). C-14 gave August's exports as StatCan revised them on 2026-11-04, after the key
was built; it is re-graded correct with that reason. These questions shaped earlier fixes, so
accuracy here is in-sample; cost is not. Answers took longer (28.7 seconds) because two runs
shared the machine.

## Full run on every server, 2026-11-05 to 2026-11-08

The whole v2 set (61 questions, three passes) on every arm, with the label `<arm>-1105`,
graded with `--verify` and reviewed by hand as the Nov. 3 runs were. Mean correct answers per
run, the other arms only (MapleStats' row is below the table):

| Arm | Core (24) | Beyond (24) | Analyst (5) | Total (53) | Release (8) | False claims | Referrals | USD per question |
| :-- | --: | --: | --: | --: | --: | --: | --: | --: |
| Pipeworx (Nov. 3; not re-run) | 22.7 | 17.3 | 2.7 | 42.7 | – | 4 | 18 | 0.074 |
| OpenMCP (Nov. 3; not re-run) | 22 | 11 | 3 | 36 | – | 6 | 16 | 0.053 |
| arose26 | 22.3 | 5 | 3.7 | 31 | 0.7 | 3 | 77 | 0.018 |
| mcp-canada | 20 | 9.7 | 1.3 | 31 | 2 | 3 | 43 | 0.061 |
| mcp-statcan | 22.7 | 4.7 | 3.3 | 30.7 | 3 | 8 | 58 | 0.020 |
| CanData-MCP | 21.7 | 1.3 | 2.7 | 25.7 | 2.7 | 3 | 36 | 0.030 |
| OpenCanadaPublicDataMCP | 20.3 | 3.3 | 1.3 | 25 | 0.7 | 9 | 49 | 0.031 |
| canada-data-agent | 19.3 | 2 | 2.7 | 24 | 0.3 | 7 | 81 | 0.022 |
| statcan2 | 4.3 | 4 | 3.3 | 11.7 | 1 | 7 | 74 | 0.049 |
| No data tool | 2 | 2 | 0 | 4 | 1 | 16 | 152 | 0.009 |

**MapleStats is in-sample here, not comparable.** It ran a frozen checkout of be91871 (as
merged in #146), which contains the changes made after the Nov. 3 runs with these questions in
view (5d15f59, 605dfcd, 5a31394; see "MapleStats after these runs"). Its 1105 score, 98.1% of the 53
correct (core 98.6%, beyond 97.2%, analyst 100.0%; 79.2% of the 8 release questions; 95.6% of all 61; no false
claims or referrals; USD 0.060 per question), belongs beside `maplestats_after` (98.7%), not in
the table above. MapleStats' comparable score stays 91.8%, from Nov. 3, before those changes.

As shares of the 53 questions answered correctly, the re-run arms score: arose26 58.5%,
mcp-canada 58.5%, mcp-statcan 57.9%, CanData-MCP 48.4%, OpenCanadaPublicDataMCP 47.2%,
canada-data-agent 45.3%, statcan2 22.0% and no data tool 7.5%, beside Pipeworx 80.5% and OpenMCP
67.9% (Nov. 3) and MapleStats 91.8% (Nov. 3, comparable). On the core questions they range from
80.6% to 94.4% (statcan2 18.1%), on the 8 release questions from 4.2% to 37.5%. Each share is the
correct answers over the three runs divided by three times the number of questions
(`results_v2.json`).

False claims and referrals count all 61 questions over three runs, so the 1105 arms are not
comparable with the Nov. 3 counts, which cover 53. Per-arm details are in
[`results_v2.md`](results_v2.md) under each `-1105` label.

**What differs from the Nov. 3 runs.**

- **Pipeworx was not re-run.** Pipeworx enforced its advertised 50-calls-a-day anonymous limit
  between Nov. 3 and Nov. 5; a full arm needs about 500, so the Nov. 3 score stands. Both
  attempts (`runs_v2/paused/*_pipeworx-1105_*`) were set aside ungraded: most answers there
  were sign-in requests, not answers.
- **OpenMCP was not completed.** On this laptop its server took up to 3.3 GB and minutes of
  CPU per tool call, and 40 of its first 103 answers hit the 10-minute cap (3 of 159 on Nov.
  3). That measures the machine more than the server, so its Nov. 3 score stands and the
  partial file is in `runs_v2/paused/`.
- **Run errors were asked again** with the same settings and recorded under their pass
  numbers; the failed answers are in `runs_v2/errors/`. MapleStats had 21 (its server missed
  the CLI's start-up wait, before run.py set `MCP_TIMEOUT`); mcp-canada had 166, all from one
  stretch when the session running the benchmark was closed by mistake. No arm has a run
  error left.
- **The key changed on 2026-11-07:** five Labour Force Survey release dates were corrected;
  no values changed. StatCan also revised August's exports to the US on 2026-11-04 (C-14,
  now $54,771.6 million). The eight Nov. 3 answers that gave the earlier $54,346.5 million
  are kept correct, with that reason in the overrides file.
- **Versions:** mcp-canada was at 0.13.0. statcan2's copy of StatCan data still ends in
  August 2026, so it declined most September questions again.
- The new runs were on Nov. 7 and 8, but every question names its period, so the answers
  are graded against the same figures.

**The review.** All 1,647 new answers from nine arms were read, one question at a time, with
the arm's name hidden and the answers shuffled, under the Nov. 3 rules for each question
(`overrides_v2.json`, keys `<arm>-1105/...`). One rule was settled the same way across all
questions: a referral is an answer with no figure that says it cannot reach the publisher at
all and points to the publisher's page. A data copy that ends early, an empty lookup or a tool
error is not a referral. One new case, an answer that names the wrong province first and then
corrects itself (C-01, four answers from three arms), was graded partial. The review took
correct answers away from nine arms (statcan2 17, no tools 11, arose26 8, canada-data-agent
7, mcp-statcan 7, CanData-MCP 6, mcp-canada 3, OpenCanadaPublicDataMCP 3, MapleStats 1) and
gave a few back (OpenCanadaPublicDataMCP 2, mcp-canada 2, CanData-MCP 1, mcp-statcan 1). Most
lost grades were a previous month offered in place of the one asked, or a drug status named
only among possibilities (X-15, X-16), as on Nov. 3. MapleStats' lost grade is R-06 in one
pass: it gave the 2025 accounts' release date without saying none is set for 2026.

## Shelf life

Two questions depend on today's calendar: M-13 holds until StatCan publishes Q4 2026 GDP
(about late February 2027), and `build_key` refuses to rebuild once it has. Values can be
revised (population and wages especially); `--check` reports any change, and a changed
key means earlier runs are graded against the new figures only after a person reviews them.

Built 2026-11-02 by MapleStats, credits to CanData (neobenjax/Canadian-Open-Data-Agentic-Platform)
for the benchmark design this follows.
