### Added

- Chat demo: a daily token budget (`CHAT_DAILY_TOKENS`, default 3,000,000 input plus
  output tokens, summed from the usage of every model call on both backends). A spent
  budget answers 429 with a message before any model call. The counters stay in
  memory and reset on restart, so `chat/README.md` now says the real backstop is a
  spend limit on the API key's workspace.

### Changed

- Chat demo: a series computed by the server (`transform="yoy_pct_change"` and the
  like on WDS, SDMX and Bank of Canada tools) is charted and tabulated in its own unit
  (percent, percentage points, an index), with the server's formula in its notes. The
  published levels follow as a second series while there is room under the
  8-series cap. Before, the panel showed only the levels and ignored `transformed`.

### Fixed

- Chat demo: a failure after a billed model call (while reading the answer or the tool
  results) is no longer refunded against the per-address and daily caps. Only a backend
  failure known to have happened before any billed call is given back.

### Security

- Chat demo: on Render the per-address rate limit reads `CF-Connecting-IP`
  (`CHAT_CLIENT_IP_HEADER`) before `X-Forwarded-For`, whose rightmost entry behind
  Cloudflare may be a shared edge address that put many callers in one bucket. Falls
  back to `X-Forwarded-For` when the header is missing or not an IP address.
- Chat demo: the page sends a full Content-Security-Policy (scripts only from this
  origin, the two pinned cdnjs files and the page's inline script by a SHA-256 hash
  computed at startup; no framing), and every response sends
  `X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin`.
  Model text is sanitised without images, and its links open in a new tab with
  `rel="noopener noreferrer"`.
