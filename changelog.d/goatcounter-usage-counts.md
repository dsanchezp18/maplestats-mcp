### Added

- With `MAPLE_GOATCOUNTER_URL` and `MAPLE_GOATCOUNTER_TOKEN` set, the HTTP server also sends
  each counted tool call to GoatCounter as the event `mcp/<instance>/<tool>` (`/error` on
  failure; `MAPLE_INSTANCE_NAME` labels the host), in batches each minute. `/stats` starts
  again on every restart and knows one host only; the GoatCounter counts persist and add up
  across the Azure and Render instances. Only the registry tool name, outcome, host label
  and time are sent, never arguments or addresses, and visitor counting is off.
- The chat demo's page counts views with GoatCounter, like the website, under a fixed path,
  so the question a `?q=` link carries is not recorded.
