### Security

- `plan_query` reads at most the first 2,000 characters of a question. The planner
  runs on the event loop and its time grew faster than the length (13.5 s at
  400,000 characters, minutes at 1 MB), so one oversized question under the 2 MB
  body cap stalled every request on a hosted server, health checks included.
- `wds_query_series` workers ask the kernel to kill them first if the container
  runs out of memory, so a runaway query fails on its own instead of taking the
  server, and every caller's session, down with it.
