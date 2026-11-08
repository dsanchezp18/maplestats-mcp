# Launch drafts

The blog post and the LinkedIn post are published. The outreach messages are still drafts: none has been sent.

| File | What it is |
| :-- | :-- |
| [`blog-post.md`](blog-post.md) | "One MCP to Rule Them All", for the website (published) |
| [`linkedin-post.md`](linkedin-post.md) | Short announcement (published) |
| [`outreach.md`](outreach.md) | Draft, one message each: Jens von Bergmann (cansim, CMHC, canivt), OSI Data Analyst Network, Edmonton Data Society, Vancouver group, NRCan (Torben), SFU Economics |
| [`toronto-open-data-awards.md`](toronto-open-data-awards.md) | Drafts, not sent: eligibility email to opendata@toronto.ca and the Open Data Infrastructure entry for the Toronto Open Data Awards 2026 (deadline 2026-12-04) |

## Where each number comes from

| Figure | Source |
| :-- | :-- |
| 399 tools in 78 modules at publication (457 tools in 89 modules on main now, from `scripts/build_site.py`); coverage and "not covered" list | `README.md` ("What it covers") |
| Version 0.4.8 in the published posts (the outreach drafts name no version); Python 3.12 or later | `pyproject.toml`, `CHANGELOG.md` |
| Hosted URL, 60 requests a minute, Azure Canada Central | `README.md` |
| `check_answer` and `reproduce_code` behaviour; `cansim` and `canivt` in generated R | `README.md`; `src/maplestats_mcp/modules/reproduce/builders.py`; `src/maplestats_mcp/modules/borealis/client.py` |
| Maple Test v2, as shares of questions answered correctly: MapleStats 91.8% of 53 (Nov. 3, comparable), Pipeworx 80.5%, OpenMCP 67.9% (both Nov. 3, not re-run), the other servers 22.0% to 58.5% (re-run Nov. 5 to 8); core 80.6% to 94.4% for every tool-using arm but statcan2; each share is correct answers over three runs divided by three times the questions (`results_v2.json`); 0 hallucinated, 0 false claims, 0 invented IDs, 94% precision, USD 0.116; 1,923 answers reviewed on Nov. 3 and 1,647 on Nov. 5 to 8, blinding imperfect | `tests/maple_test/results_v2.md`, `tests/maple_test/README.md` |
| In-sample MapleStats: 98.7% of 53 (`maplestats_after`), 98.1% of 53 and 79.2% of the 8 release questions (Nov. 5 to 8 run), 91.7% of the 8 release questions (Nov. 4) | `tests/maple_test/README.md` |
| Chat demo: Claude Haiku 5.5, Chart/Table/Sources panel built from tool results | `chat/README.md`, `docs/ROADMAP.md` |

## Open points for Daniel

- The published posts give raw scores ("48.7 correct answers of 53"); the site now gives the share of questions answered correctly. Lines to change in the live posts (`blog-post.md` and `linkedin-post.md` here are left as published):
  - Blog, "Testing it": "MapleStats averaged 48.7 correct answers of 53 per run, against 42.7 for the next server (Pipeworx) and 36 for the one after (OpenMCP)." becomes "Over three runs, MapleStats answered 91.8% of the 53 questions correctly, against 80.5% for the next server (Pipeworx) and 67.9% for the one after (OpenMCP)."
  - Blog: "every tool-using arm but one scored between 19.3 and 22.7 of 24" becomes "every tool-using arm but one answered between 80.6% and 94.4% of the 24 core questions correctly".
  - Blog: "that version scored 52.3" becomes "that version answered 98.7% correctly"; "where MapleStats scored 7.3 of 8 per run" becomes "where MapleStats answered 91.7% of the 8 release questions correctly over three runs", and "(the other servers have not been run on them yet)" becomes "(the other servers, run on them from November 5 to 8, answered 4.2% to 37.5% correctly)".
  - LinkedIn: "it averaged 48.7 correct answers per run against 42.7 for the next server" becomes "it answered 91.8% of the questions correctly over three runs, against 80.5% for the next server".
- The post says "I am an economist who works with official statistics"; adjust if you want to name your role.
- The outreach messages carry placeholders in square brackets for names, channels and your connection to each recipient. No contact details were looked up.
- The cansim and MountainMath messages are merged into one message to Jens von Bergmann, who co-maintains cansim.
- The Vancouver group is still to be confirmed; the Notion page mentions the Vancouver Data Visualization Group once.
- The Azure hosting is self-funded (Notion update of 2026-11-05); `docs/ROADMAP.md` now says so. The drafts do not mention funding.
