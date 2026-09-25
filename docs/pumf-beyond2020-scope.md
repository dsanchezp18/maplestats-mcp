# PUMFs, Beyond 20/20 and cross-language compatibility: scope

First scoped 2026-09-24. Revised the same day, after PUMF phase 1 shipped
and after looking at mountainMath's `canivt`. Findings were checked
against the live sources that day unless marked otherwise.

## 1. PUMFs

### Shipped: phase 1 (discovery and codebooks)

There are four `statcan_pumf_` tools, verified live on LFS, Census,
CCHS, SHS and EICS:

- `statcan_pumf_search`: StatCan data products categorized as public use
  microdata. There are 144 in the catalogue.
- `statcan_pumf_list_files`: the free ZIP downloads, found by going from
  the catalogue page to its `/n1/pub/` pages. All seven PUMFs sampled
  have direct, unauthenticated downloads.
- `statcan_pumf_list_zip` and `statcan_pumf_get_codebook`: these read
  inside a ZIP with HTTP range requests (`shared/remote_zip.py`).
  Listing the 182 MB Census 2021 file takes 12 KB. The codebook tool
  parses whichever format the ZIP carries:
  - an LFS-style codebook CSV;
  - Stata `.dct` and `.do` files;
  - SPSS `_vare`/`_vale` label files, with `_varf`/`_valf` in French.

  It returns variables, labels, value codes, fixed-width positions and
  weight variables, in English or French.

**Still open.** SHS and CSWC also ship SAS-only label files, and the SAS
`PROC FORMAT` syntax is not parsed. SHS has Stata and SPSS files too, so
it still works.

### Phase 2: weighted tables

Add `statcan_pumf_tabulate(url, member, rows, columns, filters,
statistic)`: weighted counts, means and shares, computed server-side.

- **Reading.** Stream the data member out of the ZIP. Deflate supports
  streaming, so the whole archive never sits in memory. Read CSV where
  the ZIP has it (LFS, Census `_v2.csv`). Otherwise read the fixed-width
  file, using positions from the codebook.
- **Engine.** Add `duckdb` or `polars`; both scan CSV lazily. I'd pick
  DuckDB, because a SQL `GROUP BY` over a named weight maps directly to
  the tool's arguments.
- **Standard errors are feasible for several PUMFs.** The Census PUMF
  ships 16 replicate weights (`WT1`...`WT16`), and SHS, EICS and CSWC ship
  bootstrap weight files (`*_BSW*`). For those, return standard errors and
  CVs using the survey's documented variance method. LFS has no replicate
  weights, so return the point estimate plus a note pointing to the CV
  tables in the user guide. Never invent a standard error.
- **Guards.** Report the unweighted cell count next to every estimate,
  and flag cells below a minimum. Return no raw rows beyond a small
  sample.
- **Storage.** Streaming avoids keeping ZIPs on disk, but every table
  then pays for a full download: 30 MB for a year of LFS, 182 MB for the
  Census. A persistent cache volume on the hosted server avoids that
  repeat cost. **Decision needed.**
- **Effort.** 2-3 days for LFS plus the Census, then about half a day
  per extra survey (its weight names and variance method).

## 2. Beyond 20/20 (IVT)

### What changed

The first draft said to skip IVT because the tables checked have CSV
twins. That holds for the recent census data tables: the 2016 and 2006
download pages checked offer CSV, TAB and SDMX next to IVT. It doesn't
hold everywhere. mountainMath's [canivt](https://github.com/mountainMath/canivt)
(MIT, v0.5.0, July 2026) shows that some data exists only as IVT:

- custom census tabulations, many hosted on the Borealis dataverse;
- older census releases that predate the SDMX and CSV products.

canivt reverse-engineered the format and ships its notes in
`inst/notes/`, including an 88 KB `ivt-format.md`, a marker catalogue and
a coverage list. It downloads IVT files by StatCan catalogue number or
Borealis id and returns tidy data, Parquet or CSV with dimension
metadata, DGUIDs and footnotes. The author reports that some files still
warn or fail to parse.

### Options

| Option | How | Pros | Cons |
|---|---|---|---|
| A. Route | Find IVT tables (StatCan catalogue, Borealis) and return the CSV/SDMX twin where one exists; otherwise return the IVT link with a ready canivt snippet | Small; no parsing risk | IVT-only tables are not readable in the MCP itself |
| B. Call canivt | Run `Rscript` with canivt on the server | Reuses a maintained parser | Adds R to the Docker image; slow start per call; a second runtime to secure |
| C. Port to Python | Reimplement the parser from canivt's spec, tested against canivt's output | Native, fast, no R on the server | Large: about 700 KB of R and still-evolving format knowledge; MIT allows it, credit required |

