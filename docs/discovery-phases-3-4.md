# Discovery, Phases 3 and 4: a proposal (2026-11-07)

The discovery plan in [`ROADMAP.md`](ROADMAP.md#discovery) has four phases. Phase 1 (a
benchmark) is built; Phase 2 (a hybrid ranker for tools) is measured and has not passed its
gate ([`phase2.md`](../tests/discovery_benchmark/phase2.md)). Phases 3 and 4 had a scope and no
gate. This note proposes both: what to index, how to measure it, where it runs, and the gate
each phase must pass. Nothing here is built.

## Where discovery stands

- `search_tools` finds the tool (R@5 0.84 on 129 reviewed questions, 2026-11-07); `plan_query`
  names the tools for a question in order (expected tool anywhere in the plan 0.90). Neither
  names the table, dataset, sheet or column that holds the answer: the model calls a tool's own
  search next (`wds_search_cubes`, `ckan_search_datasets`, `cmhc_dt_*`), one source at a time.
- Each source's own search is lexical and per source. `wds_search_cubes` matches every title
  word over a cached list of about 8,000 StatCan tables; CKAN portals search through their own
  Solr. Nothing ranks "rental vacancy rate in Halifax" across StatCan, CMHC and the Nova Scotia
  portal at once.
- Only 3 of the 129 benchmark questions record a dataset-level answer (`live_expected`: a StatCan
  table number). There is no dataset or variable answer key.
- Adding tools makes tool search harder: the 24 tools added between Oct. 27 and Nov. 7 pushed
  four questions out of `search_tools`' top five. A dataset index behind fewer tools is one way
  to stop that drift.

## Phase 3: datasets and variables

### What a record is

One record per dataset (a StatCan table, a CKAN dataset, a CMHC data table, a Bank of Canada
series group, a provincial agency's workbook) and, beneath it, one per variable (a StatCan
dimension, a CKAN DataStore column, a workbook column heading, a PUMF codebook variable). Each
record holds:

- source, dataset id, title and description in English and French (where the source has
  French), subject and survey codes, frequency, first and last reference period;
- for variables: name, label, and a short list of member or category names (not all members:
  StatCan geography alone has thousands, and the geography resolvers already handle places);
- **the call that reads it**: the tool name and arguments (`wds_get_cube_metadata`
  `{"product_id": 14100287}`), so a hit always leads to the live adaptor;
- provenance: the source URL, the record's last-modified date, and the build date.

No data values. The index says where to look; the number comes from the tool call, as the
roadmap's constraints require.

### Sources, in order

| Order | Source | Records (approximate) | Metadata available | Variables |
|---|---|---:|---|---|
| 1 | StatCan tables (WDS) | 8,000 tables | titles, subjects, surveys, dates in the cached list `wds_search_cubes` reads | dimension names and member names from `getCubeMetadata`, one call per table |
| 2 | StatCan PUMFs | dozens of files | `statcan_pumf_` file listings | codebook variables and value labels (`statcan_pumf_get_codebook`): the case where variable search matters most, since the user must name a variable to tabulate |
| 3 | CKAN portals (federal, provincial, municipal) | about 34,000 federal (OpenMCP's count), 3,000 open Alberta, others smaller | `package_search` metadata | DataStore field names where a resource is in the DataStore; none otherwise |
| 4 | CMHC data tables, Bank of Canada Valet groups, provincial agencies (BC Stats, ISQ, NL, NWT, Yukon) | hundreds each | each module's listing tool | sheet and column headings the modules already read |

Start with 1 and 2: StatCan is where most benchmark questions land (25 of 129 are StatCan-only and
most multi-source questions include it), and PUMF variables have no discovery path today. CKAN
comes third because its portals already search themselves, and federal CKAN is the largest and
least curated set.

Before building, confirm every field above against live payloads, as `AGENTS.md` requires: the
cached StatCan list carries `dimension_count` but not, in this codebase, dimension names.

### How it is built, stored and searched

- **Built offline**, not on the host: about 8,000 `getCubeMetadata` calls at StatCan's rate limit
  is hours of work, and CKAN listings are paced at one request per 10 seconds for several
  portals. A scheduled GitHub Actions job (or a script Daniel runs) builds one DuckDB file and
  publishes it as a release asset or to the hosted server's Azure Files share (`/data`), which
  already holds the PUMF cache. The server reads the file; it never builds it.
- **Refreshed incrementally**: StatCan's changed-cube list (`wds_get_changed_cube_list`) and
  CKAN's `metadata_modified` say what changed since the last build; only those records are
  fetched again. A record older than its source's refresh window is flagged as stale.
- **Searched lexically first, in DuckDB, without the `fts` extension.** The roadmap notes that
  DuckDB's `fts` extension must be downloaded at run time and does not update incrementally.
  Instead the build writes BM25 statistics as plain tables (term, record, term frequency;
  record lengths; document frequencies), using `shared/search.py`'s tokenizer, and a query is
  one SQL statement over them. DuckDB is already a dependency; nothing new is installed.
- **Embeddings later, if Phase 2's held-out test shows they help.** If they do, the same e5-small
  model embeds titles and descriptions; 60,000 records at 384 dimensions is about 23 MB in int8
  or 92 MB in fp32, stored in the same file.
- **Memory budget**: the index loaded or memory-mapped stays under 150 MB on the hosted server, so
  that with a PUMF tabulation (+400 MB), two `wds_query_series` workers (256 MB each) and the
  server itself (about 120 MB) the total stays near 1.1 GB of the 2 GiB.

### How it reaches users

Through one new tool, `discover_datasets` (name to settle), found by `search_tools` and run with
`call_tool`: it takes a question, optional sources and a language, and returns ranked datasets
and variables, each with a one-line reason for the match (which words or identifiers matched,
in which field) and the call that reads it. It is registered only when the index file is present
and a setting turns it on (the `catalogue.TOOL_SWITCHES` pattern `statcan_pumf_tabulate` uses), so
`search_tools` and `plan_query` do not change for anyone until Phase 3 passes its gate.

### The Phase 3 benchmark

A new answer key, built the way Phase 1's was: written by one session from the sources' own
listings, reviewed by a second session that checks each answer against the live source, frozen
before any ranker runs.

- 150 to 200 questions, English and French, each with one or more accepted
  `(source, dataset id)` pairs and, for 50 or more, accepted variables (a StatCan dimension, a
  PUMF variable, a CKAN column).
- Coverage: StatCan tables across subjects, PUMF variables, CKAN datasets on three or four
  portals, cross-source questions where two sources both answer, and questions no source
  answers (to measure abstention).
- Baselines: each source's own search (`wds_search_cubes`, `ckan_search_datasets`; the live
  script `scripts/discovery_benchmark_live.py` already does this for two sources), and a
  "best source search" oracle that is told the right source.
