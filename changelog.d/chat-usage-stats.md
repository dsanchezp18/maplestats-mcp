### Added

- The chat demo serves `/stats`: how each question ended (answered, refused and by which
  limit, failed), billed model tokens by kind, model and tool calls with the tools by
  name, the model's stop reasons, the turn number of each question, the p50 and p95 time
  to an answer, the same per UTC day, and how much of today's question and token limits
  is used. It keeps no questions, answers, tool arguments or addresses. With
  `CHAT_USAGE_STATS_FILE` the counts are kept in a file across restarts (the Azure
  deploy mounts the server's file storage at `/data` for it);
  `CHAT_USAGE_STATS=0` turns the route off.
