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
browser; leave it unset when the page is served from this service. `/api/chat`
answers 415 to any POST whose `Content-Type` is not `application/json`: browsers
send other types (such as `text/plain`) cross-site without a preflight, so a
third-party page could otherwise spend the budget from its visitors' browsers.

`CHAT_TRUST_PROXY_HEADERS` decides whether the per-address limit reads the
caller's address from `X-Forwarded-For` (one hop from the right, as the MCP server
does) or uses the socket address. It defaults to `1` when the `RENDER` variable is
set, because Render's proxy always sits in front, and to `0` everywhere else: run
directly, as in the section above, any caller could write that header and choose
its own bucket. Set it to `1` yourself only behind a proxy you control that appends
the real address.

Conversation limits can be set with `CHAT_MAX_MESSAGE_CHARS`,
`CHAT_MAX_ASSISTANT_CHARS`, `CHAT_MAX_CONVERSATION_CHARS` and `CHAT_MAX_BODY_BYTES`.
Messages must alternate between user and assistant, starting and ending with user.
