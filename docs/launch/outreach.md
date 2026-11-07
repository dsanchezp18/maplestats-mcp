# Outreach messages

*Drafts. Nothing has been sent. Placeholders are in square brackets; no contact details were looked up.*

Each message assumes the blog post is live; replace [blog post link] before sending. The context for each recipient comes from the Notion page's "Dissemination and launch outreach" and "Canadian data ecosystem relationships" sections.

---

## 1. cansim maintainers

**To:** [cansim maintainers: name(s) and channel, e.g. a GitHub discussion or email]
**Subject:** MapleStats MCP, and how it uses cansim

Hello [name], I hope you are well.

I am an economist, and I have built MapleStats MCP, an open-source MCP server that lets AI assistants read Canadian public data from the source: Statistics Canada's WDS tables and vectors, the Census, public use microdata, the Bank of Canada, CMHC and a long list of federal, provincial and municipal sources. It went public with version 0.4.8: [blog post link].

I am writing because cansim is part of how it works. When the server returns Statistics Canada data, its `reproduce_code` tool writes the R script that fetches the same data outside the assistant, and for StatCan tables and vectors that script uses `get_cansim()` and `get_cansim_vector_for_latest_periods()`. The aim is that someone can find a series through an assistant and then move to an ordinary R workflow without starting over.

Two requests, if you have time. First, I would value your view on whether the generated cansim code follows the package's intended usage; the builder is in `src/maplestats_mcp/modules/reproduce/builders.py`. Second, if you think it would help cansim users, I would be glad to have it mentioned wherever you list related tools. It is okay if neither is possible.

Thank you for cansim. Much of how MapleStats treats Statistics Canada data was learned from it.

Regards,
Daniel Sánchez Pazmiño
https://github.com/dsanchezp18/maplestats-mcp

---

## 2. MountainMath

**To:** [Jens von Bergmann / MountainMath: channel]
**Subject:** MapleStats MCP: CMHC data and a request for feedback

Hello Jens, I hope you are well.

I have released MapleStats MCP, an open-source MCP server that gives AI assistants read-only access to Canadian public data, with a citation on every figure: [blog post link]. Your work shaped several parts of it. The CMHC tools read the Housing Market Information Portal and CMHC's Excel data tables, and when I designed them I looked at how your packages handle CMHC data. For Beyond 20/20 tables that only exist as IVT files, the server returns an R snippet that uses canivt, since that is the only tool I know of that reads them. The README's acknowledgements credit you and your co-authors.

I would value your technical feedback, especially on the CMHC and Census parts, where I expect you know the traps better than I do. If you find it useful for the same Canadian-data audience your packages serve, I would also appreciate help sharing it. It is okay if you don't have time for either.

Regards,
Daniel S.

*Note for Daniel: Jens von Bergmann also co-maintains cansim, so messages 1 and 2 may reach the same person. Consider sending one combined message, or sending the cansim one to the other maintainers.*

---

## 3. OSI Data Analyst Network

**To:** [Data Analyst Network organizer: name]
**Subject:** Proposed session: MapleStats MCP, an AI access layer for Canadian public data

Hi [name],

I would like to propose a session for the Data Analyst Network on MapleStats MCP, an open-source tool I built that lets AI assistants pull Canadian public data straight from the source: Statistics Canada tables and Census data, Labour Force Survey and other public use microdata, the Bank of Canada, CMHC, the Alberta Economic Dashboard and Open Alberta, and many federal and provincial sources.

The session would be practical rather than promotional: the access problem it addresses, a few live analyst workflows (finding the right table, pulling a series with its citation, getting R or Python code that reproduces the pull), and the mistakes it is built to catch, such as constant versus current dollars or an economic-family median reported as a household median. I would also cover its limits honestly, including where the assistant can still pick the wrong table. About [30-45] minutes with questions.

I am also exploring a presentation to the Edmonton Data Society. If the network is open to it, we could invite them to the same session, which would save both groups a separate event. Happy to discuss.

The launch write-up is here: [blog post link].

Thanks,
Daniel

*Note for Daniel: the tool is a personal project, not a Government of Alberta product. Check whether the session needs any internal approval or a disclaimer before proposing it.*

---

## 4. Edmonton Data Society

