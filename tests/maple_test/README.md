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
bill. v1 and the CanData GTA runs did not record it. Runs from 2026-11-08 on also record
the cached input tokens (`cache_read_tokens`, `cache_creation_tokens`): `input_tokens`
alone counts only the uncached few dozen. `grade` reports tokens in and out per arm and a
cost-per-question table; `python -m tests.maple_test costs --version v2 [runs...]` prints
that table from run files without grading.

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

## Version 3: technical data and documentation (November 2026)

v1 and v2 ask for figures. Before an analyst uses a figure they ask what it is: the unit,
whether it is seasonally adjusted or revised, who is in the survey, what a code means,
which licence a dataset carries and whether its table can be queried. v3 asks 36 of those
questions, on the publishers' documentation and on open-data portals, and is a new,
out-of-sample set for MapleStats.

**The out-of-sample rule.** The questions were written and the key built on 2026-11-08,
before MapleStats or any other server was asked them, and nobody has run MapleStats on
them. T-29 to T-36 were added the same day, once StatCan's WDS and the Ontario and
Alberta catalogues answered this machine again, and were keyed before any server was
asked them too. Every key value is read by `build_key_v3.py`, with httpx, from the publisher's own
API or page, never through MapleStats. The rule at the top of this file applies: a
MapleStats change tuned on these questions makes later MapleStats runs in-sample, and
checking such a change needs another new set.

| ID | Source | Kind | Asks |
| :-- | :-- | :-- | :-- |
| T-01 | StatCan IMDB 3701 | facts | LFS: territories in the national estimates? Exclusions from the target population |
| T-02 | StatCan IMDB 3701, 5200 | facts | Is the LFS mandatory? Is the Canadian Income Survey? |
| T-03 | StatCan IMDB 3701 | facts | LFS monthly sample (households) and reference week |
| T-04 | StatCan IMDB 2301 | refusal | Revision to the unadjusted August 2026 CPI (the unadjusted CPI is never revised) |
| T-05 | StatCan IMDB 2301 | facts | Number of seasonally adjusted national CPI series; years revised each January |
| T-06 | StatCan IMDB 2301 | facts | CPI time base and the month it took effect |
| T-07 | StatCan IMDB 5200 | facts | Where the CIS gets its income data; how variance is estimated |
| T-08 | StatCan RDaaS | facts | NAICS Canada 2022 code for software publishers, and its 2017 code |
| T-09 | StatCan RDaaS | facts | NOC 2021 code for economists and its broad category |
| T-10 | Bank of Canada Valet | facts | What V39079 and V122530 are, and their frequency |
| T-11 | Bank of Canada Valet | facts | Valet codes, frequency and unit of CPI-trim and CPI-median |
| T-12 | Bank of Canada Valet | refusal | The noon USD/CAD rate on October 30, 2026 (noon rates ended in April 2017) |
| T-13 | CMHC | facts | Definition of a housing start |
| T-14 | CMHC | facts | When the Rental Market Survey is run and what it covers |
| T-15 | CMHC | facts | Rental Market Survey reliability code D; minimum responding entities |
| T-16 | CMHC | refusal | Toronto vacancy rate in an April 2026 survey (the survey is October only) |
| T-17 | open.canada.ca | facts | Express Entry monthly dataset: publisher, frequency, formats, DataStore (none) |
| T-18 | open.canada.ca | facts | Express Entry Reports: number of resources, format, frequency |
| T-19 | open.canada.ca | facts | Drug Product Database files: licence, frequency, portal release date |
| T-20 | BC Data Catalogue | facts | Historical fire perimeters: publisher, licence, CSV or DataStore (neither) |
| T-21 | BC Data Catalogue | facts | Popular girl names: publisher, resources, format, last modified |
| T-22 | Données Québec | facts | SAAQ accident reports: property-damage threshold and its start date |
| T-23 | Données Québec | refusal | A 2024 file of SAAQ accident reports (the latest is 2022) |
| T-24 | Données Québec | facts | DataStore value: girls named Alice in 2025; how counts under five are shown |
| T-25 | Toronto | facts | TTC subway delays: owner, refresh rate, type of the 'Min Delay' field (text) |
| T-26 | Toronto | facts | DataStore value: what delay code MUSAN means |
| T-27 | Montréal | facts | Road collisions: are highways included (no); who records collisions |
| T-28 | Montréal | facts | Road collisions DataStore: the severity field; NB_MORTS's type |
| T-29 | StatCan WDS | facts | Unit and scalar factor of v2062811 (employment: persons, thousands) |
| T-30 | StatCan WDS | facts | Which table holds v62305752, and that table's frequency |
| T-31 | StatCan WDS | facts | Is v41690973 (all-items CPI) seasonally adjusted? (no) |
| T-32 | StatCan WDS | facts | Release date of 17-10-0005-01's latest update; frequency; latest reference date |
| T-33 | Ontario | facts | Top baby names (female): ministry, licence, update frequency, resources |
| T-34 | Ontario | facts | Same dataset's DataStore fields and types; how counts under five are handled |
| T-35 | Alberta | facts | Net corporate income tax revenue: ministry, licence, frequency, format; do totals match the annual report (no) |
| T-36 | Alberta | facts | Canada supply and disposition: open data or publication, ministry, frequency, format |