- Metrics: dataset R@1, R@5, MRR; variable R@5; correct source at 1; abstention; latency; index
  size and memory.

### Phase 3 gate

1. The answer key is reviewed and frozen, and the run is repeatable in CI (offline, against a
   committed index snapshot).
2. Dataset R@5 is higher than every source's own search on that source's questions, and higher
   than the best single-source search on cross-source questions, with p below 0.05 on a sign
   test over the questions that change.
3. No loss in French (dataset R@5 within 0.02 of English or better than the French baseline).
4. Table numbers and PUMF file names typed exactly rank their record first (the Phase 2 lesson).
5. Every hit carries provenance and a tool call that, run live, returns the dataset it names
   (checked on a sample of 50 in a live script).
6. Cost: index under 150 MB in memory, query p95 under 100 ms, the build reproducible from a
   script, and the server unchanged when the file is absent.

## Phase 4: integration

### Scope

- `plan_query` adds, to each step that reads a source, the best one to three datasets or
  variables from the index with their match reason (an additive field; the existing plan text
  and steps stay as they are).
- `search_tools` keeps ranking tools. Once Phase 3 passes, its top-five list may include
  `discover_datasets` for questions about finding data, which is a normal docstring change.
- Fallback: with no index, a stale index for one source, or an index built with a different
  tokenizer or model (the `catalog_meta` guard Phase 2 already applies to the semantic index),
  `plan_query` returns exactly today's plan and says why in a logged warning.
- Refresh on the hosted server: a weekly scheduled build, swapped in atomically (write a new
  file, then rename), with the build date in every result's provenance.
- Regression tests: the Phase 1 floors and new Phase 3 floors in `tests/`, the index-absent
  plan equal to today's plan on all 129 Phase 1 questions.

### Phase 4 gate

1. On the Phase 1 questions, `plan_query`'s tool metrics do not drop (anywhere 0.90, R@5 0.85 on
   2026-11-07).
2. On the Phase 3 questions, the dataset named in the plan's first reading step is right as often
   as `discover_datasets` alone puts it first (no loss from integration).
3. With the index absent, every Phase 1 plan is identical to today's.
4. `plan_query` p95 stays under 50 ms (5.5 ms p50 and 8.2 ms p95 today), and the hosted server's
   peak memory under a PUMF tabulation stays under 1.5 GB.
5. A model-run check, for the first time: the same set of questions answered by a client model
   with and without dataset hints (the Maple Test harness), compared on correct figures and on
   tool calls per answer. Dataset hints are worth shipping only if answers get more right or
   cheaper, not just if retrieval metrics rise.

## Decisions for Daniel

- Where the index is built and stored: a GitHub Actions schedule publishing a release asset, or a
  job writing to the Azure Files share. The first keeps the build public and reproducible; the
  second avoids a download on start. Changing Azure is outside this proposal.
- Whether the Phase 3 answer key is reviewed by a person for a sample (Phase 1's was reviewed by a
  second AI session only).
- Whether CKAN is in Phase 3 at all, or left to the portals' own search with the index covering
  StatCan, PUMFs and the agencies' workbooks.

## Effort, roughly

- Phase 3 answer key (write and review): two sessions.
- StatCan and PUMF records, the DuckDB build, the SQL BM25 and `discover_datasets` behind a
  setting: one to two sessions, plus a first full build of several hours, unattended.
- CKAN and the other sources: one session each family.
- Phase 4: one session for `plan_query` and the tests, one for the scheduled refresh, and a Maple
  Test run.
