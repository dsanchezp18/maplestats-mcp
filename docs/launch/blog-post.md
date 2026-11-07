# One MCP to Rule Them All

*Draft for maplestats.danielstats.io. Not published.*

*Three MCPs for the statisticians under the sky, seven for the data portals in their halls of stone...*

Okay, perhaps not quite.

The Model Context Protocol (MCP) made it easy to connect an AI assistant to a data source, and the Canadian data community responded the way it always does: one connector at a time. There is an MCP server for Statistics Canada, another for the Bank of Canada, and a few for the open-data portals. Housing data live somewhere else. The Census has its own quirks, researchers work with public use microdata files, and some tables still sit in Beyond 20/20 files that only one R package can read.

Each of these tools is useful on its own. Together, they rebuild an old Canadian data problem in a new form: too many places to look, too many interfaces to learn, and too many decisions to make before you can ask a fairly simple question.

MapleStats MCP takes the opposite approach. It is one MCP server for Canadian open data.

## What it is

MapleStats gives an AI assistant (Claude, ChatGPT, Cursor, or any other MCP client) typed, read-only access to Canadian public data through a single server, in English and French. The idea is to centralize the interface, not the data. MapleStats does not copy anything into a database of its own. It reads from the publishers' own APIs and files when you ask, and every result says where it came from.

Statistics Canada is at the centre: data tables and vectors, the 2021 Census Profile, public use microdata (codebooks and weighted tables), merchandise trade by commodity, The Daily and the release calendar. Canadian data do not end at Statistics Canada, though, so the same server also reaches the Bank of Canada, CMHC, Environment and Climate Change Canada, Health Canada, IRCC, NRCan and a few dozen other federal agencies, the provincial and territorial statistics bureaus, and the federal, provincial, territorial and municipal open-data portals. As of version 0.4.8, that is 399 tools in 78 modules.

An assistant does not see 399 tools at once. It sees three: `search_tools` finds the right tool from a plain-language query, `call_tool` runs it, and `plan_query` turns a question that crosses agencies into an ordered plan. The point is that the person asking should not need to know beforehand whether the answer sits in a WDS table, a Valet series, a CMHC data table, a CKAN resource or a Census profile.

## How to use it

The hosted server needs no installation, account or key:

```
https://mcp.maplestats.danielstats.io/mcp
```

In Claude, add it as a custom connector (Settings, Connectors, Add custom connector). In Claude Code:

```bash
claude mcp add --transport http --scope user maplestats https://mcp.maplestats.danielstats.io/mcp
```

The Connect page on the website has the steps for ChatGPT, Cursor, VS Code, Codex and Microsoft 365 Copilot. The hosted server runs on Azure in Canada Central and allows each client 60 requests a minute.

If you would rather keep everything on your own machine, it is on PyPI and runs locally over stdio:

```bash
uvx maplestats-mcp
```

`pip install maplestats-mcp` works too (Python 3.12 or later).

## Built around the mistakes people actually make

I am an economist who works with official statistics, and most of the errors I see in analysis built on them are not arithmetic. They are reading errors: constant dollars taken for current dollars, an economic-family median reported as a household median, the Bank Rate read as the overnight target, a December-over-December change compared with an annual average. An AI assistant makes the same mistakes, only faster and more confidently.

So MapleStats spends most of its effort on context rather than on raw access. Every Statistics Canada series comes with a citation (table, vector, release date, reference period, unit and geography, with a link to the official table), and quality flags such as "use with caution" or "too unreliable to be published" are spelled out on every value. Where a well-known trap applies, the result says so in plain language, and each of those cautions rests on the publisher's own documentation. When a figure is not published, or a period has not been released yet, the server says no and points to the closest figure that does exist, instead of letting the assistant fill the gap.

Two tools let you check the assistant's work. `check_answer` takes the Statistics Canada and Bank of Canada figures an answer cites, re-reads them from the source, and returns only the problems: a different value, a missed scale factor, a newer period, another geography, an unadjusted series, each with a fix. `reproduce_code` writes the R, Python, Stata or Julia script (or an Excel Power Query) that pulls the same data straight from the publisher, so the analysis does not depend on the assistant having been right. For Statistics Canada tables in R, it uses `cansim`.

## Testing it: the Maple Test