By source: Statistics Canada 13 of 36 (36.1%), the Bank of Canada 3 (8.3%), CMHC 4 (11.1%),
and CKAN portals 16 (44.4%): federal 3 (8.3%), provincial 9 (25.0%), municipal 4 (11.1%).
Four questions (11.1%) have no answer to give (refusals). Results are reported for each
source group (`group` in the key), as v2 reports its halves.

**Grading.** Most answers are text, so v3 adds one grading kind, `facts`: each question
lists the facts an answer must state, one pattern each (`facts`), the ones it cannot do
without (`headline`), and statements the key shows are false (`wrong`). All facts is
correct; half or more with every headline fact is partial; a false statement, or wrong
facts with a code or figure of their own, is hallucinated; a decline with none is
abstained. Refusal questions are graded as in v1 and v2. Every question also carries a
written `grading` rule (what is correct, what is partial, what counts as a referral) for
the hand review, which, as for v2, reads every answer.

**Sources and how the key is read.** StatCan's IMDB survey pages (www23) for survey
documentation, StatCan's RDaaS API for NAICS and NOC, StatCan's WDS
(`getSeriesInfoFromVector`, `getCubeMetadata`, `getCodeSets`) for a series' unit, scalar
factor, table, frequency and release date, Valet series and group metadata,
CMHC's methodology pages, and each portal's CKAN Action API (`package_show`,
`datastore_search`). Documentation answers are read by pattern from the page, so a
reworded passage stops the build with the phrase it could not find. Facts were preferred
to figures so the key holds: licences, codes, definitions, field types. Where a value can
change (Alice's count, which Retraite Québec revises each year; the latest SAAQ year;
resource counts; T-32's release date, which moves when StatCan next updates the table,
about September 2027), `--check` reports it. Because WDS, Ontario and Alberta had blocked
this machine after heavy use, the builder asks them for each fact once, with a pause, and
stops on HTTP 403 or 429 instead of retrying.

```bash
uv run python -m tests.maple_test.build_key_v3 --check     # has any source changed?
uv run python -m tests.maple_test run --version v3 --repeat 3 --arm maplestats
uv run python -m tests.maple_test grade --version v3
uv run pytest tests/test_maple_test_v3.py                 # offline checks of the key
```

Not run yet on any arm.

### v3 results, 2026-11-09: brief and full results, and OpenMCP

Three arms on all 36 v3 questions, three runs each (108 answers per arm), graded and then
reviewed by hand, blind to the arm, under each question's written rule
(`overrides_v3.json`). Percentages are correct answers over 108; partial counts as a miss.

