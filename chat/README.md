# MapleStats chat demo

A one-page chat where a cheap LLM answers questions about Canadian open data by
calling the public MapleStats MCP server. It exists so a visitor can see the MCP
working without installing anything. It is a separate service: the MCP server is
untouched, and this one holds the model API key.

## What a visitor sees

Under each answer, a panel with three tabs, modelled on Eurostat Assistant's chat
(ainergy-hub/eurostat-assistant):

- **Chart**: every series the tools returned, one line chart per unit (a bar when a
  series has a single value).
- **Table**: the same values, sortable and filterable, with a CSV download.
- **Sources**: per series, the table number and title linked to the StatCan page, the
  vector, geography, unit, frequency and release date, the reading notes, the cautions
  for those tables, and the URL of every call behind the answer.

The panel is built by `results.py` from the tool results, not from the model's text, so
it shows what the data server returned even when the answer misquotes it. It reads
StatCan WDS and SDMX series (with the `context` the server attaches) and Bank of Canada
Valet series; any other tool with provenance appears under Sources. When the model asks
for a computed series (`transform="yoy_pct_change"` and the like), the panel draws the
computed values in their own unit (percent, percentage points, an index) with the
server's formula in the notes, and adds the published levels as a second series while
there is room (at most 8 series per answer). The page draws the
charts itself (inline SVG, no chart library) and builds every element from text, never
from HTML in a result. The conversation is kept in the browser's local storage; **New
chat** clears it. **Theme** switches light and dark.

Under the panel, when the answer fetched data:

- **Get the code**: the scripts `reproduce_code` writes for one data call behind the
  answer (R, Python, Stata, Julia and an Excel Power Query), one tab each, with Copy and
  Download, the packages each needs, the URL they fetch and the server's notes.
- **Download Excel**: the rows of that call as an .xlsx from `reproduce_workbook`
  (delivered as base64 and saved by the page), with the server's notes and, when the file
  holds only the first rows, a pointer to the Power Query script for all of them.

The answer records its data calls (`calls` in the result: tool name and arguments, only for
calls that succeeded and returned provenance, at most 8; discovery and reproduce tools are
never listed). With several, a list picks one. The page posts it to `POST /api/code` or
`POST /api/workbook` (`{"tool_name", "arguments", "lang"}`, plus `"language"` for code),
and this service asks the MCP server through `call_tool`, as the `openai` backend calls
tools. No model is called, so the exports never touch the question or token limits; they
have their own limit, 30 per address per hour (`CHAT_EXPORT_PER_HOUR`), the same
`application/json` rule as `/api/chat`, a 64 KiB body, and a 120 s wait for the server
(`CHAT_EXPORT_TIMEOUT_SECONDS`). A tool name must look like a MapleStats data tool. Only the
fields the page draws are passed back; the server's own error (a tool with no script, for
example) is shown as text, cut at 600 characters.

**Français** in the header switches the page to French (and **English** back); the first
visit follows the browser's language, and the choice is kept in this browser. Every string
the page writes is in both languages. A French page sends `"lang": "fr"` with each
request: the limits and errors come back in French, the model's system prompt gets one more
block (after the cached one) telling it to answer in French and pass `lang="fr"` to
`plan_query` and every tool, and the export calls pass `lang="fr"` to the reproduce tools,
whose notes and workbook labels are then French. The StatCan notice stays bilingual.

## Run it locally

```bash
cd chat
uv sync
CHAT_API_KEY=sk-ant-... uv run uvicorn app:app --port 8081
```

Open <http://localhost:8081>. Run the tests with `uv run pytest`.

## While it works

A question can take a few seconds or a couple of minutes (every tool call is a model
turn, and StatCan's census profile service alone takes 30 to 45 s a call), so the page
shows progress instead of a blank wait. It posts to `POST /api/chat/stream`, which runs
the same turn as `POST /api/chat` (same guards, limits, counts and result) and answers
with newline-delimited JSON:

- `{"type": "tool", "name": ...}` when a tool call starts (the real tool's name, not
  `call_tool`);
- `{"type": "text", "delta": ...}` for a piece of the model's text (the page shows it
  as plain text and replaces it with the finished answer; text written before a tool
  call is thinking aloud and is cleared at the next `tool` event);
- `{"type": "ping"}` every `CHAT_STREAM_PING_SECONDS` (10) of quiet, so no proxy closes
  an idle connection;
- last, either `{"type": "final", ...}` with the `/api/chat` body, or `{"type": "error",
  "status": ..., "error": ...}`.

