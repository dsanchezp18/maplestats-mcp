### Fixed

- The hosted server on Azure rate-limited every caller together: its per-client limit
  (120 requests a minute) keyed on the address the app's connections come from, which
  is Container Apps' ingress, not the caller. The Azure deploy now trusts the one
  `X-Forwarded-For` entry the ingress appends (`MAPLE_TRUST_PROXY_HEADERS=1`, one hop),
  so each caller has its own limit. On 2026-11-20 the deploy's live check met refusals
  on six steps (`ab_wildfire_get_fires`, `nrcan_energy_use_list_tables`,
  `feedback_draft_issue`, `docs_list_resources`, `rdaas_get_term_exclusion`,
  `rdaas_get_classification_indexes`); each passed when called again.
- The live check against a hosted server tells a refusal from a failure: it records
  each error response's HTTP status, waits as a 429's Retry-After asks (longer after a
  503 or an ingress error), tries three times, and names the statuses when a call still
  fails. Before, the retry came 2 s later and the status was lost.
- The `sdmx_get_data` live step accepts the refusal in WDS's words: behind StatCan's
  captcha the tool answers from WDS, which refuses an unpublished series differently
  from SDMX.

### Added

- `/stats` counts requests the HTTP layer refused, by reason only (`rate_limited`,
  `client_busy`, `server_busy`), in memory.
