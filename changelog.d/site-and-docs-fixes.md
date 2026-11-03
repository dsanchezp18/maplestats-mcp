### Fixed

- Website: the About page links Kole Harvey's `statcan-mcp` and `bank-of-canada-mcp` at their
  current repositories (the old links were dead), and the Connect page links OpenAI's moved
  developer-mode article, in French on the French page. The benchmark tables use decimal
  commas on the French page, and the count of answers read by hand says it includes the
  updated MapleStats runs. The French home page offers French example questions and says, under
  the tool search, that tool descriptions are in English. Chart labels that wrap onto several
  lines are read with a space between the lines by screen readers. Several French phrasings
  were corrected, and the Contributing page no longer lists Python versions that can go out of
  date.
- README: the Docker Compose command sets `MAPLE_AUTH_TOKEN` first, without which the server
  refuses to start, and the lint and format commands include `scripts`, as CI runs them.
- SECURITY.md: the chat demo is in scope.
