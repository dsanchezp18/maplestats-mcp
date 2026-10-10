# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [semantic versioning](https://semver.org/) while it is in beta.

## [Unreleased]

### Added

- `cra_charities` module: search CRA's annual List of charities by name, city, province
  or designation, look one up by business number, and list its directors and officers
  (open.canada.ca DataStore, Open Government Licence - Canada).

## [0.3.0] - 2026-10-10

### Added

- Issue reporting: a `docs://report-issue` resource and server instructions
  for drafting a bug report when a tool misbehaves. The client shows the final
  text and files it only after the user approves that exact text.
- Prompts follow `lang`, with French bodies, and the eight `docs://` resources
  have French twins.
- Planner: a taxation topic (CRA T1, TFSA, GST/HST, charities) and routes for
  bc_environment, eccc_datamart, health_products and oeb.
- Earthquakes: each result carries a `lookup_id` (the UTC minute the service
  accepts as `eventid`).
- Website: "See it in action" section linking a chat demo, and Claude and
  ChatGPT custom-connector steps on the Connect page.
- Website: touch icon, favicon fallback and web manifest; sitemap `lastmod`.
- Website: a privacy page. Server error logs keep only the exception type, not
  tool arguments or error text.
- Security policy, code of conduct and this changelog. Dependabot keeps the
  pinned actions, Docker base image and Python dependencies current.

### Changed

- Website: moved to <https://maplestats.danielstats.io/>. The old GitHub Pages
  address redirects there, and the hosted server accepts browser calls from
  the new domain only (plus localhost).
- Website: the FAQ's "last updated" date and the About page's "checked in"
  month come from the build date.
- StatCan census notes point `census_tables` users to the 2021 profile.

### Fixed

- Hosted server: rate limits read `X-Forwarded-For` from the right
  (`MAPLE_TRUSTED_PROXY_HOPS`) and apply before the token check; timed-out
  calls count in `/stats`.
- Upstream XML is parsed with defusedxml (Borealis, StatCan Daily, WFS,
  electricity). Bulk downloads and unpacked ZIP members are capped at the
  cache size, and failed unpacking raises typed errors and cleans up.
- Earthquakes: catalogue ids are refused with a message naming the accepted
  minute form. EPCOR: `as_of` is the newest day with a value. Transit: exo's
  moved GTFS feeds.

## [0.2.0] - 2026-10-04

### Added

- 358 tools in 69 modules.

### Changed

- French throughout: errors, notes, provenance, limits and licences of every
  module, the planner's plans and `reproduce_code`'s notes, and the French
  website pages.
- Search: more French function words as stop words, with a parity test for
  the in-page search.
- README: current tool and module counts, every module in the coverage table.
- FAQ: sources not built or removed, and new sources' reuse conditions.

## [0.1.1] - 2026-09-28

### Added

- Case-study pages ("Demos") and release notes on the website.
- Issue templates for bug reports and source requests.
- Registry and listing badges (PyPI, MCP Registry, Smithery, Glama, M8ven).

### Changed

- Near-duplicate Statistics Canada, RDaaS, Bank of Canada and CKAN tools
  merged.
- The three visible tools' descriptions sharpened; English tool discovery
  tested against 98 realistic questions.
- Bank of Canada list tools accept `limit` without a query.

### Fixed

- CDC price CSV with French headers is accepted; an empty Edmonton Police
  Service load-date table now raises a clear "reload in progress" error.

## [0.1.0] - 2026-09-27

First public release: one MCP server for Canadian open data, with
`plan_query`, `search_tools` and `call_tool` in front of every module,
published to PyPI and the MCP Registry.

### Added

- Statistics Canada, Bank of Canada, CMHC, federal agency, provincial,
  territorial and municipal modules, and the CKAN, ArcGIS Hub and Socrata
  portal modules.
- Read-only annotations on every tool.
- PMPRB and Parliamentary Budget Officer modules.
- The bilingual website, generated from the running server.

### Fixed

- Statistics Canada WDS observation release times are read as Eastern time.

[Unreleased]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/dsanchezp18/maplestats-mcp/releases/tag/v0.1.0