I built a benchmark to find out, the Maple Test, and ran its second version in early November. It asks 48 questions in two halves. The core half (24 questions) uses Statistics Canada's regular tables and Bank of Canada series, where most Canadian data servers compete. The beyond half (24) uses the 2021 Census, ECCC climate and river-flow data, the World Bank, the BIS, Health Canada's Drug Product Database and IRCC's Express Entry rounds. Five analyst questions, built from an ordinary analyst's working week, were added after the first runs and are graded on their own. Every value in the answer key was read from the publisher's own API, never through MapleStats. Eleven arms (ten servers and one with no data tool) answered every question three times with Claude Sonnet 5.5, and I then reviewed all 1,923 answers by hand, one question at a time, with the arm's name hidden.

MapleStats averaged 48.7 correct answers of 53 per run, against 42.7 for the next server (Pipeworx) and 36 for the one after (OpenMCP). It gave no hallucinated answers, made no false claims about the data and cited no table or vector that does not exist. Of the Statistics Canada vectors and Bank of Canada series it cited, 94% held a figure its answer stated.

That headline needs two qualifications. First, the gap comes almost entirely from the beyond half. On the core half the servers are close: every tool-using arm but one scored between 19.3 and 22.7 of 24, and MapleStats was at the top of that range, tied with Pipeworx. The beyond sources were chosen from what MapleStats covers, and most other servers do not claim to cover them, so that half measures scope as much as quality. A StatCan-only server that declines a climate question is doing its job. Second, MapleStats was the most expensive arm per question (USD 0.116), because its results carry more text. Cheap arms were cheap partly because they declined more often.

After the runs I changed MapleStats with these questions in view, and that version scored 52.3. By the test's own rule, a fix tuned on the questions cannot be scored on them, so I do not treat that number as a result. Measuring whether accuracy rose in general needs a fresh question set, and that work has started: eight new questions on release dates, written and keyed before any server saw them, where MapleStats scored 7.3 of 8 per run (the other servers have not been run on them yet). The full tables, the grading rules and every re-grade with its reason are in the repository, along with a count of which way the hand review moved each arm.

## Try it without installing anything

The chat demo at <https://chat.maplestats.danielstats.io> answers questions with a small model (Claude Haiku 5.5) connected to the hosted server. Under each answer there is a chart, a table you can download as CSV, and a Sources tab with the table numbers, vectors, release dates and cautions behind it. That panel is built from what the tools returned, not from the model's text, so it shows the published figures even when the answer misquotes them. It is a beta, it is rate-limited, and its answers can be wrong; it is there so you can see the server work before connecting your own assistant.

## What it does not cover

Some sources are not there, and the roadmap records why for each one. CAPP's Statistics Handbook, Petrinex and Payments Canada were not built, and CanadaBuys and OpenParliament.ca were removed, because their terms or hosts do not permit automated access. The City of Hamilton's portal and Niagara Open Data answer automated requests with a Cloudflare challenge. The 2006 to 2016 census data tables were removed because Statistics Canada's host for them blocks automated clients (the 2021 Census Profile and the WDS tables remain). CREA's MLS Home Price Index is links and terms only, with no values, because CREA allows private, non-commercial analysis only. Statute text is out of scope: legislation is not data this server carries. MapleStats can tabulate public use microdata, but it cannot run a custom tabulation, RTRA or an RDC request; when a figure needs one, it says so.

The larger limitation is the one every tool of this kind shares. MapleStats returns values as published, but the assistant using it can still pick the wrong table, geography or period, and what it writes is AI-generated. For anything you would publish, check a few figures against the source and re-run the data with `reproduce_code`. MapleStats is an independent project, not affiliated with or endorsed by Statistics Canada, the Bank of Canada, CMHC or any other publisher, and each dataset keeps its own licence: credit the publisher, not MapleStats.

## Acknowledgements

MapleStats owes its architecture to [EcuDataMCP](https://github.com/DweskZ/EcuDataMCP), the MCP server for Ecuador's open data that I help maintain with DweskZ and its other contributors. Its approach to Canadian data owes a lot to the R developers who got there first: Jens von Bergmann (mountainMath) and his co-authors, including Dmitry Shkolnik, Thierry Warin (statcanR) and Valentin Lucet (rgovcan).

The code is MIT-licensed at <https://github.com/dsanchezp18/maplestats-mcp>, and the website is <https://maplestats.danielstats.io>. If a tool gives you a wrong figure, or a source you need is missing, please open an issue. That is the most useful thing you can send me.

One MCP, for Canadian public data. As much of it as I can reasonably connect.
