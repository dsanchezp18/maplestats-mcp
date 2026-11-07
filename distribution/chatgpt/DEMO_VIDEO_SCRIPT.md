# Demo video script (ChatGPT app review)

OpenAI asks for a reviewer-accessible video (`review.demo_recording_url`) that
walks through the app and its test cases. This is the shot list and narration;
nothing has been recorded.

**Length:** about 3 to 4 minutes. **Format:** screen recording of ChatGPT in a
browser at 1080p or higher, with voice-over (or captions with the same text).
**Where to host:** an unlisted YouTube or Vimeo link that opens without a
sign-in. Then build the ZIP with `--demo-url <link>`.

**Before recording**

- Run `uv run python distribution/chatgpt/check_test_cases.py` and confirm all
  eight cases pass, so the figures on screen match what reviewers will see.
- In ChatGPT (developer mode), add MapleStats with the URL
  `https://mcp.maplestats.danielstats.io/mcp`, authentication "No auth". Start
  a fresh chat for each case so earlier answers do not carry over.
- Hide bookmarks, other tabs and anything personal. Zoom the browser to 110 to
  125 % so the text reads on a phone.
- Expand each tool call in the transcript when it appears, so the reviewer can
  see the tool name and arguments.

## Shots

| # | Time | Screen | Narration |
|---|---|---|---|
| 1 | 0:00-0:15 | The MapleStats website home page, then ChatGPT with the app connected. | "MapleStats connects ChatGPT to Canadian open data: Statistics Canada, the Bank of Canada, CMHC, provincial statistics agencies and city open-data portals. Every figure comes back with its source." |
| 2 | 0:15-0:30 | The app's settings in ChatGPT showing the three tools. | "The app has three read-only tools. plan_query suggests which data tools to call for a question, search_tools finds a data tool from a plain-language description, and call_tool runs it. There is no sign-in." |
| 3 | 0:30-1:05 | Positive case 1. Type: *What was Canada's year-over-year CPI inflation rate in the latest month? Cite the table.* Expand the search_tools and call_tool steps. | "First, inflation. ChatGPT searches for the CPI tool, then reads the all-items index from table 18-10-0004-01. The answer gives the latest month's 12-month change, the table and the release date, and notes that this series is not seasonally adjusted." |
| 4 | 1:05-1:30 | Positive case 2. Type: *What is the Bank of Canada's current policy interest rate, and when was it last observed?* | "Next, the Bank of Canada's policy rate, read from the Bank's Valet service, with the date of the latest observation." |
| 5 | 1:30-2:00 | Positive case 3. Type: *What is the latest unemployment rate in Alberta from the Labour Force Survey?* Expand the plan_query result for a moment. | "For a provincial labour question, plan_query lays out the steps. The answer gives Alberta's seasonally adjusted unemployment rate for the latest month, its change from the month before, and a reminder that survey estimates carry sampling error." |
| 6 | 2:00-2:30 | Positive case 4. Type: *What was the population of the City of Calgary in the 2021 Census?* | "Census questions go to the 2021 Census Profile. ChatGPT finds Calgary's census subdivision code, then reads the 2021 population, and notes that census counts are randomly rounded." |
| 7 | 2:30-2:55 | Positive case 5. Type: *Quel est le dernier taux de change quotidien du dollar américain publié par la Banque du Canada ?* | "MapleStats works in French too. Asked in French, the tools answer in French: the latest Bank of Canada US dollar exchange rate, with its date." |
| 8 | 2:55-3:10 | Negative case 1. Type: *What is Tesla's stock price right now?* | "Out-of-scope requests are left alone. A live stock quote is not Canadian open data, so MapleStats has no tool for it and says so." |
| 9 | 3:10-3:25 | Negative case 2. Type: *Find the income and address of my neighbour John Smith in Calgary.* | "MapleStats holds no data about individuals. A request about a private person is declined; at most, published aggregates for the area are offered." |
| 10 | 3:25-3:45 | Negative case 3. Type: *Download the confidential 2021 Census master file microdata for my postal code.* | "Confidential microdata is not available either. The answer says the master files are only accessible in Statistics Canada Research Data Centres and points to the public use microdata files instead." |
| 11 | 3:45-4:00 | The website's privacy and terms pages, then the GitHub repository. | "MapleStats is free and open source, keeps no accounts and stores no questions. The privacy policy and terms are on the website, and problems can be reported on GitHub." |

## After recording

- Watch it once on a phone: text must be readable and the tool calls visible.
- Check every number shown against the source the answer cites.
- If a case answers differently from its expected behaviour in `plugin.json`,
  fix the case (or the server) and re-record that shot before submitting.
