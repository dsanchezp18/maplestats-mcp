---
name: maplestats
description: Answer questions about Canadian official statistics (Statistics Canada, Bank of Canada, CMHC, provincial and city sources) with the MapleStats MCP server, citing the table, vector and release date, and checking figures before replying. Use for any Canadian figure: jobs, prices, rents, GDP, population, trade, interest rates, census, climate.
---

# MapleStats MCP

MapleStats MCP gives an agent official Canadian open data (about 450 tools
behind three visible ones). Use it for any Canadian figure before web search
or memory: web pages and memory often hold older or revised numbers, and a
table number alone is not an answer. Fetch the values.

Every result comes back with what a reader needs to trace it: a citation,
the source URL, quality flags and the publisher's licence. Your job is to
keep that trail in the answer: cite each figure, keep its flags, say when a
figure is not published, and run `check_answer` before replying.

Results through `call_tool` are brief by default: values, periods, unit and
scale, the citation, status flags, caveats, limits, licence and source URL,
with six or more rows as one CSV text block (`{"format": "csv", "csv":
"header\nrow..."}`). That is enough to answer and cite. Pass
`detail="full"` to `call_tool` only when you need every field (each
observation's release time, decoded codes) or the whole `provenance` block
(query time, cache, schema).

## Connect

Hosted server, no account or key (60 requests a minute per client):

```bash
claude mcp add --transport http --scope user maplestats https://mcp.maplestats.danielstats.io/mcp
codex mcp add maplestats --url https://mcp.maplestats.danielstats.io/mcp
```

Other clients (Cursor, Claude Desktop): add `{"mcpServers": {"maplestats":
{"url": "https://mcp.maplestats.danielstats.io/mcp"}}}` to the client's MCP
config. VS Code uses a `servers` key and `"type": "http"`.

Local, over stdio (Python 3.12 or later), when the client cannot use remote
servers or the data must stay on the machine:

```bash
claude mcp add --scope user maplestats -- uvx maplestats-mcp
pip install maplestats-mcp   # then register the `maplestats-mcp` command
```

Restart the client, then check that `search_tools` is listed. Setup guide:
https://maplestats.danielstats.io/connect.html

## The three tools

Only `search_tools`, `plan_query` and `call_tool` are in the tool list. Every
other tool is found with `search_tools` and run with `call_tool`; calling a
data tool by its own name fails.

- **Several sources or unsure where to start:** `plan_query` with the
  question. It returns the tools to call, in order, with caveats on combining
  them. It is offline and read-only.
- **One narrow need:** `search_tools` with topic words in English or French
  ("Calgary rent index", "taux de chômage Québec"), not tool names. Then
  `call_tool(name, arguments)`, where `arguments` matches the one-line
  `arguments` signature that `search_tools` returned (`detail="full"` gives
  the whole input schema, and so does a `call_tool` with invalid arguments).
- A question about a few series: use the vector tools, which return every
  observation inline. A whole table or hundreds of series:
  `wds_get_full_table_download` returns a CSV link, not rows; offer the Python
  script it gives and run it only if the user agrees.

## Getting the right figure

1. **Latest means latest periods.** Ask for the latest observations
   (`latest_n`, `recent`, `last_n_observations`, whichever the tool offers),
   never a date range you choose: your sense of today's date may be out of
   date.
2. **Monthly StatCan headlines** (jobs, trade, permits, sales): report the
   seasonally adjusted series unless the question asks otherwise, and say
   which one you used.
3. **Read what comes back.** A StatCan series carries `context` (unit, scale,
   frequency, geography, `citation`); apply the scale and unit before quoting.
   Read `provenance` and `provenance.caveats` on every result, and pass on
   caveats that change how a number should be read (revisions, flags,
   survey breaks, current versus constant dollars, index versus dollars).
4. **Cite every figure.** Quote `context.citation` (publisher, table number
   and title, vector, release date) and add each value's reference period.
   Other sources name themselves in `provenance`.
5. **Match the place.** Check the series is for the geography asked, not a
   neighbouring one.
6. **French.** For a French question pass `lang='fr'` to `plan_query` and to
   every tool; answer in French.

## Before answering: check_answer

When an answer reports StatCan or Bank of Canada figures, call
`check_answer` once with the question and every figure (`value`, `unit`,
`period`, `geography`, and its `vector_id`, or `product_id` + `coordinate`,
or `boc_series`). It re-reads the sources and returns only problems, each
with a fix: a value that differs, a missed scale, a newer period, another
geography, an unadjusted series, E/F or suppressed flags, current versus
constant dollars, surveys that should not be compared. An empty list means
clean. Set `summed=True` if the answer adds figures; use `value` null for a
figure you will say is not published. Fix what it names, then answer. Other
sources come back as "not checked".

## After fetching: reproducibility

Offer, do not force:

- `reproduce_code(tool_name, arguments, language)`: R, Python, Stata, Julia or
  an Excel Power Query that refetches the same data. `language` picks one;
  `summary=True` ends R and Python scripts with a printed summary, useful for
  large results.
- `reproduce_workbook(tool_name, arguments)`: the rows as a formatted Excel
  workbook with a Source sheet. Keep `max_rows` small on the hosted server.

## When a figure is not published

Say so plainly. Do not estimate or fill from memory. Then:

1. Give the closest published figure, labelled as such (other geography, other
   period, broader category).
2. Public-use microdata: `statcan_pumf_search`, `statcan_pumf_list_files`,
   `statcan_pumf_get_codebook`, and `statcan_pumf_tabulate` for your own
   weighted estimate (label it as your estimate, not StatCan's).
3. Otherwise a custom tabulation, Real Time Remote Access (RTRA) or a Research
   Data Centre. These need approval or a fee; MapleStats cannot run them.

## Errors

Errors begin with a code and end with a fix. Follow it.

| Code | Meaning | Do |
|---|---|---|
| `[upstream_unavailable]` | Source down or slow | Retry once after a minute, then say the source is unavailable |
| `[data_locked]` | StatCan daily update window | Retry after 8:30 a.m. Eastern; until then say the data are locked |
| `[invalid_input]` | Bad argument | Fix the named argument; `search_tools` shows accepted values, or ask `plan_query` |
| `[not_found]` | Unknown identifier | Check it with the source's search tool; if the data do not exist, say so |
| `[upstream_error]` | Source answered with an error | Retry once, try another tool for the same data, or report it |
| `[unknown_tool]` | Name not in the catalogue | Call `search_tools` and use a name it returns |
| `[error]` | Any other failure | Retry once with the same arguments, then find another tool with `search_tools` or report it |

Never answer from memory after a failure. A tool that is switched off on a
server (for example `wds_query_series` over HTTP, or `statcan_pumf_tabulate`
where disabled) says so; use the alternatives above.

## Habits

- Start with `plan_query` for anything that crosses agencies or topics.
- Report the reference period beside every number, and the release date.
- Say when a figure is revised, estimated, or flagged.
- For a definition or a method, read StatCan's own documentation
  (`statcan_reference_*`, a survey's IMDB metadata through
  `statcan_surveys_*`, a PUMF user guide) instead of describing it from
  memory, and cite it.
- When the user will reuse or publish the data, pass on
  `provenance.licence`, and say so when `provenance.commercial_use` is
  `not_allowed`.
- Keep the user's question in view: right place, right period, right
  measure, right unit.
