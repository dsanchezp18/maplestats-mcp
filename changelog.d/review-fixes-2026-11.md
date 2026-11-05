### Changed

- The Docker image now sets `MAPLE_REQUIRE_AUTH=1`: it listens on every
  interface, so it refuses to start without `MAPLE_AUTH_TOKEN` unless a
  deployment opts out with `MAPLE_REQUIRE_AUTH=0` (the public Render and Azure
  deployments do).
- Docker images are pushed and deployed to Azure only after CI passes on main,
  from the commit CI tested. Before, they were built on the same push as CI
  and deployed even when the tests failed.
- `wds_get_data_from_vectors` refuses more than 3,000 periods, or more than
  60,000 observations in total (vectors times `latest_n`), instead of returning
  hundreds of MB inline; `wds_get_full_table_download` covers larger requests.
- `fcac_search_bank_accounts` refuses `max_monthly_fee` and
  `sort="monthly_fee"` for savings accounts, whose search results carry no fee.
  Before, the filter dropped every account and reported none matching.

### Fixed

- `check_answer`: a Bank of Canada figure cited without a period is compared
  with the latest observation. Before, it passed whatever its value. A period
  it cannot read is reported, and a figure it could not re-read (Valet or WDS
  down) gets a note instead of passing silently. A newer period is found by
  date, not by label, so a quarter such as 2026-Q3 no longer reads as newer
  than the month 2026-07.
- `statcan_pumf_tabulate`: a mean leaves out the value variable's reserve codes
  (valid skip, not stated, don't know and the like, as the codebook labels
  them), which inflated means by orders of magnitude.
- `reproduce_code`: the R script for StatCan tables and vectors keeps
  suppressed observations (missing `val_norm`) with their status and symbol,
  as the tool and the other languages do. The WDS vector scripts in R, Python,
  Julia and Excel skip a vector WDS could not serve instead of failing on it.
- `telecom_prices`: numbers written as French text (`59,97 $`, `1 234,5`) are
  read with a decimal comma. Before, `59,97 $` became 5997.
- `ab_wildfire`: `date_basis="assessed"` counts Alberta calendar days. The
  assessment time is UTC, and the bounds were UTC midnight, 18:00 the
  evening before in Alberta.
- `dfo_iwls_get_water_levels`: when a date-only `end` one day past the 7-day
  cap is cut back, `limits` names the hours that were not fetched.

### Security

- HTTP mode refuses `/mcp` request bodies over 2 MB (413, or a disconnect for
  a chunked body). The MCP SDK read any body whole, so a few large posts could
  run a small instance out of memory without a token.
- The rate limit counts an IPv6 address as its /64 network, so one caller can
  no longer use a fresh bucket per address. Expired clients are swept once
  per window instead of on every request.
- The ZIP reader's search for a resume point inflates at most 16 MB per step,
  like the rest of the reader, instead of without limit.
- New `MAPLE_MAX_REQUESTS_PER_CLIENT` (off by default) caps the requests one
  client may hold in flight, for deployments where callers do not share
  addresses.
