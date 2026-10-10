# MapleStats chat demo

A one-page chat where a cheap LLM answers questions about Canadian open data by
calling the public MapleStats MCP server. It exists so a visitor can see the MCP
working without installing anything. It is a separate service: the MCP server is
untouched, and this one holds the model API key.

## Run it locally

```bash
cd chat
uv sync
CHAT_API_KEY=sk-ant-... uv run uvicorn app:app --port 8081
```

Open <http://localhost:8081>. Run the tests with `uv run pytest`.

## Choose the model

Set three environment variables. Nothing else changes.

| Backend | `CHAT_PROVIDER` | `CHAT_MODEL` | `CHAT_BASE_URL` |
|---|---|---|---|
| Claude Haiku 5.5 (default) | `anthropic` | `claude-haiku-5-5` | unset |
| DeepSeek | `openai` | `deepseek-chat` | `https://api.deepseek.com` |
| Kimi | `openai` | a Kimi K2 model id | `https://api.moonshot.ai/v1` |
| GLM | `openai` | a GLM model id | `https://api.z.ai/api/paas/v4/` |

The Anthropic path uses Anthropic's MCP connector, so Anthropic's servers call the
MCP URL and the public endpoint must be reachable. The `openai` path runs the tool
loop here, so it also works with a local MCP server (`CHAT_MCP_URL`). Model ids,
base URLs and prices for the non-Anthropic providers change; check each provider's
page.

## Guards

The endpoint is public and every call costs money. Defaults, all overridable by
environment variable: 20 questions per address per hour (`CHAT_RATE_PER_HOUR`), 500
per day in total (`CHAT_DAILY_LIMIT`), 1,000 characters per user message,
16,000 per assistant reply, 120,000 per conversation, a 512 KiB request body,
8 user turns per conversation, 2,000 output tokens, 8 tool steps. Also set a monthly spend limit on
the provider's dashboard; the in-memory counters reset on every restart.

`CHAT_ALLOWED_ORIGINS` (comma-separated) lets another site call `/api/chat` from a
browser; leave it unset when the page is served from this service.

Conversation limits can be set with `CHAT_MAX_MESSAGE_CHARS`,
`CHAT_MAX_ASSISTANT_CHARS`, `CHAT_MAX_CONVERSATION_CHARS` and `CHAT_MAX_BODY_BYTES`.
Messages must alternate between user and assistant, starting and ending with user.
