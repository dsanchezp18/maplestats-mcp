### Changed

- The chat demo moves to Azure Container Apps (Canada Central), next to the MCP server, so it no longer sleeps between visitors. It still runs Claude Haiku 5.5, now at medium effort with up to 4,000 output tokens per model call and 12 tool steps per answer (were low, 2,000 and 8), so questions that need several lookups finish more often. The page now lists disclaimers above the conversation: answers can be wrong, MapleStats is not affiliated with Statistics Canada or any government agency, answers are not advice, questions go to Anthropic, and the demo is rate-limited.
