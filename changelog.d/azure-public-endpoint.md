### Changed

- The public endpoint is now `https://mcp.maplestats.danielstats.io/mcp`, an always-on
  server on Microsoft Azure (Canada Central), so the first request after a quiet spell no
  longer waits up to a minute. Limits are unchanged (60 requests a minute per client,
  `statcan_pumf_tabulate` off). `server.json`, the README, the Connect, FAQ and privacy
  pages and the chat demo use it; `https://maplestats-mcp.onrender.com/mcp` keeps working
  as a backup.
- The server instructions and `plan_query`'s guidance describe what `check_answer` does
  instead of telling the assistant to call it before every reply.
