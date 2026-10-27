# Discovery Phase 2: hybrid semantic search, measured (2026-10-27)

Phase 2 of the discovery plan (`docs/ROADMAP.md`): an optional index of tool metadata,
BM25 against multilingual embeddings and reciprocal-rank fusion, exact-identifier boosts,
and the costs, judged on the Phase 1 benchmark reviewed on 2026-10-27
([`baseline.md`](baseline.md), [`REVIEW.md`](REVIEW.md)).

**Outcome.** The identifier boosts cost nothing, change no reviewed score and fix bare
identifier queries; they are now in the default `search_tools`. The best hybrid that fits a
small host (multilingual-e5-small, int8) ranks more first answers right (R@1 0.56 to 0.61,
French 0.51 to 0.66) but fewer in the top five that `search_tools` returns (R@5 0.88 to 0.84),
and adds about 220 MB of memory and 2.5 s to the first search. **The Phase 2 gate is not met**:
the retrieval gain is not across the board, and the cost is material on a 512 MB host. The
hybrid ships as a prototype behind `MAPLE_SEARCH=hybrid` and the `semantic` extra, off by
default. EmbeddingGemma ranks best of all (R@1 0.65, R@5 0.88, R@10 0.95, MRR 0.76) but needs
about 0.7 GB once loaded and three to four times that while it embeds, plus Gemma's licence
terms: not a candidate for the hosted server.

## Method

- Questions: the 129 reviewed questions (`queries.json`, fixtures `5846d2758d0a2c2d`), scored as
  in Phase 1 (an expected or alternative tool counts). Plus 29 identifier probes
  (`identifiers.json`: table numbers, vectors, Bank of Canada series codes, tool names and
  prefixes, classification codes, survey acronyms). **The probes are not reviewed**: they were
  written by the session that wrote the boosts, before running them, with their accepted tools
  read from the docstrings. Treat them as a check of what identifier queries do, not as a score.
  The reviewed key has only six identifier questions (`statcan-en-03`, `-04`, `-05`, `-15`,
  `statcan-fr-03`, `boc-en-06`); BM25 already put the right tool first on all six.
- Catalogue: the 374 searchable tools in `tool_catalogue.json` (the baseline's), so a module
  being added in the same tree does not move the rows; `--all-registered` includes it.
- Rankers, all in one process over the same snapshot
  (`python -m tests.discovery_benchmark.phase2`):
  - `bm25`: the server's index (fastmcp's BM25 Okapi with the accent, plural and stop-word
    tokenizer). It reproduces the baseline exactly.
  - `bm25 + ids`: the same with the identifier boosts (below).
  - `semantic`: cosine similarity between the query and each tool's card, one embedding per tool.
  - `rrf`: reciprocal-rank fusion (k = 60, the usual constant, not tuned) of BM25's top 50 and
    the embedding's top 50, equal weights; `rrf + ids` adds the boosts after fusion.
- Card (what is embedded per tool): the name, the docstring's first paragraph, and the
  Keywords and Mots-clés lines. Measured on the first run with e5-small: the whole docstring
  did worse (R@1 0.46 alone, RRF 0.56) than the card (0.58, 0.67), because parameter notes and
  caveats dilute one vector and short models cut the Mots-clés line, last in the docstring.
