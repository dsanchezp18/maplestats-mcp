# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [semantic versioning](https://semver.org/) while it is in beta.

## [Unreleased]

### Added

- Security policy, code of conduct and this changelog.
- Website: touch icon, favicon fallback and web manifest; sitemap `lastmod`.

### Changed

- Website: the FAQ's "last updated" date and the About page's "checked in"
  month come from the build date.

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

[Unreleased]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/dsanchezp18/maplestats-mcp/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/dsanchezp18/maplestats-mcp/releases/tag/v0.1.0
