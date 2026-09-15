# MapleData MCP — Project Guide

Source of truth: Notion page "MapleData MCP" (Programming Hub / Software
Projects & Ideas), last edited 2026-09-14. This guide is a working copy of
that page for local reference during development. When the two diverge,
update this file from Notion rather than editing Notion from memory.

## Properties

| Field | Value |
|---|---|
| Development Stage | Planned |
| Priority | High |
| Project Type | Data product |
| Repository | `maple-data-mcp` |
| Required Skills | Python, APIs, AI, Data engineering |
| Target Audience | Government, Researchers |
| Problem | Canadian public data access is fragmented across Statistics Canada, the Bank of Canada, CMHC, federal/provincial/municipal open-data portals, Census products, PUMFs and legacy dissemination formats. Build one agent-friendly access layer across them. |
| Next Action | Fork the strongest suitable existing Canada MCP implementation and turn it into Daniel's own maintained version. Keep the project name undecided for now (superseded — see naming decision below). Once the product is complete and stable, explore distributing or featuring it through SFU Economics. |

## Current implementation decision

- **Approach:** do not build the Canada MCP from scratch. Start from the
  strongest suitable existing implementation by creating a fork/version,
  then adapt, simplify, extend and maintain it.
- **Naming:** decided 2026-09-14. Full name **MapleData MCP**; repository
  `maple-data-mcp`. Scope is pure Canadian data/statistical analysis (math
  and numbers) — legislation and parliamentary information are explicitly
  out of scope for this project and belong to a separate MCP.
- **Distribution path:** once complete, stable and presentable, explore
  having it featured, shared or otherwise plugged through **SFU
  Economics** — a distribution/visibility route, not an assumption of
  formal institutional ownership or endorsement.
- **Roadmap implication:** prioritize selecting the base repository,
  understanding its license and architecture, establishing the fork, and
  identifying the minimum changes needed for a credible maintained release
  before adding new source coverage.

## Vision

Build the **canonical MCP and data-access layer for Canadian public
data**. Unify the strongest available infrastructure for Statistics
Canada with other major Canadian statistical and open-data systems, so AI
agents and analytical workflows can discover, understand and retrieve
Canadian data through one coherent interface.

Broader than a Statistics Canada MCP — the main project for **all
Canada-related programmatic data access**.

## Core source inventory

### Statistics Canada

- Build best-in-class support rather than a thin API wrapper.
- Benchmark existing StatCan MCP implementations; reuse/mirror the
  strongest ideas.
- Support the Web Data Service / data tables: discovery, metadata,
  retrieval.
- Robust table and cube discovery — users should not need to already
  know a PID.
- Preserve source metadata, provenance, update information and stable
  identifiers.
- Make **StatCan documentation pages first-class and agent-accessible**
  (not optional): table documentation, concepts/definitions, survey and
  methodology pages, classification notes, metadata guides, relevant PDF
  documentation — so the agent can interpret data, not only retrieve it.
- Cover Census data and Census Profile access as a first-class interface.
- Integrate or learn from existing tooling: `statcanR`, `cansim`,
  `cancensus`.

### Bank of Canada

- Add Bank of Canada data access, including Valet/API statistical
  series.
- Benchmark existing Bank of Canada MCP implementations before designing
  the adaptor.

### CMHC

- Add CMHC housing and rental-market data.
- Investigate and reproduce existing community access patterns for
  CMHC data rather than limiting support to obvious downloadable
  files.
- Preserve geographic and time-series metadata needed for housing
  analysis.

### Microdata / CanPUMF

- Add **CanPUMF** support for discovering and accessing Canadian
  public-use microdata and associated metadata/documentation.
- Treat microdata discovery as distinct from aggregate StatCan table
  retrieval.

### CKAN and open-data portals

Build a reusable CKAN adaptor so individual portals do not require
bespoke implementations.

- Federal Government of Canada open-data portal.
- Inventory and support all viable provincial and territorial open-data
  portals.
- Inventory and support major municipal open-data portals.
- Include Alberta open data within this common architecture rather than
  a separate Alberta assistant.
- Detect CKAN capabilities and normalize catalogue search, dataset
  metadata, resources, previews and downloads across portals.
- Allow additional Canadian CKAN portals to be registered with minimal
  configuration.

### Beyond 20/20 and legacy statistical systems

