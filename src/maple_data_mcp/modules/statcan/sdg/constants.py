"""Constants for StatCan's Sustainable Development Goals (SDG) Data Hub.

Confirmed live 2026-09-21. StatCan's own SDG Data Hub landing page
(www144.statcan.gc.ca/sdg-odd/) links to two separate "Open SDG"
platform sites, each a static site (front end + data) hosted on
GitHub Pages, not a StatCan-run API host: the Canadian Indicator
Framework (86 indicators) and the Global Indicator Framework (251
indicators, Canada's reporting against the UN's own indicator set).
Both sites embed their real data API base URL directly in their own
page JavaScript (`opensdg.remoteDataBaseUrl`) rather than publishing
it as documentation -- confirmed live by fetching each site's HTML
and reading that config value, since the two custom domains
(sdgcif-data-canada-oddcic-donnee.github.io,
sdggif-data-canada-oddcmi-donnee.github.io) do not themselves serve
the JSON, only the front end that reads it from a third, shared
GitHub Pages host under different repo-path prefixes.

Real quirk: the two frameworks' per-indicator metadata JSON use
genuinely different field names for the same concepts, confirmed
live -- Canadian: `sdg_goal`, `target_id`, `national_indicator_
description`, `published`. Global: `SDG_GOAL`, `SDG_TARGET`,
`STAT_CONC_DEF`, no `published` field at all. Both frameworks do
share `goal_number`/`target_number`/`indicator_name`/`reporting_
status`/`computation_units`/`source_url_N` (numbered 1, 2, ...), so
this client normalizes to those common fields rather than exposing
each framework's full, differently-shaped raw metadata.

Standard HTTP 404 for an unknown indicator code (a plain static file
host, not one of StatCan's other quirky embedded-error APIs).
"""

FRAMEWORK_BASE_URLS = {
    "canada": "https://sdg-data-canada-odd-donnees.github.io/cif-data-donnees-cic",
    "global": "https://sdg-data-canada-odd-donnees.github.io/sdg-data-donnees-odd",
}

RATE_LIMIT_SOURCE = "statcan-sdg"
RATE_LIMIT_PER_SECOND = 5.0
RATE_LIMIT_CAPACITY = 5.0

# SDG indicators are updated on their own annual/multi-year reporting cycle.
CACHE_TTL_INDEX_SECONDS = 24 * 60 * 60  # 24h
CACHE_TTL_METADATA_SECONDS = 24 * 60 * 60  # 24h
CACHE_TTL_DATA_SECONDS = 24 * 60 * 60  # 24h

SEARCH_LIMIT_DEFAULT = 10
SEARCH_LIMIT_MAX = 100

# Confirmed live: numbered source_url_N/source_organisation_N/etc. fields
# go up to N=5 for the Canadian framework and N=9 for the Global one.
MAX_SOURCES = 20
