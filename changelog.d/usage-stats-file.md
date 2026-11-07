### Added

- `MAPLE_USAGE_STATS_FILE`: the `/stats` call counts (per tool and per UTC day) can be
  kept in a JSON file, read at startup and saved every minute and on exit, so a deploy
  or restart no longer starts them from zero. Processes sharing the file add their
  counts together, which keeps the calls served by both revisions during a rollout.
  The hosted Azure server keeps it on its file share at `/data/usage/stats.json`;
  `docker-compose.yml` uses a named volume. Days are now kept for 400 days, not 90.