A request the guards refuse (415, 413, 400, 429) is an ordinary JSON error with its
status, sent before any stream starts. The Anthropic backend streams the model call
(`client.beta.messages.stream`); billing, counts and the answer are read from the
finished message exactly as before. The `openai` backend reports each tool call but
not the text. `POST /api/chat` stays for scripts and tests.

## When StatCan refuses automated requests

Since November 2026 Statistics Canada answers some automated requests with a check only
a person in a browser can pass (the MCP server never tries to get past it). The server's
public `/stats` lists the StatCan path groups that answered with it in the last 15 minutes
(`upstreams.challenged_paths`). While it lists any, the page shows a short notice in English
and French: StatCan's data service is temporarily refusing automated requests, so some
answers may be unavailable or come from other sources.

The page asks `GET /api/status` on load and every minute; it answers
`{"upstream_blocked": true|false}`. The chat service reads `/stats` (the MCP server's origin,
or `CHAT_MCP_STATS_URL`) at most once a minute, for at most 3 seconds and 2 MB, and a failed
read means no notice: the question routes never call it, so a slow or dead data server cannot
hold an answer up. The notice shows only once the MCP server reports `challenged_paths`; an
older server has no such field and the page stays as it was.

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

## Usage counts

`/stats` answers with aggregate counts, as the MCP server's `/stats` does:

- how each request to `/api/chat` ended: `answered`, `empty`, `failed`, `unavailable`,
  `limited_address`, `limited_daily`, `limited_tokens` or `rejected`;
- billed tokens by kind (`input`, `output`, `cache_write`, `cache_read`);
- model calls, tool calls and tool errors, the tools by name, and the model's stop
  reasons;
- the turn number of each question, and the p50 and p95 time to an answer;
- `per_answer`: how many model requests, tool calls and model steps each answered question
  took, as p50, p95 and a histogram (a count of 30 or more is one bin, `30+`, reported as
  30). A model step is one sampling step: Anthropic's connector runs several inside one
  request and lists them in `usage.iterations`; a response that does not report them counts
  as one step, so the steps are then a lower bound. This is what to read to see what a
  question costs in time and steps (see "The step budget" and "Prompt caching" below);
- the same outcomes, tokens, calls and answer sizes per UTC day (400 days kept);
- `today`: questions and tokens counted against `CHAT_DAILY_LIMIT` and
  `CHAT_DAILY_TOKENS`, with the provider and model.

It never keeps the question, the answer, tool arguments or results, or an address. A
tool name is kept only when it looks like a MapleStats tool (lower case, digits and
underscores); anything else, which a prompt could steer the model into, counts as
`other`. `CHAT_USAGE_STATS=0` turns the route off.

