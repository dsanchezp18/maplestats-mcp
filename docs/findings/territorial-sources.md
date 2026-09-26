# Territorial sources

Findings moved from [`ROADMAP.md`](../../ROADMAP.md) on 2026-09-25. Each section
records what was checked, against which live responses, and what the
module does about it. Dates are when a finding was confirmed; the
status in `ROADMAP.md` is the current one.

## Yukon

**Status:** Shipped.

open.yukon.ca, CKAN Action API: `ckan_*` (`portal="yt"`), 8 tools.
English-only (site UI is bilingual-chrome only; dataset content is not).
3,841 datasets. Checked 2026-09-20 for a `ckan_datastore_search` tool to
match the rest of the CKAN family: this deployment genuinely has no
DataStore extension installed at all -- `datastore_search` answers `"Bad
request: Action name not known: datastore_search"`, confirmed live -- so no
tool was added here, unlike every other CKAN portal in this project.

## Nunavut

**Status:** Blocked.

Investigated 2026-09-19: no dedicated open-data portal exists
(`opendata.gov.nu.ca`/`data.gov.nu.ca` don't resolve). The Government of
Nunavut's own site (`gov.nu.ca`), including its Nunavut Bureau of
Statistics/economic-data pages, sits behind a bot-detection interstitial
that did not clear even after 15s in a real rendered browser, and returns
HTTP 403 to a plain HTTP client — genuinely blocking automated access, not
just a slow load. Re-investigate only if a dedicated portal is later
launched or the bot-check is confirmed to allow a properly-identified client
through.
