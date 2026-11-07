# Launch drafts

Drafts for review. Nothing here has been published, posted or sent.

| File | What it is |
| :-- | :-- |
| [`blog-post.md`](blog-post.md) | "One MCP to Rule Them All", for the website |
| [`linkedin-post.md`](linkedin-post.md) | Short announcement |
| [`outreach.md`](outreach.md) | One message each: cansim, MountainMath, OSI Data Analyst Network, Edmonton Data Society, Vancouver group, NRCan (Torben), SFU Economics |

## Where each number comes from

| Figure | Source |
| :-- | :-- |
| 399 tools in 78 modules; coverage and "not covered" list | `README.md` ("What it covers") |
| Version 0.4.8; Python 3.12 or later | `pyproject.toml`, `CHANGELOG.md` |
| Hosted URL, 60 requests a minute, Azure Canada Central | `README.md` |
| `check_answer` and `reproduce_code` behaviour; `cansim` and `canivt` in generated R | `README.md`; `src/maplestats_mcp/modules/reproduce/builders.py`; `src/maplestats_mcp/modules/borealis/client.py` |
| Maple Test v2: 48.7 of 53, 42.7 (Pipeworx), 36 (OpenMCP), core 19.3 to 22.7, 0 hallucinated, 0 false claims, 0 invented IDs, 94% precision, USD 0.116, 1,923 answers reviewed | `tests/maple_test/results_v2.md`, `tests/maple_test/README.md` |
| 52.3 in-sample; release questions 7.3 of 8 | `tests/maple_test/README.md` |
| Chat demo: Claude Haiku 5.5, Chart/Table/Sources panel built from tool results | `chat/README.md`, `docs/ROADMAP.md` |

## Open points for Daniel

- The post says "I am an economist who works with official statistics"; adjust if you want to name your role.
- The outreach messages carry placeholders in square brackets for names, channels and your connection to each recipient. No contact details were looked up.
- cansim and MountainMath may reach the same person (Jens von Bergmann co-maintains both); see the note under message 2.
- The Vancouver group is still to be confirmed; the Notion page mentions the Vancouver Data Visualization Group once.
- `docs/ROADMAP.md` says the Azure hosting is "covered by the sponsorship credits"; the Notion update of 2026-11-05 says it is self-funded. The drafts do not mention funding.