**To:** [Edmonton Data Society: organizer name and channel]
**Subject:** Talk proposal: MapleStats MCP, Canadian public data for AI assistants

Hello [name], I hope you are well.

I am an Edmonton-based economist, and I would like to offer a talk to the Edmonton Data Society on MapleStats MCP, an open-source server I built that gives AI assistants (Claude, ChatGPT, Cursor and others) read-only access to Canadian public data, with a citation on every figure: Statistics Canada, the Bank of Canada, CMHC, federal agencies, the provincial statistics bureaus, and the open-data portals, including the City of Edmonton's.

The talk would show the problem it addresses (Canadian data spread across many institutions and interfaces), a few live workflows, and how I tested it against other servers on a 53-question benchmark, including where it did not win. The write-up is here: [blog post link].

One option to consider: I am also proposing the same session to the Data Analyst Network at [OSI, full name], and if venue is a constraint, a joint session there might work for both groups. If you would rather hold it separately, that is fine too.

Regards,
Daniel Sánchez Pazmiño

*Note for Daniel: the City of Edmonton portal is in the Socrata module (`socrata/constants.py`), and Edmonton police, transit and EPCOR water quality have their own modules. "Edmonton-based" is my assumption; change it if it is wrong.*

---

## 5. Vancouver data group

**To:** [group name to confirm; the Notion page mentions the Vancouver Data Visualization Group] [organizer name and channel]
**Subject:** Virtual talk proposal: MapleStats MCP

Hello [name], I hope you are well.

I would like to offer a virtual talk to [group name] on MapleStats MCP, an open-source server I built that lets AI assistants read Canadian public data from the source, with a citation on every figure. It covers Statistics Canada, the Bank of Canada, CMHC, BC Stats, DriveBC, BC's environmental monitoring data, the BC Transit timetables, the City of Vancouver's open-data portal and many other federal and provincial sources.

For a [visualization / data] audience, I would focus on getting from a question to a reproducible dataset: the assistant finds the series, the server returns it with its source, and a generated R or Python script pulls the same data again for charting. The browser demo also draws a chart and a sourced table under each answer. About [30-45] minutes over video, at a time that suits the group. The write-up is here: [blog post link].

Regards,
Daniel Sánchez Pazmiño

---

## 6. Natural Resources Canada (Torben)

**To:** Torben [surname, channel]
**Subject:** MapleStats MCP is live

Hi Torben,

[One line on how you know each other, if useful.]

I wanted to share MapleStats MCP with you now that it is public: [blog post link]. It is an open-source server that lets AI assistants read Canadian public data from the source, with a citation on every figure. Several NRCan sources are in it: the Canadian Wildland Fire Information System (hotspots, fire danger and weather stations), the National Burned Area Composite, mineral production and Earthquakes Canada, along with Statistics Canada, the Bank of Canada and ECCC.

If you or your colleagues try it, I would especially like to know whether the NRCan tools describe the data the way your team would, and what is missing. It is free to use at https://mcp.maplestats.danielstats.io/mcp, with no account needed.

Regards,
Daniel

*Note for Daniel: I listed the NRCan sources from the README's coverage table (`nrcan_*`, `cwfis_`, `nrcan_nbac_`, `earthquakes_`). Adjust to whichever is closest to Torben's own work.*

---

## 7. SFU Economics

**To:** [SFU Economics: communications contact or faculty contact, name and channel]
**Subject:** MapleStats MCP: an open-source tool for Canadian economic data

Hello [name], I hope you are well.

[One sentence on your connection to the department, e.g. degree and year.] I am writing to share a project that may interest the department and its students: MapleStats MCP, an open-source server that lets AI assistants read Canadian public data directly from Statistics Canada, the Bank of Canada, CMHC and many federal and provincial sources, with a citation on every figure and the R, Python, Stata or Julia code that reproduces each data pull. It is free to use and needs no installation. The write-up is here: [blog post link].

I built it with MA students and researchers in mind: the people who need a Canadian figure they can cite and a script they can put in a replication package. I also tested it against other Canadian data servers on a 53-question benchmark and published the results with their limitations.

If the department would consider featuring it, for example in a profile like the ones it has run for other economics initiatives, I would be glad to provide whatever is useful: a short description, a demo, or a conversation. It is okay if this is not a fit.

Regards,
Daniel Sánchez Pazmiño
