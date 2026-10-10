# Connectors Directory submission notes

Portal: https://claude.ai/directory/manage (Submit new, MCP connector).

## Values for the portal

| Field | Value |
|---|---|
| Server URL | `https://maplestats-mcp.onrender.com/mcp` |
| Authentication | None (public open data; no accounts, no keys) |
| Privacy policy URL | `https://maplestats.danielstats.io/privacy.html` |
| Documentation URL | `https://maplestats.danielstats.io/connect.html` |
| Reads or writes | Hosted tools read public data; Excel exports return base64. Local stdio exports can save files and declare that behaviour. |
| Data handling | Public data from Statistics Canada and other Canadian open-data publishers; no personal health data; no sponsored content |

## Test account and access instructions (Test & launch step)

No account, credentials or setup are needed: the server is public and has no
authentication.

1. In Claude, add a custom connector with the URL above (Settings, Connectors,
   Add custom connector). Leave any OAuth fields empty.
2. The server exposes three tools: `search_tools`, `call_tool` and
   `plan_query`. `search_tools` finds a data tool from a plain-language query;
   `call_tool` runs it by name; `plan_query` lists the tools to call, in order,
   for a question that spans several sources.
3. Try these prompts, in order:
   - "What was Canada's unemployment rate in the latest Labour Force Survey?"
     (`search_tools`, then `call_tool` with a Statistics Canada table tool.)
   - "Compare the Bank of Canada policy rate with Canadian CPI inflation since
     2022." (`plan_query`, then `call_tool` for each step.)
   - "Quel est le taux de chômage au Québec ?" (French queries are supported.)
   - "Give me an R script that reproduces that table." (`call_tool` with
     `reproduce_code`.)
   - "Export that table as an Excel workbook." (`call_tool` with
     `reproduce_workbook`; the hosted server returns the file as base64.)
4. Limits: 60 requests per minute per client. The first request after an idle
   period can take up to a minute while the host wakes.

## Review checklist

- [x] Every tool has a title and behaviour hints. The hosted endpoint is read-only; local workbook exports and their `call_tool` wrapper declare file writes.
- [x] Tool names are at most 64 characters.
- [x] Public HTTPS endpoint, Streamable HTTP transport.
- [x] Privacy policy page, English and French.
- [ ] Run every tool once from Claude as a custom connector (the portal asks
      you to confirm).
- [ ] Icon, support contact and company details ready.