The counts are in memory unless `CHAT_USAGE_STATS_FILE` names a JSON file on a
persistent volume: then they are read at startup, saved every minute and at shutdown,
and a save adds this process's new counts to the file, so the old and new revisions
running together during a deploy both count. On Azure, `docker.yml`'s
`deploy-chat-azure` job mounts the `chat/` folder of the Azure Files storage the MCP
server already uses at `/data/chat`, and nothing else of the share (added once, with a
PATCH of the app's template; later deploys find it) and sets
`CHAT_USAGE_STATS_FILE=/data/chat/stats.json`. If the deploy identity may not attach
the storage, the job warns and the counts stay in memory; its last step prints
`persisted` from `/stats`.

## Guards

The endpoint is public and every call costs money. Defaults, all overridable by
environment variable: 20 questions per address per hour (`CHAT_RATE_PER_HOUR`), 500
per day in total (`CHAT_DAILY_LIMIT`), 1,000 characters per user message,
16,000 per assistant reply, 120,000 per conversation, a 512 KiB request body,
8 user turns per conversation, 4,000 output tokens per model call, a step budget per
question (next section), and 3,000,000 tokens per day in total (`CHAT_DAILY_TOKENS`:
input plus output tokens, cached input included, summed from the usage of every model
call on both backends). The question caps count questions, not cost: on the Anthropic
path the connector passes tool results to the model uncut, so one question can use far
more input tokens than its text suggests. The token budget is checked before each
request (a spent budget answers 429 with a message) and grows after each model call, so
the request that crosses it still finishes.

### The step budget

A question is bounded by requests to the model, and on the Anthropic path one request is
not one model call: Anthropic's MCP connector runs the tool loop on its own side, takes
up to about 10 model steps inside a single request, and ends the request with
`pause_turn` when it reaches that limit, and this app then resumes it. The old default of
12 requests therefore allowed about 120 model steps for one question (a vague question
made 17 tool calls over 93 to 158 s).

- `CHAT_MAX_TOOL_STEPS` (Anthropic path, default **2**, was 12): the first request plus
  one resume, so about 20 model steps at most. The resume is the last request, and its
  system prompt gets a wrap-up instruction: do not call any more tools, answer now with
  the figures already in hand, say plainly what could not be got. If that request still
  ends in `pause_turn`, or writes no answer, the visitor gets the step-limit message ("I
  could not finish within the demo's tool-call limit. Try a narrower question..."). A
  budget of 1 has no resume, so it has no wrap-up: the first request is never told to
  stop calling tools. The first request's prompt says only that the model has a small
  budget of steps and should put independent calls in the same step.
- `CHAT_MAX_TOOL_ROUNDS` (`openai` path, default **12**, unchanged): there this app runs
  the loop, and a round is one model call plus its tool calls, so 12 rounds are at most
  12 model steps, fewer than the 20 above. A lower number would leave no room for the
  plan, a search and a data call, which follow one another, before the answer. The last
  round gets the same wrap-up instruction; a tool call asked for in it is not run, and
  the answer is the step-limit message.

Before changing either number, read `per_answer` in `/stats` to see what questions
actually take.

### Prompt caching

`CHAT_PROMPT_CACHE=1` (also `true`, `yes` or `on`; default off) puts
`cache_control: {"type": "ephemeral"}` (the 5-minute cache) on the system prompt, sent as
a list of one text block, and on the `mcp_toolset` entry of the Anthropic request. The
cached prefix is then the tool list plus the system prompt, about 1,800 tokens (the three
tool definitions are about 1,460 and the prompt about 360), above Haiku 5.5's 512-token
minimum; a shorter prefix is silently not cached. Cache reads cost a tenth of the input
price and writes 1.25 times it (Anthropic's prompt-caching page for Haiku 5.5 at the
5-minute TTL: $0.01 and $0.125 per million tokens, against $0.10 for plain input), and
the tokens count as `cache_read` and `cache_write` in `/stats` and against the daily
token budget, as before. The wrap-up instruction goes in a second system block after the
cached one, so the cached prefix is the same on every request. With the flag off the
request has no cache fields at all.

It is off; to test it in a separate environment, ask one question twice within
five minutes and read `/stats`. `tokens.cache_write` should grow on the first and
`tokens.cache_read` on the second. Anthropic's pages do not say whether the connector
reuses the cache between the steps of its own tool loop, so `cache_read` on the first
question is also worth a look. The MCP beta header stays `mcp-client-2025-11-20`.
Anthropic also lists `mcp-client-2026-09-15`, which records the server's tool list in
`mcp_tool_listing` blocks and lets a toolset pin it with `tools`; it is not used here, so
that a problem with it cannot hide a result about caching.

All these counters live in memory and reset whenever the service restarts (a deploy,
or a free instance waking from sleep), so they are not a hard cap. **The real
backstop is a spend limit on the API key's workspace** (Anthropic Console, or the
provider's dashboard): set one, and keep the key in a workspace of its own.

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

With proxy headers trusted, `CHAT_CLIENT_IP_HEADER` names a header the outermost
proxy sets to the caller's own address, read before `X-Forwarded-For`. It defaults
to `CF-Connecting-IP` when `RENDER` is set, because Cloudflare fronts onrender.com
and the rightmost `X-Forwarded-For` entry there may be a shared edge address that
puts many callers in one bucket (the MCP server does the same with
`MAPLE_CLIENT_IP_HEADER`). When the header is missing or is not an IP address, the
`X-Forwarded-For` rule applies. Set it to an empty string to turn it off.

The page is sent with a full Content-Security-Policy: scripts only from this origin,
the two pinned cdnjs files (which also carry Subresource Integrity hashes) and the
page's own inline script, allowed by its SHA-256 hash. The hash is computed at
startup from `static/index.html`, which is then served from memory, so editing the
page needs no hand-copied hash, only a restart. Styles allow `'unsafe-inline'` for
the page's `<style>` block; images only from this origin and `data:`; `fetch` only
to this origin; no framing. Every response also carries
`X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin`.
Model text is sanitised with DOMPurify, which drops images and opens links in a new
tab with `rel="noopener noreferrer"`.

Conversation limits can be set with `CHAT_MAX_MESSAGE_CHARS`,
`CHAT_MAX_ASSISTANT_CHARS`, `CHAT_MAX_CONVERSATION_CHARS` and `CHAT_MAX_BODY_BYTES`.
Messages must alternate between user and assistant, starting and ending with user.