- Models (CPU only, ONNX, no torch, no GPU):
  - `intfloat/multilingual-e5-small` (MIT, 118 M parameters, 384 dimensions), the authors'
    int8 ONNX file, run by onnxruntime with sentencepiece: the `semantic` extra. Also its fp32
    file through fastembed, for comparison.
  - `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (Apache-2.0, through fastembed).
  - `google/embeddinggemma-300m` (Gemma terms, through fastembed's ONNX copy). The roadmap names
    "EmbeddingGemma 2"; only `embeddinggemma-300m` was found and tested.
- No hosted embedding API was tried: a query must not leave the server.
- Machine: Linux container, 4 cores, Python 3.13, onnxruntime 1.31.1, fastembed 0.9.1. Query
  latency is one query at a time on one thread; memory is resident size (VmRSS).

Model performance claims from other projects (OpenMCP's use of EmbeddingGemma, model cards)
were not used as evidence; every number here is a MapleStats run.

## Results on the reviewed questions (n = 129: 76 English, 53 French)

| ranker | R@1 | R@5 | R@10 | MRR | EN R@1 | EN R@5 | FR R@1 | FR R@5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bm25 (baseline) | 0.56 | 0.88 | 0.91 | 0.69 | 0.59 | 0.87 | 0.51 | 0.89 |
| bm25 + ids | 0.56 | 0.88 | 0.91 | 0.69 | 0.59 | 0.87 | 0.51 | 0.89 |
| e5-small int8: semantic | 0.59 | 0.84 | 0.88 | 0.69 | 0.57 | 0.84 | 0.62 | 0.83 |
| **e5-small int8: rrf + ids** (prototype) | 0.61 | 0.84 | 0.91 | 0.72 | 0.58 | 0.83 | 0.66 | 0.87 |
| e5-small fp32: rrf + ids | 0.63 | 0.84 | 0.91 | 0.73 | 0.58 | 0.84 | 0.70 | 0.85 |
| MiniLM-L12: semantic | 0.33 | 0.57 | 0.64 | 0.44 | 0.36 | 0.58 | 0.28 | 0.57 |
| MiniLM-L12: rrf + ids | 0.53 | 0.78 | 0.87 | 0.64 | 0.57 | 0.79 | 0.49 | 0.77 |
| EmbeddingGemma: semantic | 0.62 | 0.88 | 0.92 | 0.73 | 0.59 | 0.86 | 0.66 | 0.91 |
| EmbeddingGemma: rrf + ids | 0.65 | 0.88 | 0.95 | 0.76 | 0.66 | 0.86 | 0.64 | 0.91 |

By category, R@1 / R@5:

| ranker | statcan | boc | cmhc | ckan_federal | ckan_provincial | municipal | multi_source | ambiguity |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bm25 | 0.76 / 1.00 | 0.50 / 0.83 | 0.83 / 1.00 | 0.42 / 0.75 | 0.25 / 0.75 | 0.62 / 1.00 | 0.50 / 1.00 | 0.45 / 0.60 |
| e5-small int8: rrf + ids | 0.80 / 0.96 | 0.75 / 0.92 | 0.83 / 1.00 | 0.33 / 0.75 | 0.17 / 0.58 | 0.56 / 0.81 | 0.70 / 1.00 | 0.55 / 0.65 |
| EmbeddingGemma: rrf + ids | 0.84 / 1.00 | 0.83 / 0.92 | 0.83 / 1.00 | 0.50 / 0.75 | 0.33 / 0.67 | 0.62 / 0.94 | 0.70 / 1.00 | 0.45 / 0.65 |

What the e5 hybrid changes in the top five (the part `search_tools` returns): it gains three
questions (`boc-en-02` USD to CAD, `ambiguity-en-03` poverty rate, `ambiguity-fr-08` oil
production) and loses seven, each a question that names a place or portal, which BM25 matches
word for word and the embedding pulls toward a topically similar tool:
`ckan_provincial-en-04` (New Brunswick health facilities, rank 1 to 9), `-en-06` (Manitoba school
divisions), `municipal-en-02` (Edmonton property assessment, out of the top ten), `municipal-en-03`
(Winnipeg 311), `municipal-fr-06` (Gatineau), `ambiguity-en-06` (median household income in
Ontario, out of the top ten) and `statcan-fr-07` (crude oil exports to the US).

The embedding alone is the best ranker on the ambiguous, general questions (e5-small R@5 1.00 and
EmbeddingGemma 0.90 against BM25's 0.60 on "How many Canadians have a job?" and the like), and
the worst on named places and portals. Fusion with equal weights keeps most of BM25's
precision on places and little of the embedding's recall on vague questions; a fusion that
weighs the embedding by question type would be the next thing to try, on new questions, since
tuning weights on these 129 would make the benchmark measure itself. A sensitivity row with the
embedding at half weight (`phase2.py` writes it) moves R@1 and R@5 by at most 0.01 for e5-small
int8, so the result does not hinge on the weight.

The same hybrid run end to end through `search_tools`
(`MAPLE_SEARCH=hybrid python -m tests.discovery_benchmark`, 378 registered tools) gives R@1 0.60,
R@5 0.85, R@10 0.91, MRR 0.72, with parity between the server's top five and the runner's.

## Exact identifiers

| ranker (identifier probes, unreviewed, n = 29) | R@1 | R@5 | table (6) | vector (4) | tool name (5) | acronym (5) |
|---|---:|---:|---:|---:|---:|---:|
| bm25 | 0.59 | 0.90 | 0.50 / 0.83 | 0.75 / 1.00 | 0.60 / 1.00 | 0.00 / 0.60 |
| bm25 + ids | 0.76 | 0.93 | 0.83 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 0.00 / 0.60 |
| e5-small int8: semantic | 0.34 | 0.62 | 0.33 / 0.67 | 0.00 / 0.25 | 0.80 / 1.00 | 0.20 / 0.60 |
| e5-small int8: rrf | 0.66 | 0.83 | 0.67 / 0.83 | 0.50 / 0.50 | 0.80 / 1.00 | 0.40 / 0.60 |
| e5-small int8: rrf + ids | 0.72 | 0.93 | 0.83 / 1.00 | 0.50 / 1.00 | 1.00 / 1.00 | 0.40 / 0.60 |
| EmbeddingGemma: rrf + ids | 0.83 | 0.93 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 0.00 / 0.60 |

(Category cells are R@1 / R@5; classification codes, prefixes and series codes are in the
generated `phase2.md`.) Embeddings do not read identifiers: alone, e5-small finds the vector
tools for one vector question in four. Fusion without boosts loses identifier questions that
BM25 got right; with the boosts the hybrid keeps them (R@5 0.93 either way). On the six reviewed
identifier questions every ranker with boosts keeps the right tool first.

The boosts, in `shared/search.py` (`identifier_boosts`), apply to the default BM25 and to the
hybrid alike:

- a tool's exact name in the query (`boc_get_observations`) puts that tool first; a family
  prefix (`cmhc_dt_`, `eccc_datamart`) lifts the family;
- a StatCan table number (`14-10-0287-01`, `14-10-0287`, `1410028701`, `14100287`) lifts the
  StatCan tools that take a `product_id`. The tokenizer splits a hyphenated number into "14",
  "10", "0287" (stray matches) and an unhyphenated one matches nothing: `36100434` alone used to
  return no tool. An 8-digit number starting with 0 is a DIN, not a table;
- a vector (`v41690973`) lifts the tools taking `vector_id`, `vector_ids` or `series_names`, and
  `boc_get_series`, whose docstring shows V-numbers (old Bank of Canada series are named so).

A boost is a share of the best score, so the query's other words still order the boosted tools
("download" puts `wds_get_full_table_download` first among the table tools). On the reviewed
questions the boosts change no accepted tool's rank, only tools below it.

Acronyms are not fixed by a boost: LFS, SEPH, MBM and EPA appear in no tool docstring (CPI,
NAICS, NOC/CNP, HS and DIN do, and BM25 already finds them). The fix is a docstring one, outside
this change: add the survey acronyms (LFS/EPA, SEPH/EERH, CPI/IPC, MBM/MPC) to the Keywords and
Mots-clés of `wds_search_cubes` and `statcan_indicators_get_indicators`.

## Costs

Server process, `search_tools` through an in-process client, MAPLE_SEARCH=bm25 against hybrid
(same machine, one run each):

| | bm25 | hybrid (e5-small int8) |
|---|---:|---:|
| resident memory after the first search | 122 MB | 345 MB (+223 MB) |
| peak resident memory | 124 MB | 413 MB (+289 MB, while the model loads) |
| first search (index build, model load) | 0.6 s | 3.1 s |
| `search_tools` p50 / p95 | 11 / 14 ms | 24 / 32 ms |
| ranking alone, p50 (phase2.py) | 0.5 ms | 5 ms |
| install size of new dependencies | 0 | 124 MB (onnxruntime 1.31.1, numpy, sentencepiece, flatbuffers; protobuf and packaging already installed) |
| model and index on disk | 0 | 118 MB model + 5 MB tokenizer + 1.4 MB index |
| index build | 0 | about 12 s for 375 tools on one thread (plus a 123 MB download the first time) |

Where the memory goes (measured in a bare process): onnxruntime and numpy imports about 40 MB,
the sentencepiece vocabulary about 60 MB, the int8 model session about 130 MB. The Hugging Face
`tokenizers` package holds about 280 MB for the same 250,000-word vocabulary, which is why the
extra uses sentencepiece (same token ids on all 374 cards). fastembed, used for the comparison
rows only, adds pillow, mmh3, loguru, huggingface-hub and others (179 MB installed) and held
about 900 MB for e5-small fp32 and 1 GB once EmbeddingGemma was loaded (2.5 GB while it
embedded the cards, measured alone on four threads); EmbeddingGemma also took 33 ms (four
threads) to 80 ms (one thread) per query.

On Render's free tier (512 MB, cold starts; hosting is decided after Nov. 1) the hybrid would
take the server from about 120 MB to about 350 MB before any tool module is imported, with a
peak above 400 MB on the first search after every cold start. That leaves little for the data
tools (the PUMF, DuckDB and Excel readers allocate on their own). EmbeddingGemma does not fit.

## Privacy

- Queries are embedded in the server process; nothing is sent to an embedding service. The
  only network use is the one-off model download from huggingface.co by the build command,
  pinned to one revision and checked by SHA-256.
- The index holds tool metadata only (names, summaries, keywords), never data rows.
- Data values and authoritative retrieval stay in the existing tools: `search_tools` returns
  tool definitions, in the same format as before; the number still comes from `call_tool`.
  The plan's "ranked candidates with reasons and source links" is not added to the output,
  because this change keeps `search_tools`' format unchanged; the boosts carry a reason string
  internally (`identifier_boosts`) for a later, additive field.

## Licences

- multilingual-e5-small: MIT (model card and repository), compatible with this MIT project;
  the weights are downloaded by the user's build, not redistributed in the package.
- paraphrase-multilingual-MiniLM-L12-v2: Apache-2.0.
- EmbeddingGemma: Gemma Terms of Use, not an open-source licence. Using it means accepting
  those terms (the Hugging Face repository is gated), and redistributing the weights or a
  derivative requires passing the terms and the Gemma Prohibited Use Policy on as binding
  restrictions. The MIT code could call it as a separate, user-downloaded model, but the
  model could not be bundled under MIT, and a hosted MapleStats using it would be bound by the
  prohibited-use policy. Google's terms claim no rights in outputs (the vectors), but shipping
  a prebuilt index would still tie the project to a model whose terms Google can update. Note
  that fastembed downloads it from an ungated ONNX copy (`onnx-community`), which does not
  change the terms that apply.
- New runtime dependencies of the extra: onnxruntime (MIT), sentencepiece (Apache-2.0), numpy
  (BSD-3-Clause), flatbuffers (Apache-2.0).

## The gate

"Demonstrably better benchmark retrieval without material regression in exact identifiers,
French performance or operational cost":

| criterion | e5-small int8 hybrid | verdict |
|---|---|---|
| better retrieval | R@1 +0.05, MRR +0.03, R@10 equal, R@5 0.88 to 0.84 (7 lost, 3 gained: 113 to 109 of 129), municipal R@5 −0.19, ckan_provincial R@5 −0.17 | mixed: not demonstrably better at the five results `search_tools` returns |
| exact identifiers | no reviewed identifier question moves; probes R@5 0.93 as with bm25 + ids (R@1 0.72 against 0.76) | no material regression, thanks to the boosts |
| French | R@1 0.51 to 0.66, MRR 0.66 to 0.75; R@5 0.89 to 0.87 | better at rank 1; net one question lost in the top five (47 to 46 of 53) |
| operational cost | +223 MB resident, +289 MB peak, +2.5 s first search, +13 ms per search, +124 MB install | material on a 512 MB host |

**Not met.** `MAPLE_SEARCH` stays `bm25` by default; the hybrid stays a feature-flagged
prototype for a local stdio install with memory to spare. EmbeddingGemma would meet the
retrieval part (R@5 equal, R@1 +0.09, R@10 +0.04, French R@5 +0.02) and fails cost by a
wide margin.

## What shipped

- Default (all installs): the identifier boosts in `search_tools`
  (`shared/search.py::identifier_boosts`, `server.py::AnnotatedBM25SearchTransform._search`).
  Reviewed benchmark unchanged; the regression floors in `tests/test_discovery_benchmark.py` are
  unchanged.
- Optional: `pip install "maplestats-mcp[semantic]"`, then
  `python -m maplestats_mcp.shared.semantic build` (model and index into `MAPLE_SEMANTIC_DIR`,
  default a `maplestats-mcp/semantic` folder in the system temp folder), then
  `MAPLE_SEARCH=hybrid`. The index records model, revision, file hashes, dimension and card
  version (OpenMCP's `catalog_meta` guard): an index built any other way is refused and search
  falls back to BM25 with a logged reason, as it does without the extra or the index. A tool
  added or edited since the build has no vector and is ranked by BM25 alone (logged with a
  count) until the next build.
- The runner's 10-deep ranker is now an instance of the server's own transform, so parity holds
  in both modes.

## Not done, and why

- The website's search (`site/assets/site.js`, out of scope here) ranks with BM25 only; its
  tokenizer is unchanged, but its `rank()` does not apply the identifier boosts, so the site no
  longer ranks exactly like `search_tools` for identifier queries (the 16 queries
  `tests/test_site.py` compares contain none, and it passes). Porting `identifier_boosts` to
  `site.js` would restore exact parity.
- No index of datasets or tables (StatCan cubes, CKAN datasets): Phase 2 indexed tools only,
  which is what `search_tools` ranks. Dataset-level ranking is Phase 3.
- No weight tuning, question-type routing or reranker: each would be fitted to these 129
  questions; new reviewed questions are needed first.
