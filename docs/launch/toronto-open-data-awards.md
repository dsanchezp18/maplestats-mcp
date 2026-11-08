# Toronto Open Data Awards 2026: drafts

> **DRAFT. Nothing here has been sent or submitted.** Daniel reviews,
> edits and sends both pieces himself. Submissions close 2026-12-04
> ([call](https://open.toronto.ca/toronto-open-data-awards-2026-call-for-submissions/)).
> Category: Open Data Infrastructure ("backend work, automation, data links,
> or AI/ML"; judged on "a clear technical problem, a strong or innovative
> solution, open code and documentation, and potential for reuse or scale").

Eligibility as the call states it: the project uses at least one dataset
from open.toronto.ca, is active or completed in 2026, is freely accessible,
and has not won before. The call does not say whether the maker must live in
Toronto, hence the email. Items marked [confirm] are facts to check before
sending.

## 1. Email to opendata@toronto.ca (DRAFT, not sent)

**To:** opendata@toronto.ca
**Subject:** Open Data Awards 2026: eligibility of a project maintained outside Toronto

Hello, I hope you are well.

I maintain MapleStats MCP, a free, open-source server that lets AI
assistants query Canadian open data and cite the source of every figure
(https://github.com/dsanchezp18/maplestats-mcp). It reads several
open.toronto.ca datasets through the CKAN API, including RentSafeTO
building evaluations, Neighbourhood Profiles, short-term rental
registrations and DineSafe. I would like to enter it in the Open Data
Infrastructure category.

I live and work in Edmonton. Could you please confirm whether a project
maintained from outside Toronto is eligible, provided it uses Toronto's
open data?

I also have a question about automated access. The portal's robots.txt
allows `/api/` but disallows `/dataset/*/resource/*/download/*`, so my
server reads only DataStore tables and never downloads files. The "For
Developers" code on each dataset page, however, suggests downloading files
from a resource's `url` attribute. Is a tool that downloads a single file
when a user asks for it (for example, a TTC GTFS zip or a 311 yearly file)
acceptable to the City, or should it keep to the API?

Thank you for your time.

Regards,
Daniel Sánchez Pazmiño

## 2. Award entry (DRAFT, not submitted)

**Project:** MapleStats MCP
**Category:** Open Data Infrastructure
**Links:** code https://github.com/dsanchezp18/maplestats-mcp (MIT
licence), website and documentation https://maplestats.danielstats.io/,
package https://pypi.org/project/maplestats-mcp/, Toronto worked example
https://github.com/dsanchezp18/maplestats-mcp/tree/main/docs/examples/toronto
**Funding:** grassroots, built on my own time with no grant or company
behind it [confirm before submitting].

### Problem

AI assistants are now a common way to ask questions about a city, and they
answer from memory or from whatever web page they find. For Toronto that
means a renter asking how their building scored on RentSafeTO, or a
journalist comparing neighbourhoods, gets a figure with no source and no
date. The City publishes the answer on open.toronto.ca, but an assistant
cannot read a CKAN DataStore table, page through 7,000 rows, or know that
the 2016 profile writes "525,835" as text and marks sub-items with leading
spaces.

### Approach

MapleStats MCP is a Model Context Protocol server: one connection gives
Claude, ChatGPT, Cursor and other MCP clients typed access to Canadian open
data from 88 modules (Statistics Canada, the Bank of Canada, CMHC and
federal, provincial and city portals). For Toronto it offers two layers:

1. The whole open.toronto.ca catalogue through the CKAN API (`ckan_*` tools
   with `portal="toronto"`): search, dataset details and any DataStore table.
2. Five tools for the Toronto datasets people ask about most, returning tidy
   rows: Neighbourhood Profiles for one of the 140 neighbourhoods (census
   2016 to 2001), RentSafeTO evaluation scores by building, ward or property
   type, short-term rental registrations counted by ward, property type or
   FSA, and DineSafe inspections.

Every result carries the dataset's citation line, the DataStore resource id
and the Open Government Licence – Toronto with its attribution statement.
Any call can be turned into an R, Python, Stata, Julia or Excel Power Query
script that fetches the same data directly from the City's API
(`reproduce_code`), so a figure can be checked without trusting the AI.

The server reads Toronto's portal only through the API that its robots.txt
allows. It does not download files, and the short-term rental tool returns
counts, never operators' addresses.

### Open code and documentation

The code is MIT-licensed on GitHub, with typed response models, tests
against recorded City responses, a live smoke test of every Toronto tool and
a public changelog. The website documents all 455 tools in English and
French. `docs/findings/municipal-sources.md` records what was checked on the
City's portal (terms, robots.txt, table quirks) and why the 311 requests,
TTC GTFS and 2021 neighbourhood profiles are not read.

### Reuse and scale

Toronto is one of ten CKAN portals the same code serves, next to 86 ArcGIS
Hub and five Socrata portals; adding a city on one of these platforms is a
configuration entry. The server runs locally from PyPI or from the hosted
endpoint https://mcp.maplestats.danielstats.io/mcp, and anyone can fork it.

### Evidence: one question answered end to end

*Do Toronto neighbourhoods where more households rent have lower-scoring
apartment buildings?* The worked example reads three City tables through
the DataStore API (RentSafeTO evaluations since 2023, the 140 neighbourhood
boundaries and the 2016 Neighbourhood Profiles), places 3,459 of 3,608
evaluated buildings in their neighbourhood (149 have no coordinates) and
compares each neighbourhood's mean score with its 2016 renter share. Across
the 122 neighbourhoods with five or more buildings, the rank correlation is
−0.16: more renters goes with slightly lower scores, and the relation is
weak. The tenure figures are from 2016 and the scores from 2023 to 2026, so
this is a description, not a causal estimate. The script re-fetches
everything and runs in one command
(`uv run docs/examples/toronto/rentsafe_by_neighbourhood.py`).

### Note on a related project

The 2025 honourable mention in this category went to a CKAN MCP server
[confirm its name and author]. MapleStats differs in scope (Statistics
Canada, federal and provincial sources beside the City's portal), in its
curated Toronto tools, and in the reproducible scripts behind every figure.
This paragraph is optional; cut it if the form has no room.