- `maplestats-brief`: the hosted server as users reach it (brief results, the default since
  #203). **MapleStats' comparable v3 score.**
- `maplestats-full`: the same hosted server through a local relay
  ([`relay_full.py`](relay_full.py)) that sets `detail='full'` on every `call_tool`
  request; its log (`relay_logs/`) shows all 873 logged requests carried it.
- `openmcp-1109`: OpenMCP from its local clone, run alone.
- `maplestats-postfix`: the hosted server after fixes chosen from the first runs' misses
  (main c07852e). **Partly in-sample**, so not comparable with OpenMCP the way the brief
  run is.

| Arm | Correct | StatCan (39) | BoC (9) | CMHC (12) | Federal portal (9) | Provincial portals (27) | Municipal portals (12) | USD per question | Seconds | Tokens in / out |
| :-- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| MapleStats, brief | 75.0% | 76.9% | 100% | 75.0% | 0% | 88.9% | 75.0% | 0.063 | 14.8 | 50,639 / 967 |
| MapleStats, full | 63.9% | 66.7% | 88.9% | 75.0% | 22.2% | 55.6% | 75.0% | 0.060 | 15.3 | 47,629 / 911 |
| OpenMCP | 49.1% | 48.7% | 100% | 75.0% | 11.1% | 25.9% | 66.7% | 0.047 | 79.5 | 45,351 / 904 |
| MapleStats after fixes (partly in-sample) | 90.7% | 97.4% | 100% | 91.7% | 100% | 81.5% | 75.0% | 0.048 | 17.3 | 37,380 / 884 |

No arm cited an invented StatCan id. Hallucinated answers: brief 3, full 4, OpenMCP 9,
after fixes 1. Brief results cost about as much as full ones here and answered more
questions correctly; most of the difference is on the provincial portal questions.

On v2 the brief and full arms were also run (183 answers each,
`runs_v2/cost_only/`), for cost: USD 0.056 against 0.060 per question, 13.1 and 13.2
seconds, 50,504 and 52,416 tokens in. MapleStats is in-sample on v2, so those runs were not
reviewed by hand and are left out of `results_v2.md` (the grader alone: 94.5% brief, 96.2%
full). OpenMCP was run on v3 only; its v2 reference stays the Nov. 3 score.

**How the runs were done.**

- **OpenMCP needs DuckDB 1.x.** Its `requirements.txt` leaves `duckdb` unpinned, and with
  DuckDB 2.0.0 its keyword search (`match_bm25` over 81,497 datasets) does not return for a
  query of more than one word (a 3-word query ran for over 25 minutes; 0.1 s with 1.5.6). The
  local clone was given `duckdb==1.5.6`; its code was not changed. The two attempts before
  the pin (half their answers at the 10-minute cap) are in `runs_v3/paused/` and
  `runs_v2/paused/`, and this likely explains the Nov. 8 OpenMCP timeouts too.
- **The relay's first version wrote Windows cp1252,** so a `search_tools` result holding
  "≤" (two CKAN tool descriptions) failed in the full arm. After the fix, the full arm's 45
  answers on the 15 portal questions where it touched CKAN were asked again (old answers in
  `runs_v3/invalidated/`) against a local server at 092ed42, the code the hosted server ran
  for the first runs, since the hosted server had been updated by then. StatCan's WDS was
  refusing this machine (HTTP 403) at the time; those 15 questions read only the portals.
- One answer stopped on the Claude usage limit and was asked again (`runs_v3/errors/`).

**Review rules applied to every arm.** A refusal after a tool error is abstained, not
partial; a fact given only as a possibility does not count; a value from memory flagged as
unverified is graded on its value. Two disputes went the same way: an answer that gave a real
published value from another copy or source, cited as such, is partial, not hallucinated.
On T-05, seven MapleStats answers gave 11 seasonally adjusted CPI series, as table
18-10-0006-01 holds them (checked), against the key's 15 from the CPI's IMDB record. On T-28,
two OpenMCP answers read field types from Données Québec's copy, where every field is text.
On T-15, three answers recalled CMHC's code D as "Fair"; that was memory, and the key, read
from CMHC's page, stands.

## Version 4: one set, fewer reviews, faster runs (November 2026)

A full v2 comparison took hours per arm and a hand review of every answer (1,647 for the
1105 runs). v4 keeps what separates servers and spends a person's time only where the
graders disagree.

### The questions

v4 asks no new questions. `build_key_v4.py` keeps 47 of the 112 asked in v1 to v3 and lists
every one of the 112 as kept or dropped, with the reason:

- **Near-duplicates go.** One question per skill and source: C-09 stands for the CPI
  questions (M-06, C-06, C-07, C-08), C-01 for the LFS rates (M-01, C-02, C-03), X-15 for the
  drug lookups (X-13, X-14), R-04 for the monthly release dates (R-05, R-07, R-08), and so on.
- **Questions that separate no one go.** `item_analysis.py` reads every hand-reviewed grade
  of v1, v2 and v3 (`overrides_v3.json`, #217), and gives each question each comparable
  arm's share of correct answers (`v4/item_analysis.json`). A question every comparable arm
  always got right (M-01, M-03, C-17, C-22, T-04, T-08 to T-11, T-16, T-23, ...) or always
  got wrong (X-04, T-03, T-05, T-07, T-18, T-35) is dropped. The model alone and in-sample
  MapleStats runs are not comparable arms; `maplestats-release` counts on the release
  questions, which it was first to answer.
- **v3 rests on two servers.** Only MapleStats (`maplestats-brief`, `maplestats-full`) and
  OpenMCP ran it, so a v3 ceiling means both got it right every time. The hand review moved
  several: T-04, T-16, T-23 and T-27 became ceilings and were dropped; T-14, T-22 and T-28
  stopped being ceilings, or were wrongly graded, and were kept in their place.
- **Coverage is stratified** by publisher and by kind of answer:

| Source | Dev | Test | | Kind | Dev | Test |
| :-- | --: | --: | :-- | :-- | --: | --: |
| Statistics Canada | 11 | 11 | | Figure | 7 | 8 |
| Bank of Canada | 2 | 3 | | Comparison | 3 | 2 |
| CMHC | 1 | 2 | | Flag | 3 | 1 |
| Provincial portals | 2 | 2 | | Documentation | 6 | 8 |
| Municipal portals | 1 | 1 | | Refusal or not published | 2 | 4 |
| Federal (ECCC, Health Canada, IRCC, open.canada.ca) | 3 | 4 | | Release date | 1 | 2 |
| International (World Bank, BIS) | 2 | 2 | | | | |

Each question is copied unchanged from its source key, so it grades exactly as before;
`test_maple_test_v4.py` checks that, and that the committed key is what the builder makes.

```bash
uv run python -m tests.maple_test.item_analysis          # v4/item_analysis.json
uv run python -m tests.maple_test.build_key_v4 --check   # stale key, or a missing stratum
```

The source keys are still rebuilt from the publishers by their own `--check` builders.

### Dev and test, and the rotation rule

The 47 are split into a public **dev** set (22) and a held-out **test** set (25). The split
is made by a salted hash of each id, alternating within each source, with the first salt that
puts every kind of answer in both sets (`SALT = 2`, fixed from now on): nobody chose a
question's set, and it never reshuffles. Since 2026-11-09 all 47 are dev, and the test set is
25 fresh questions (below): 72 questions in all.

1. Fixes are tuned on **dev** only. Read dev answers, write caveats for them, re-run dev.
2. **Test** answers are graded by the grader and the judge. A person reads only the flagged
   ones and records the outcome; a test answer is never the reason for a change to a server.
3. When a test question does motivate a change anyway, it moves to dev in the next key
   (v4.1), and a new question of the same source and kind, written and keyed before any
   server answers it, takes its place in test. The builder's `MOVED_TO_DEV` table records
   the move and what it motivated; no other question changes set.
4. A server's score on test is out-of-sample only for questions not in its `in_sample_for`.

**The first test set was in-sample for MapleStats:** MapleStats was changed after reading v1
and v2 answers, the release history after R-06, and v3's `maplestats-postfix` after v3. Rule 3
was therefore applied to the whole set on 2026-11-09: its 25 questions moved to dev
(`MOVED_TO_DEV`), and 25 fresh questions replaced them.

### The fresh test set (N-01 to N-25)

The 25 were written and keyed on 2026-11-09 (`build_key_v4_test.py`, key
`maple_test_v4_test.json`), before MapleStats or any other server was asked them. They are
out-of-sample for every server (`in_sample_for: []`). None repeats a v1 to v3 question, and
none asks the same thing of the same series. They keep the stratification of the set they
replace: StatCan 11, Bank of Canada 3, CMHC 2, provincial 2, municipal 1, federal 4,
international 2; figure 8, comparison 2, flag 1, documentation 8, refusal 4, release date 2.

| ID | Source | Kind | Asks |
| :-- | :-- | :-- | :-- |
| N-01 | StatCan | figure | Industrial Product Price Index, 12 months to September 2026 |
| N-02 | StatCan | figure | Business-sector labour productivity, Q2 2026 vs Q1 |
| N-03 | StatCan | figure | Regular EI beneficiaries, August 2026 |
| N-04 | StatCan | figure | Canadian-resident return trips from the US by car, August 2026 vs 2025 |
| N-05 | StatCan | comparison | New Housing Price Index, Calgary vs Edmonton, 12 months to September 2026: where weaker |
| N-06 | StatCan | flag | Q2 2026 GDP (at annual rates) divided by the population, called GDP per person for the quarter |
| N-07 | StatCan | documentation | SEPH's data sources and the Business Payrolls Survey's sample |
| N-08 | StatCan | documentation | Monthly Survey of Manufacturing: target population, its list, number of industries |
| N-09 | StatCan | refusal | Nova Scotia's monthly GDP (published for Canada only) |
| N-10 | StatCan | release date | Stock and consumption of fixed capital, 2025 |
| N-11 | StatCan | release date | Provisional poverty estimates, 2025 (past) |
| N-12 | Bank of Canada | figure | Monthly nominal CEER, October 2026, vs September |
| N-13 | Bank of Canada | comparison | CAD against the yen, October 1 vs October 30, 2026 |
| N-14 | Bank of Canada | refusal | A Bank of Canada rate for the Venezuelan bolívar (none) |
| N-15 | CMHC | documentation | Market Absorption Survey: absorbed, and when a unit counts as sold |
| N-16 | CMHC | figure | Vancouver CMA vacancy rate, October 2025, apartments of six units and over |
| N-17 | BC Data Catalogue | documentation | BC Liquor Store Locations: publisher, licence, format |
| N-18 | Données Québec | documentation | Uses of AI in Quebec's public administration: ministry, licence, frequency, years |
| N-19 | Toronto | documentation | Dinesafe: owner division, refresh rate, DataStore |
| N-20 | open.canada.ca | documentation | Proactive publication of contracts: publisher, frequency, DataStore |
| N-21 | ECCC | figure | 1981-2010 normal January mean temperature, Winnipeg Richardson Int'l A |
| N-22 | ECCC | refusal | The same normal at Toronto City Centre (none: opened 2009) |
| N-23 | open.canada.ca | refusal | CSV files in ECCC's 'Climate Data Products' dataset (none) |
| N-24 | BIS | figure | Credit to Canada's private non-financial sector, % of GDP, Q1 2026 |
| N-25 | World Bank | documentation | Definition of 'Labor force, total' (SL.TLF.TOTL.IN): ages, who counts, whose estimates |

**How the key was read.** All values come from the publishers' own APIs and pages, never
through MapleStats: StatCan's IMDB, WDS and The Daily's release schedule; Valet; CMHC's
methodology page (and its vacancy rates as StatCan's table 34-10-0127 carries them, as v2's
C-15 read CMHC's starts); ECCC's MSC GeoMet; the CKAN APIs of open.canada.ca, the BC Data
Catalogue, Données Québec and Toronto; and the World Bank and BIS APIs. Ontario's and
Alberta's catalogues and the OECD answered 429 or 403 that day, so the provincial questions
use BC and Quebec. StatCan's www150 host blocks this machine after heavy use, so the builder
has two parts that can be rebuilt apart (`--part open`, `--part statcan`). It sends one
request at a time with a pause, and stops on a 403 or 429 instead of retrying.

```bash
uv run python -m tests.maple_test.build_key_v4_test --check   # has any source changed?
uv run python -m tests.maple_test.build_key_v4 --check        # the v4 key with the fresh set
```

**Independent review.** A second agent read the 25, given only the files (not this
author's reasoning), for ambiguity, grading risk, overlap with v1 to v3, bias and shelf life.
Its written report could not be saved (a file permission was declined); its findings came
back as text, and these changes were made before any server saw the questions:

- calls that were not graded (N-12, N-13 were numeric) are now graded (`answer_regex`, a
  new optional field the grader reads for a comparison's call);
- regex bugs: N-23's refusal matched "no" inside "Normals"; N-19 and N-20 counted
  "DataStore is not active" as yes; N-17, N-18 missed English or reordered wording;
- N-16 is worded as the series it is keyed on (apartments of six units and over, as
  StatCan publishes CMHC's survey), so a server reading CMHC's three-plus headline is not
  marked wrong against a key it was not asked for;
- the flag question was replaced: averaging the provinces' October 2026 unemployment
  rates gave 6.72% against Canada's 6.7%, so the trap could not catch anyone (the
  builder now fails when a flag's trap closes);
- questions answerable from memory or from their own wording now need the page (SEPH's
  sample size, the manufacturing survey's 156 industries; N-25 now asks the World Bank's
  labour-force definition rather than its unemployment series, whose name gave the answer);
- the release questions use releases that the schedule lists (fixed capital, provisional
  poverty estimates), since the next quarterly GDP and population releases were not yet on
  it;
- the v4 prompt's example table and vector (14-10-0287-01, v2062815) are now 17-10-0009-01
  and v1, which no v4 question asks for.

**Kept, with the reviewer's objection noted.** The documentation questions on portals (N-17
BC, N-19 Toronto, N-20 open.canada.ca) ask the same kind of thing as v3's T-17, T-20, T-25
about other datasets: the stratification requires portal metadata, and no question reuses a
dataset. N-13 (CAD against the yen) is a Bank of Canada exchange rate like M-11, another
currency and dates. N-14 (no bolívar rate) is the same kind of refusal as T-12, which every
arm answered; it may separate no one, and the item analysis after the first full run will
say. Shelf life is short for about a third of the set (N-01, N-03, N-04 revise at their next
monthly release; N-02 and N-24 in December): every arm of a comparison runs against one key
build, checked with `--check` before and after.

**MapleStats was not run on the fresh set before this was merged**, as the rule requires:
the first MapleStats run on it is the out-of-sample measurement.

### Structured answers

The v4 prompt (`run.PROMPTS["v4"]`) covers figures, release dates and documentation, and asks
the answer to end with a fenced JSON block: each value with its unit and reference period,
the sources (table, vector, series or dataset id), `not_published`, and `abstain` with a
reason. `grade.grade_v4` reads the block first and falls back to the regex grader on the
whole answer:

- the block settles an answer only in its favour (every expected value, date or fact in its
  values, the right call for a comparison, `not_published` on a refusal question) or as a
  plain abstention (`abstain` with no values);
- anything else goes to the regex grader, so a block never makes an answer worse than its
  prose. Each grade records its `basis` (`json` or `regex`).

This removes the commonest false miss in v3, a refusal phrased in the source's own words
("there's no 2024 file").

### The judge, and what a person reads

`judge.py` asks an LLM judge (headless Claude Code, `claude-sonnet-5-5`, no tools, a JSON
schema) to grade each answer with the key, the rules of the v2 and v3 reviews, and a rubric
for its kind of answer. A person reads an answer only when the judge's outcome differs from
the deterministic grade, its confidence is below 0.7, or it failed. Flagged answers go to
`v4/review_queue.md`, grouped by question, shuffled, arm hidden; a person settles each in
`overrides_v4.json` as before (`"ref:<ref>"` or `"<arm>/<id>#<pass>"`). The judge never
changes a grade by itself, and the citation checks (`grade --verify`) are unchanged.

**Calibration** (`calibrate.py`) against the hand reviews of v1, v2 and v3, on the questions
v4 keeps, each version on its own. v1 and v3 are small enough to judge every answer; v2's
1,653 answers are sampled: 150 of the 273 whose regex grade a person changed and 150 of the
1,380 they did not, weighted back to those sizes (estimates; the sample counts are exact).

| Version | Answers | Judge agrees with the person | Regex grader agrees | Flagged for a person | Wrong and not flagged | Grader errors flagged | USD |
| :-- | --: | --: | --: | --: | --: | --: | --: |
| v1 | 32 | 65.6% (21 of 32) | 62.5% (20 of 32) | 53.1% (17) | 3.1% (1) | 91.7% (11 of 12) | 0.27 |
| v2 | 1,653 | 91.4% (sample 262 of 300) | 83.5% (1,380 of 1,653) | 24.8% | 1.2% | 92.7% (139 of 150) | 2.59 |
| v3 | 180 | 92.8% (167 of 180) | 71.1% (128 of 180) | 33.9% (61) | 0.6% (1) | 98.1% (51 of 52) | 1.81 |

Judge `claude-sonnet-5-5`, flagged when it disagrees with the deterministic grade or its
confidence is below 0.7. Read v2's row as: a person reads about a quarter of the answers
instead of all of them, and about 1.2% of grades stay wrong without a person seeing them,
against 16.5% for the regex grader alone. Applied to the 1,647 answers of the 1105 review,
that is about 408 answers to read. On v3, where answers are text, the regex grader is wrong
on 28.9% and the judge catches 51 of those 52.

**v1's row is mostly key drift, not the judge.** StatCan revised August 2026 trade on
2026-11-04 and the v1 key was re-keyed (M-09: 4,198.8 to 4,951.3 million); the v1 answers
were reviewed on Nov. 2 against the old value. The judge, given today's key, grades six of
them hallucinated where the review said correct. Without those six, the judge agrees on 21
of 26 (80.8%). The frozen MapleStats arm and a key built once per comparison are the fix.

On v1 and v2 together, `claude-haiku-5-5` agrees 87.3% of the time (Sonnet 91.6%), costs a
thirteenth as much (USD 0.20 against 2.63 for 300 answers), but flags 35.1% of answers
against Sonnet's 22.2%; a person's time is what v4 is saving, so Sonnet is the default.

The remaining disagreements cluster where the review rule is finer than the key: A-03
(another published series, all persons rather than excluding zero incomes: partial by the
review, hallucinated by the judge), X-16 (a drug's company named without its cancelled
status), X-12 and X-24 (one of two figures, or a rounded one). The rubric was not tuned on
these disagreements: tuning it on the hand reviews would make the calibration in-sample,
as the rule at the top of this file says for servers. Verdicts are cached in
`v4/judge_cache.jsonl`; the per-version reports are `v4/calibration_*.json`.

### Speed

- **One pass,** plus two extra passes only for the 6 questions whose outcome changed between
  passes for at least 40% of the arms (`extra_passes` in the key): 59 answers an arm, against
  183 for v2's three passes of 61.
- **Questions at once** for hosted arms (`--workers`), and **arms at once** (`run-many`):
  hosted arms run side by side, arms that start a server on this laptop run one after
  another beside them.
- **Frozen upstream data** for the MapleStats arm (`--frozen CASSETTE`, `frozen_server.py`):
  the server's HTTP is recorded once and replayed, so reruns neither drift nor hit StatCan
  WDS again. `FROZEN_MODE=replay` fails any request not recorded. Other servers cannot be
  frozen this way.
- A server that did not connect is asked again, up to twice, instead of becoming a run error.

Expected wall time per arm (`python -m tests.maple_test estimate`), from each arm's seconds
per answer in its earlier runs, for 59 answers:

| Arm | Seconds per answer | One at a time | Four at a time | v2's 183 answers, one at a time |
| :-- | --: | --: | --: | --: |
| MapleStats (local, stdio) | 21 | 21 min | 21 min (local server) | 64 min |
| MapleStats hosted | 21 | 21 min | 21 min (capped at one: rate limit) | 64 min |
| mcp-statcan | 14 | 14 min | 4 min | 43 min |
| Pipeworx | 18 | 18 min | 4 min | 55 min |
| statcan2 | 14 | 14 min | 4 min | 43 min |
| arose26 | 13 | 13 min | 13 min (local server) | 40 min |
| canada-data-agent | 15 | 15 min | 15 min (local server) | 46 min |
| CanData-MCP | 32 | 31 min | 31 min (local server) | 98 min |
| OpenCanadaPublicDataMCP | 33 | 32 min | 32 min (local server) | 101 min |
| mcp-canada | 43 | 43 min | 43 min (local server) | 131 min |
| OpenMCP | 89 | 88 min | 88 min (local server) | 271 min |
| No data tool | 10 | 10 min | 2 min | 31 min |

With `run-many`, the hosted arms run beside the local lane, so a full comparison of all
twelve arms takes about as long as the local lane: roughly 4.1 hours, against about 16.5
hours one arm after another at v2's 183 answers each. These are means from earlier runs;
OpenMCP's depends on this laptop's memory.

```bash
uv run python -m tests.maple_test run --version v4 --arm maplestats_hosted --workers 3
uv run python -m tests.maple_test run-many --version v4 --arms mcp_statcan statcan2 arose26 --workers 3
uv run python -m tests.maple_test grade --version v4 --judge     # results_v4.md, v4/review_queue.md
uv run python -m tests.maple_test.calibrate                     # judge vs the v1 and v2 reviews
uv run pytest tests/test_maple_test_v4.py
```

### Dry run, MapleStats hosted, 2026-11-09

All 47 questions through the hosted server (`maplestats_hosted`), one at a time, one pass plus
two extra passes on the volatile questions: 61 answers (the run started under the 48-question
key; the four questions dropped after v3's review are left out, and the three added were
asked the same day). MapleStats is **in-sample** on every v4 question, so this checks the
pipeline, not MapleStats' accuracy; it is not comparable with other arms or with v2.

| Measure | Result |
| :-- | --: |
| Correct (each question once; 43.7 of 47) | 92.9% |
| Dev (21 of 22) / test (22.7 of 25) | 95.5% / 90.7% |
| Answers correct (57 of 61) | 93.4% |
| USD per answer (2.96 for 61) | 0.049 |
| USD per question (2.96 for 47) | 0.063 |
| Seconds per answer | 19.8 |
| Wall time (64 answers, then 5 added) | 22.7 min, then 1.5 min |
| Answers with a JSON block | 100.0% (61 of 61) |
| Grades decided by the JSON block | 77.0% (47 of 61) |
| Flagged for a person | 9.8% (6 of 61) |
| Judge cost | USD 0.58 |

The first attempt asked three questions at once and is set aside in `runs_v4/paused/`: the
hosted server's limit of 120 requests a minute per client answered "Rate limit exceeded" on
16 of 64 answers, which then declined (70.8% correct). `MAX_WORKERS` now keeps hosted
MapleStats to one question at a time; the run above had no rate-limited answer and no run
error. Hosted servers of other publishers may have limits of their own; start them with
`--workers 1` until a clean run shows they take more.

One unflagged miss shows what the triage leaves: M-09's "about $5.0 billion" (key
$4,951.3 million, ±0.5) was graded hallucinated by both the grader and the judge (confidence
0.70, at the threshold); a person might call it partial.

## Shelf life

Two questions depend on today's calendar: M-13 holds until StatCan publishes Q4 2026 GDP
(about late February 2027), and `build_key` refuses to rebuild once it has. Values can be
revised (population and wages especially); `--check` reports any change, and a changed
key means earlier runs are graded against the new figures only after a person reviews them.

Built 2026-11-02 by MapleStats, credits to CanData (neobenjax/Canadian-Open-Data-Agentic-Platform)
for the benchmark design this follows.