- Investigate support for **Beyond 20/20** files and dissemination
  systems used by Canadian statistical agencies and governments.
- Determine which Beyond 20/20 formats can be parsed directly and which
  require conversion/export workflows.
- Inventory Canadian sources that still publish through Beyond 20/20 or
  related legacy systems.

## Architecture principles

- **One discovery layer, multiple adaptors.** StatCan, BoC, CMHC, CKAN,
  Census, CanPUMF and legacy formats can have source-specific
  implementations behind a common user-facing model.
- **Discovery first.** Users and agents should find the right dataset
  without already knowing table IDs, catalogue IDs or download URLs.
- **Metadata is first-class.** Return definitions, geography, frequency,
  units, release/update dates, source URLs and other provenance alongside
  values.
- **Agent-friendly outputs.** Keep responses compact enough for MCP
  clients while exposing explicit download/resource operations for larger
  datasets.
- **Do not duplicate mature infrastructure unnecessarily.** Benchmark
  existing MCPs, APIs and Canadian open-source packages and adopt their
  strongest patterns.
- **Extensible nationally.** New Canadian agencies and portals should be
  addable as adaptors, not separate projects.

## Related ideas consolidated here

These are subprojects/use cases of this project, not separate Canada-data
projects:

- Canadian data assistants.
- Statistics Canada MCP.
- Alberta open-data assistant.
- Statistics Canada Excel add-in or other analyst-facing interfaces built
  on the same data-access layer.
- Future Canada-related public-data MCP ideas should be evaluated here
  first.

## Existing reference material

- Notion page with prior notes on Statistics Canada tables, identifiers
  and dissemination architecture:
  https://app.notion.com/p/2d14d10b4945809f8808e066cf263234

## Existing projects to absorb / benchmark

