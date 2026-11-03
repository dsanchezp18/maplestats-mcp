### Fixed

- `statcan_surveys_search_surveys`: StatCan's survey directory answers 404 since 2026-10-29.
  The search now lists surveys from IMDB's alphabetical index instead (917 surveys, active
  and inactive, same ids), and says so in `provenance.limits`.
- `wds_get_data_from_vectors` and the other vector tools refuse more than 300 vectors, and
  vector ids that are not positive 32-bit numbers, before calling StatCan. StatCan answered
  them with HTTP 416 (reported as an upstream error to retry) and a "JSON syntax error".
- CMHC: an HTTP 200 error page in place of a province's metropolitan area list is no
  longer cached for a day, which refused valid ids such as Toronto's meanwhile. Field codes
  are upper-cased on every path (`timeseries` works like `TIMESERIES`).
- `call_tool`: a switched-off tool (`wds_query_series`, `statcan_pumf_tabulate` on the hosted
  server) says it is switched off and what to use instead, rather than "unknown tool". An
  unknown name is echoed back cut to 100 characters. Calling `call_tool` or `search_tools`
  through `call_tool` is an `invalid_input`, without the advice to retry.
- `search_tools` answers "No tools matched" with a suggestion instead of an empty result,
  and reads at most 500 characters of a query.
- `plan_query` leaves out tools this server has switched off, so a hosted plan no longer
  sends the model to `statcan_pumf_tabulate`.
- `rdaas_get_classification_index_entry` now carries `provenance` (source, licence and
  URL), the one tool that had none.
- The reproduction script for CIPO patent data carries the RapidSSL intermediate
  certificate itself, instead of downloading it over plain http and trusting it.
- The HTTP server sends `X-Content-Type-Options: nosniff` and HSTS on every response.
- Docker: the server image creates `/data/cbsa_tariff`, which `docker-compose.yml` uses as
  the CBSA tariff cache; it was owned by root, so every `cbsa_tariff_` tool failed under
  compose. Compose keeps it in a named volume.

### Changed

- CI tests Python 3.15, which both Docker images run since a Dependabot update; the package
  lists 3.15 as supported. The release workflow refuses a tag on a commit that is not on
  `main`.