**Recommendation: A now, C only if IVT-only demand proves real.** A
delivers most of the value in 1-2 days, and it pairs naturally with the
cross-language snippets in section 3. If ported later, contacting Jens
von Bergmann first makes sense: canivt's notes are the spec, and
coordinating avoids a divergent second parser.

Also still to do: census data tables (cross-tabulations) are not covered
by the existing Census Profile tools. Adding them is the main piece of
option A (1-2 days).

## 3. Discovery compatibility with R, Stata, Julia and Python

The MCP finds data and returns it with provenance. Analysts then need
the same data in their own scripts, reproducibly. The gap is the step
from "the agent found it" to "my script fetches it".

### Proposal: `reproduce` snippets

Add one tool, `get_reproduction_code(tool, arguments, language)`, and
mention it in each result's provenance. It returns idiomatic code in R,
Stata, Julia or Python that fetches the same data from the same source
URL, following the user's conventions. The mapping is per source:

| Source | R | Python | Stata | Julia |
|---|---|---|---|---|
| StatCan tables (WDS) | `cansim::get_cansim("18-10-0004-01")` | full-table CSV via `polars.read_csv` | `import delimited` on the full-table CSV | `TidierFiles.read_csv` on the CSV URL |
| Census Profile | `cancensus::get_census()` | CSV download + `polars` | `import delimited` | `read_csv` |
| PUMF | `download.file` + `unzip` + `haven::read_dta` or `readr::read_csv` | ZIP + `polars` (CSV) | the ZIP's own `.do`/`.dct` files, which StatCan already ships | `read_csv` |
| IVT tables | `canivt` | none yet (option C) | none | none |
| CKAN / Socrata / ArcGIS portals | `ckanr`, `RSocrata`, or `httr2` on the resource URL | `httpx` + `polars` on the resource URL | `import delimited` on the resource URL | `read_csv` on the URL |
| Bank of Canada Valet | Valet JSON via `httr2`/`jsonlite` | `httpx` + JSON | `import delimited` on Valet's CSV output | `HTTP.jl` + `JSON3` |

- **Why a tool rather than a field in every response.** It keeps every
  response small, and one tool can be tested per source.
- **Scripts follow the house style.** Snippets use the conventions in the
  user's coding standards:
  - Python: `polars` first;
  - R: `cansim`/`cancensus`, native pipe, `janitor::clean_names()`;
  - Stata: `import delimited` with no `cd`;
  - Julia: TidierFiles.

  Each snippet also caches its download to `data/raw/`.
- **Tests.** A test per source renders each language's snippet. A
  scheduled live job runs the R and Python snippets.
- **Effort.** 2-3 days for StatCan, the Census, PUMFs and CKAN in all
  four languages; the rest follow the same pattern.

Adjacent idea for later: export helpers that write a result's rows
directly as Parquet or `.dta` for handoff. These are lower priority than
snippets, because snippets keep the analyst's pipeline reproducible,
while exported files do not.

## 4. Status (2026-09-24)

1. **Done:** census data tables plus IVT routing (option A).
   `statcan_census_tables_search` and `_get_downloads` cover 869 tables
   across 2006, 2011, the 2011 NHS and 2016. A table that exists only as
   IVT gets a canivt snippet.
2. **Done:** reproduction code. `reproduce_code` covers R, Python, Stata
   and Julia. Generated R and Python snippets were run against the live
   sources.
3. **Done, without standard errors:** PUMF phase 2.
   `statcan_pumf_tabulate` computes weighted totals, shares and means
   with DuckDB, from CSV or fixed-width members. It keeps a disk cache
   (`MAPLE_PUMF_CACHE_DIR`; a Docker volume in docker-compose).
   Verified live on LFS and EICS.
4. **Done for three surveys:** standard errors and CVs.
   - **2021 Census:** random groups (`WT1`-`WT16`, divisor 35). This
     reproduces the guide's Examples 1 and 2 exactly.
   - **EICS 2024 and CSWC 2024-2025:** bootstrap weights from the separate
     `*_BSW.txt` file, joined on `PUMFID` (1,000 replicates), divided by
     1,000 and centred on the full-sample estimate, per each guide's
     s. 10.1. The PUMF bootstrap weights are perturbed, so the results are
     comparable to, not identical with, StatCan's official figures.
   - **Not done: SHS.** Its ZIP documents no variance method, so it still
     reports no SE.
5. **Done:** SAS `PROC FORMAT` codebook parser, as a fallback. Every PUMF sampled also ships Stata or SPSS files.
6. **Only if demand appears:** the IVT port (option C).