The Canada MCP should not rebuild mature pieces blindly. Benchmark
research surveyed the existing landscape of Canada-focused MCP
servers before implementing each source adaptor, to absorb strong
design and reliability ideas rather than reinvent them. The goal
remains one coherent Canada MCP, not a wrapper around a collection of
separate MCPs. Specific repositories, authors, and registry entries
reviewed during this research are not named here — see
[README.md](README.md#acknowledgments) for credit to the projects
whose patterns most directly informed this implementation.

### Primary architectural benchmark

A large modular multi-jurisdiction Canada MCP was found providing a
context layer across Government of Canada, Statistics Canada, Alberta
and Ontario data, combining a local semantic index with live CKAN
searches and direct StatCan WDS retrieval. Especially important for
discovery, ranking, source inspection, querying heterogeneous
resources and traceable citations — the closest available reference
for a cross-source discovery layer once this project has enough
sources to need one.

A second, larger modular FastMCP server was found spanning federal,
provincial and municipal sources, with shared caching, rate limiting,
bilingual response envelopes, tool discovery/orchestration and a
local SQLite datastore. Its reported tool count varied between its
README and its repository description — treat any such count as
project-reported and version-sensitive, not canonical, when comparing
against it. Benchmark the module architecture, discovery layer,
shared infrastructure and source implementations before designing
equivalents (see [`AGENTS.md`](AGENTS.md) for how this repo's own
module pattern turned out).

### Statistics Canada benchmarks

A dedicated StatCan-specific MCP was the main benchmark for this
project's own StatCan module — its WDS/SDMX implementation, table
search, metadata, retrieval patterns, CLI, tool design and reliability
fixes were reviewed before building this project's own adaptor. A
second, smaller StatCan-specific implementation was reviewed for
edge cases but was not a primary architecture dependency.

### Federal Open Government / CKAN benchmarks

Several MCPs wrapping the federal Government of Canada open-data CKAN
API were found and reviewed, ranging from a full catalogue-search
implementation to a minimal four-tool reference wrapper (dataset
search, package lookup, organizations, groups); one repository was
identified as a fork of another rather than an independent
implementation. The multi-jurisdiction benchmark above is also
relevant here, since it handles federal, Alberta and Ontario catalogue
discovery in one shared workflow rather than as isolated portals.

### Bank of Canada benchmarks

Several small Bank of Canada Valet-API MCPs were found and reviewed
for resource/tool design, none large enough to be a primary
architecture dependency. An unmerged Bank of Canada integration
contributed to the primary multi-jurisdiction benchmark above (Valet
series, groups, observations, bounded responses, 404/error handling)
is directly reusable as a reference regardless of whether it is ever
merged upstream.

### Later-release adjacent MCPs

A Parliament MCP wrapping the unofficial OpenParliament.ca API was
found, covering bills, votes, MPs, Hansard, committees and daily
monitoring with caching/rate-limit handling and a best-effort HTML
fallback for full-text Hansard search — relevant to a later
legislation/parliamentary layer, noting the upstream API itself is
unofficial. A small procurement MCP covering CanadaBuys tender
notices and federal contract awards was also found, relevant to later
procurement expansion. A narrow MCP for one specific federal dataset
(cultural facilities) was found and is worth keeping only as an
example of a dataset-specific Canadian MCP, not a general StatCan
architecture reference.

### MCP Registry entries — adjacent, not core launch benchmarks

The official MCP registry surfaced several Canada-labelled servers
that are real leads but do not map directly to the v1 statistical/
public-data core: a Stripe-based Canadian merchant payments MCP
(out of scope — payments infrastructure, not public data), a payroll
calculation utility, a Canadian vehicle-listings/VIN-decode service, an
AI-governance/compliance MCP relevant only to a future regulatory
layer, and a sanctions-list-checking MCP relevant only to a future
compliance lead. Keep these in view for later releases; do not inflate
the core benchmark list with them.

### Gaps not yet matched to a verified dedicated MCP

As of this audit, targeted searches did **not** identify a clearly
relevant dedicated **CMHC MCP** or **CanPUMF MCP**. A search for a
Canada Census MCP returned unrelated/unclear results, so no
Census-specific MCP is recorded here without further verification.
This reflects what was verified in this audit, not a claim that none
exist anywhere.

### Absorption rule

For each launch source, first inspect the best existing implementation
and explicitly decide: **reuse code where licensing and architecture
fit, port the underlying idea, or deliberately replace it** because the
Canada MCP needs a stronger common abstraction. Avoid carrying forward
source-specific quirks that undermine the unified discovery/resource/
metadata interface.

## Initial roadmap

1. Inventory existing StatCan, Bank of Canada, CMHC, Census, CanPUMF and
   Canadian open-data tooling/MCPs.
2. Define the common discovery/resource/metadata interface and adaptor
   architecture.
3. Implement best-in-class StatCan support as the foundation.
4. Add Bank of Canada.
5. Build the reusable CKAN adaptor and inventory federal, provincial,
   territorial and municipal portals.
6. Add Census-specific discovery/access where the generic StatCan layer
   is insufficient.
7. Add CMHC using existing community tooling as an implementation/
   reference benchmark.
8. Add CanPUMF and microdata discovery/documentation support.
9. Research and prototype Beyond 20/20 support.
10. Build downstream interfaces, potentially including Excel or other
    analyst-facing clients, on top of the same infrastructure.

## Launch plan

The v1.0 launch should ship as a complete public product, not a quiet
repository release.

### v1.0 launch package

- Live hosted MCP server that normal users can connect to without local
  installation.
- Polished public website: product, supported sources, connection
  instructions, examples, status, GitHub repository.
- GitHub repository as the technical home for source code, documentation,
  issues, roadmap and contributions.
- Launch blog post: *One MCP to Rule Them All* (see below).
- Several strong cross-source demos showing why a unified Canadian data
  MCP is more useful than separate narrow connectors.

### v1.0 source coverage

- Statistics Canada data tables and metadata.
- Statistics Canada documentation pages, as part of the main release:
  searchable/agent-accessible documentation for concepts, definitions,
  surveys, methodology, classifications, table notes and related
  reference material, with source links preserved.
- Census discovery and access as a first-class interface.
- PUMFs / CanPUMF, including Census PUMFs where publicly available and
  practical to expose.
- Bank of Canada statistical series.
- CMHC housing and rental-market data.
- Government of Canada Open Data portal.
- All 10 provinces, using reusable portal adaptors wherever possible.

Launch proposition: **one AI-native access layer for Canadian public
data**, spanning aggregate statistics, census data, public-use microdata,
housing, monetary/financial data and federal/provincial open data.

### Launch design rule

The product should demonstrate that the user does not need to know which
institution, API or portal contains the answer. A strong launch demo
should ask one substantive Canadian question and transparently combine
relevant sources such as StatCan, BoC, CMHC and provincial data.

### Deferred to v1.x / v2

Do not block the initial launch on lower-priority breadth:

- Territorial open-data coverage and deeper portal support where needed.
- Major municipal open-data portals.
- Beyond 20/20 and other legacy statistical formats.
- Additional specialized federal and provincial agencies.
- Deeper microdata tooling beyond initial PUMF discovery/access.
- Permits and licensing data, where open and technically feasible.
- Legislation and regulatory data, potentially by integrating or sharing
  infrastructure with the existing Canada legislation MCP idea.
- Other high-value administrative domains: inspections, procurement,
  planning, regulatory filings where public access is available.

### Release sequencing

- **v1.0 — national public-data core:** StatCan + Census + PUMFs + BoC +
  CMHC + federal open data + all 10 provinces, with website, hosted
  server, GitHub and launch article released together.
- **v1.x / second release — breadth and legacy systems:** municipalities,
  territories, Beyond 20/20, stronger microdata workflows, additional
  specialized data sources.
- **v2 / third release — broader public-information layer:** permits,
  licensing, legislation, regulations and other public administrative
  information where a coherent agent-facing interface adds clear value.

## Launch blog post concept: "One MCP to Rule Them All"

Centre the project's consolidation thesis rather than present this as
another narrow Statistics Canada MCP.

**Narrative.** Open with a playful Lord of the Rings / One Ring
reference: the proliferation of narrow MCPs has recreated the
fragmentation MCPs were supposed to solve — a StatCan MCP, a Bank of
Canada MCP, open-data connectors, Census tooling, housing sources,
PUMFs, CKAN portals, legacy formats. Each may be useful individually, but
users should not have to choose among many MCPs before asking a
Canadian data question.

Central argument: **centralization of access to Canadian public data is
itself a core design goal.** Canada has rich public data infrastructure,
but it is fragmented across institutions, APIs, catalogues, packages and
file formats. Expose one coherent interface while retaining specialized
source adaptors underneath.

Core framing: **centralize the interface, not necessarily the data.**
Source-specific complexity should be an implementation detail, not a
decision imposed on the user.

**Draft structure — "One MCP to Rule Them All":**

> *Three MCPs for the statisticians under the sky, seven for the data
> portals in their halls of stone...*
>
> Okay, perhaps not quite.
>
> As MCP has made it easier to connect AI agents directly to data, we
> have started building increasingly narrow servers for increasingly
> narrow pieces of the Canadian data ecosystem. There is an MCP for
> Statistics Canada, another for the Bank of Canada, and others for
> open-data portals. Meanwhile, housing data live somewhere else, Census
> data have their own peculiarities, researchers work with PUMFs, and
> some Canadian public data still sit behind legacy systems such as
> Beyond 20/20.
>
> Each tool can be useful. Collectively, however, they recreate an old
> Canadian data problem in a new form: too many places to look, too many
> interfaces to learn, and too many choices before asking a relatively
> simple question.
>
> So the Canada MCP takes the opposite approach: one MCP for Canadian
> public data.
>
> Statistics Canada remains at the centre, but Canadian data do not end
> at Statistics Canada. The project brings together StatCan tables,
> metadata, Census and microdata access; Bank of Canada series; CMHC
> housing data; federal, provincial and municipal open-data portals;
> public-use microdata; Beyond 20/20 and other legacy statistical
> formats; and additional Canadian sources where there is a clear reason
> to support them.
>
> The objective is not to copy all of this data into another database.
> It is to build a common access layer over the infrastructure that
> already exists. An agent should not need to know beforehand whether a
> question requires a StatCan WDS request, a Bank of Canada Valet
> series, a CMHC dataset, a CKAN resource, a Census profile or an old
> statistical file.
>
> Ideally, it should simply ask the Canada MCP.

**Design principle for the launch.** One discovery layer, many
source-specific adaptors. One MCP rather than a collection of narrow
MCPs. Absorb the useful ideas and capabilities of narrower Canadian-data
MCPs rather than forcing users to select among them.

Possible closing line: *One MCP. Canadian public data. As much of it as
I can reasonably connect.*

## Legislation and parliamentary information

Treat as part of the broader Canada MCP rather than a standalone MCP
(deferred to v2, not v1.0 scope per the naming decision above):

- Add authoritative federal statutes and regulations discovery/retrieval.
- Inventory provincial and territorial legislation sources and normalize
  access where feasible.
- Add bills, votes, Hansard, committees and legislative-history sources
  where useful, benchmarking OpenParliament and other existing
  interfaces.
- Preserve jurisdiction, version/effective dates, source URLs and
  legislative provenance.
- Keep legislation/regulatory access behind the same discovery and
  adaptor architecture as the statistical and open-data sources, while
  allowing source-specific tools where needed.

## Updated implementation direction (2026-08-29)

1. **Build a dedicated Statistics Canada MCP first.** Go materially
   beyond existing StatCan wrappers, with especially strong support for
   PUMFs/microdata, Beyond 20/20 and legacy dissemination, and StatCan
   documentation and metadata. Goal: a genuinely best-in-class StatCan
   product that retrieves data and also interprets the concepts, survey
   documentation, classifications, methodology, table notes and microdata
   structure around it.
2. **Still build the holistic Canada MCP**, using the strongest existing
   architecture as the base/benchmark. Treat the dedicated StatCan MCP as
   a first-class component/adaptor inside the broader Canada MCP. Before
   implementation, identify the best existing general Canadian
   public-data MCP architecture, then reuse, fork, port or mirror the
   strongest parts where licensing and design permit, rather than
   rebuilding commodity infrastructure. The holistic product remains the
   end-state: one discovery and metadata layer spanning StatCan, BoC,
   CMHC, CKAN/open-data portals, Census, microdata and legacy systems.
3. **Prioritize CMHC as a high-value greenfield gap.** No verified
   dedicated CMHC MCP was found — one of the clearest opportunities for
   genuinely new coverage. Build a proper CMHC adaptor with discovery,
   geography, metadata and time-series retrieval, and investigate
   existing community CMHC access patterns as an implementation
   reference. Treat as a substantive standalone capability, not a
   token source integration.

## CRTC / telecommunications market data

- Add the CRTC as a potential source adaptor, especially for
  telecommunications pricing and market indicators.
- Prioritize mobile/wireless plan-price series, advertised plan prices,
  data allowances, revenue per GB, usage, subscriber and competition
  indicators from the Communications Market Reports / Canadian
  Telecommunications Market Report and underlying CRTC data collections
  where accessible.
- Investigate whether the CRTC exposes machine-readable tables or
  downloadable datasets behind its current-trends pages, rather than
  relying on PDF/report extraction.
- Also assess low-cost/occasional-use plan reporting and related
  affordability data as useful policy-facing endpoints.

## Additional source roadmap

Extends the Canada MCP beyond the core StatCan / BoC / CMHC / CKAN stack
into regulatory, administrative, market and sector-specific data.
Prioritize sources where the underlying data are structured,
economically useful, and poorly served by generic catalogue search.

### High-priority additions

- **CRTC** — telecommunications and broadcasting market data: plan
  prices, allowances, subscribers, revenues, usage, broadband
  availability, competition, affordability, historical Communications
  Market Report datasets. Prefer machine-readable datasets/data
  dictionaries over report-only ingestion.
- **Canada Energy Regulator (CER)** — oil, natural gas, NGL/LNG,
  pipeline, energy trade, export, price, infrastructure and provincial
  energy-market data. Investigate direct CSV/API and geospatial access.
- **Canada Revenue Agency (CRA)** — T1/T2 tax statistics, tax-filer
  aggregates, income and deduction statistics, benefits, charities and
  other administrative tax datasets. Major non-StatCan economic-data
  source.
- **Innovation, Science and Economic Development Canada (ISED)** —
  spectrum and radio licensing, broadband/connectivity, corporations,
  insolvencies, business and telecom-adjacent administrative datasets.
  Determine which ISED systems merit dedicated adaptors rather than
  generic Open Government access.
- **Office of the Superintendent of Financial Institutions (OSFI)** —
  banks, insurers, federally regulated pension plans, balance-sheet/
  regulatory statistics and financial-system administrative data.
  Complement Bank of Canada rather than duplicate it.
- **Immigration, Refugees and Citizenship Canada (IRCC)** — permanent
  and temporary residents, permits, citizenship, application
  inventories, processing and immigration administrative series.
  Improve discovery across downloadable and report-based products.
- **Health Canada + PMPRB** — Drug Product Database, pharmaceutical
  product/market data, patented medicine prices, pharmaceutical
  expenditures and international price comparisons. Investigate full
  database extracts and stable identifiers.
- **Transport Canada + Canadian Transportation Agency (CTA)** —
  aviation, rail and transport administrative/regulatory data,
  complaints, accessibility, infrastructure and related geospatial/
  downloadable datasets.

### Second-tier sector and regulatory sources

- **Competition Bureau Canada** — merger decisions, enforcement actions,
  market studies and competition-policy information. Evaluate
  structured-data availability; even metadata/document discovery could
  be valuable.
- **Canadian Grain Commission** — grain deliveries, exports, stocks,
  prices, quality and elevator data. Strong niche source for agriculture
  and commodity-market analysis.
- **Agriculture and Agri-Food Canada (AAFC)** — commodity prices,
  livestock, crops, agricultural trade, market information and
  geospatial datasets.
- **Canadian Institute for Health Information (CIHI)** — health
  spending, hospitals, physicians, pharmaceuticals and health-system
  indicators. Map licensing/access constraints and support discovery/
  metadata even where unrestricted retrieval is impossible.
- **Financial Consumer Agency of Canada (FCAC)** — consumer financial
  products, banking fees, mortgages, financial-wellbeing and consumer-
  market research. Useful for affordability and household-finance
  analysis.
- **Canadian Dairy Commission and provincial marketing boards** —
  regulated agricultural prices, quotas, production and market
  information. Treat as a family of niche source adaptors, not a single
  national dataset.
- **Canadian Intellectual Property Office (CIPO)** — patents, trademarks
  and industrial designs. Explore Canadian innovation/IP search and
  machine-readable data access.
- **Employment and Social Development Canada (ESDC)** — Employment
  Insurance administrative data, labour-program statistics, Job Bank and
  occupational information. Distinguish administrative program data from
  overlapping StatCan labour statistics.
- **Elections Canada** — election results, candidates, political
  financing/contributions, polling divisions and electoral geography.
- **Public Services and Procurement Canada / CanadaBuys** — tenders,
  procurement notices, contract awards and procurement metadata. Build
  beyond the narrow existing Canada Tenders MCP benchmark where useful.
- **Treasury Board of Canada Secretariat (TBS)** — proactive disclosure,
  government expenditures, contracts, travel/hospitality, workforce and
  other federal administrative information.

### Implementation rule for these sources

For each agency, first determine the best access path: dedicated
API/adaptor, reusable CKAN/Open Government adaptor, structured
bulk-download parser, geospatial service, or searchable
documentation/index layer. Do not create bespoke MCP tools where the
common discovery/resource/metadata abstraction is sufficient.

### Business registries / identifiers

- **ISED Business Number (BN) validation / lookup** — investigate as a
  source for validating Canadian business identifiers and linking
  business identity data across datasets. The Government of Canada BN
  data-reference standard identifies ISED as the federal lead for BN
  adoption and references a BN Web Validation Look-Up Tool. Determine
  any public/programmatic endpoint, authentication required, permitted
  uses, returned fields, rate limits, and whether it can complement
  Corporations Canada / provincial registry data. Reference:
  https://www.canada.ca/en/government/system/digital-government/digital-government-innovations/enabling-interoperability/gc-enterprise-data-reference-standards/data-reference-standard-business-number.html
- **Corporations Canada / ISED corporate search** — investigate the
  public federal-corporation search and underlying endpoints separately
  from BN validation: corporation number, legal name, status, registered
  office, directors/individuals with significant control where publicly
  available, filings and downloadable corporate records. Reference:
  https://ised-isde.canada.ca/cc/lgcy/index.html?lang=eng

### ISED / CIPO patents data

- Add ISED/CIPO patent data as a first-class specialized federal source,
  alongside the CRTC telecommunications-market data work.
- Inventory available machine-readable interfaces, bulk downloads and
  search endpoints for Canadian patent records before choosing the
  adaptor design.
- Support discovery and retrieval by patent/application number,
  title/keywords, applicant/assignee, inventor, filing/publication/grant
  dates and patent classification where available.
- Preserve patent metadata, source links and record provenance; expose
  legal/status, citation and related-document fields where the
  underlying source makes them available.
- Design the adaptor so patent search participates in the same common
  discovery/resource/metadata interface rather than becoming a
  standalone tool silo.
