# PUMFs and Beyond 20/20: scope

Scoped 2026-09-24. Every finding below was checked against the live
StatCan site that day unless marked otherwise.

## What exists today

### PUMFs (public use microdata files)

- **Discovery already works.** `statcan_reference_search_data` returns
  StatCan data products tagged with the category "Public use microdata".
  The query "public use microdata file" matched 144 products. Examples
  include the Labour Force Survey (`71M0001X`), Census (`98M0001X`),
  Canadian Community Health Survey (`82M0013X`), Survey of Household
  Spending (`62M0004X`) and General Social Survey (`45-25-0001`).
- **Several PUMFs are free direct downloads.**
  - Labour Force Survey: one zip per year (`2021001/hist/2025-CSV.zip`,
    about 30 MB) holding 12 monthly CSVs of about 12 MB each. A fixed-width
    PRN twin is also offered. The current year is published month by month
    (`2021001/2026-05-CSV.zip`).
  - Census: individuals and hierarchical files for 1991 to 2021 are listed
    on one page (`98m0001x/index-eng.htm`). The 2021 individuals zip is
    182 MB.
- **The codebooks can be read by machine.** The LFS zip includes
  `Documents/LFS_PUMF_EPA_FGMD_codebook.csv`. Each variable has a row with
  its field number, position, length, name, EN/FR label, EN/FR universe and
  EN/FR notes. Rows for its value codes follow. There is also a
  record-layout CSV and bilingual user-guide PDFs. Other surveys have not
  been checked for the same structure.
- **Not verified:** the download formats for CCHS, GSS, SHS and the other
  PUMFs. Some may be distributed only through the Data Liberation
  Initiative or ODESI, which require an academic login. A per-survey
  inventory is part of phase 1.

### Beyond 20/20

- **At StatCan, every IVT file checked has an open-format twin.** Census
  data tables offer CSV, TAB and SDMX XML downloads alongside the IVT
  (Beyond 20/20) file for the same table. This was checked on one table
  per census year: 2016 (PID 110192: CSV 0.75 MB, IVT 1.26 MB, SDMX
  1.45 MB) and 2006 (PID 89060). So the StatCan census tables checked here
  never require reading an IVT.
- **IVT is a proprietary binary format.** StatCan's own download page says
  it needs the Beyond 20/20 Table Browser, a Windows application. I don't
  know of a published specification or an open-source parser, but I have
  not verified that.
- **Coverage gap.** The existing census tools cover Census Profiles, not
  the census data tables (cross-tabulations) where these downloads live.

## Proposed approach

### PUMFs: three phases

**Phase 1: discovery and metadata. Small, no new dependencies.**
Add a `statcan_pumf` module:

- `pumf_search(query)`: search StatCan data products and keep only those
  categorized as public use microdata. For each product, return the
  catalogue number and its editions.
- `pumf_get_product(catalogue_number)`: read the product page and return
  its editions, download links, formats and sizes (sizes from HEAD
  requests), plus whether the files are a direct download or need
  DLI/ODESI access.
- `pumf_get_codebook(catalogue_number, edition, variable_query)`: download
  the zip once, cache it on disk, and parse the codebook CSV into
  variables with EN/FR labels, universes and value labels. Search it by
  keyword.

This phase answers "which survey has variable X, and what do its codes
mean?" without anyone opening a PDF.

**Phase 2: weighted tabulation. Medium effort, adds a dependency.**
Add `pumf_tabulate(catalogue_number, edition, file, rows, columns, filters,
statistic)`. It computes weighted counts, means or shares directly from
the cached CSV inside the zip, using `polars` or `duckdb` lazy scans so a
182 MB file never has to fit in memory.

- A small per-survey configuration names the weight variable (for example
  LFS `FINALWT`), the period columns and the geography columns.
- Start with LFS and the 2021 Census individuals file, then add CCHS, SHS
  and GSS through configuration only.
- Return the unweighted cell count next to every estimate, and flag any
  cell below a minimum-count threshold instead of reporting it silently.
- Never return raw microdata rows beyond a small sample.

**Phase 3: variance. Deferred.**
The LFS PUMF has no bootstrap weights, so standard errors cannot be
computed directly. Until a survey publishes replicate weights, return the
point estimate with a note pointing to the CV (coefficient of variation)
tables in that survey's user guide. Do not invent a standard error.

### Beyond 20/20

1. **Do not build an IVT parser.** The format is proprietary, and StatCan
   publishes the same tables as CSV and SDMX.
2. **Add census data tables instead.** Build a tool that lists the census
   data tables for each census year (2006, 2011, 2016, 2021) and returns
   the CSV or SDMX download link, reusing the existing census-geography
   tools. This removes StatCan's need for Beyond 20/20.
3. **Inventory the IVT-only publishers.** Survey provincial statistics
   bureaus, archived StatCan E-STAT and CANSIM II products, and other
   agencies. Give each IVT-only source its own ROADMAP row, marked Blocked
   with a conversion note, unless it also publishes an open format.

## Decisions needed

- **Where the microdata cache lives when hosted.** Phase 1 caches zips up
  to about 200 MB each on disk. The hosted server needs a persistent
  volume, or it has to accept re-downloading after each restart.
- **Which analysis engine to add for phase 2:** `polars` or `duckdb`.
  Both can scan a CSV inside a zip without loading all of it. DuckDB can
  also run SQL-style group-bys.
- **Which PUMFs come first.** The suggested order is LFS, then the 2021
  Census, CCHS and SHS.

## Rough effort

| Piece | Effort | Notes |
|---|---|---|
| PUMF phase 1 (discovery, product pages, codebooks) | 1-2 days | Per-survey page quirks drive the time |
| PUMF phase 2 (weighted tabulation, LFS + Census) | 2-3 days | Plus 0.5 day per extra survey config |
| Census data tables (Beyond 20/20 replacement) | 1-2 days | Legacy ColdFusion pages, like the Census Profile module |
| IVT-only publisher inventory | 0.5-1 day | Research only |
