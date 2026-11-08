# Outreach messages

*Drafts. Nothing has been sent. Placeholders are in square brackets; no contact details were looked up.*

Each message assumes the blog post is live; replace [blog post link] before sending. The context for each recipient comes from the Notion page's "Dissemination and launch outreach" and "Canadian data ecosystem relationships" sections.

The cansim and MountainMath messages are now one message to Jens von Bergmann, who co-maintains cansim. A separate note to the other cansim maintainers would repeat the same question, so it was dropped.

---

## 1. Jens von Bergmann (MountainMath: cansim, CMHC, canivt)

**To:** [Jens von Bergmann: channel]
**Subject:** How MapleStats MCP uses cansim and canivt, and one question

Hello Jens, I hope you are well.

Your packages are part of how MapleStats MCP works, so I wanted you to hear about it from me. It is an open-source server that lets AI assistants fetch Canadian public data with its source attached: [blog post link].

When it returns Statistics Canada tables or vectors, its `reproduce_code` tool writes an R script that fetches the same data with `get_cansim()` or `get_cansim_vector_for_latest_periods()`, so someone who finds a series through an assistant can carry on in an ordinary R workflow. For Beyond 20/20 tables that only exist as IVT files, it returns a snippet that reads them with canivt. The CMHC tools read the Housing Market Information Portal and CMHC's Excel data tables, and I looked at how your packages handle CMHC data when I designed them. There is also a small R client now (`clients/r`) that returns results as tibbles with the citation attached.

My question: does the generated cansim code follow the package's intended usage? The builder is in `src/maplestats_mcp/modules/reproduce/builders.py`. For vectors it asks for the latest N periods, because `get_cansim_vector()` alone returns each vector's whole history.

Thank you for cansim and canivt. The README's acknowledgements credit you and your co-authors.

Regards,
Daniel S.

---

## 2. OSI Data Analyst Network

**To:** [Data Analyst Network organizer: name]
**Subject:** Proposed session: MapleStats MCP, an AI access layer for Canadian public data

Hi [name],

Much of an analyst's week goes into finding the right Statistics Canada table and checking that a figure matches its source. I would like to propose a session for the network on a tool I built for that step: MapleStats MCP, an open-source server that lets AI assistants pull Canadian public data from the publisher, with the citation attached. The launch write-up is here: [blog post link].

Every figure comes back with its table and vector, reference period, release date, StatCan's quality flags and the licence, and its `check_answer` tool re-reads the figures an answer cites before the answer goes out, reporting only the problems. The session would cover a few live workflows: finding the right table, pulling a series with its citation, getting R or Python code that reproduces the pull, and tabulating Labour Force Survey public use microdata, with weights, on the hosted server. I would also show the mistakes it is built to catch, such as constant versus current dollars or an economic-family median reported as a household median, and where it falls short: the 2006-2016 census data tables are not available, because Statistics Canada's host for them blocks automated requests. About [30-45] minutes with questions.

Would the network be open to hosting it?

Thanks,
Daniel

*Note for Daniel: the tool is a personal project, not a Government of Alberta product. Check whether the session needs any internal approval or a disclaimer before proposing it. The earlier draft also offered a joint session with the Edmonton Data Society; raise it in a follow-up if the network says yes.*

---

## 3. Edmonton Data Society

**To:** [Edmonton Data Society: organizer name and channel]
**Subject:** Talk proposal: MapleStats MCP, Canadian public data for AI assistants

Hello [name], I hope you are well.

Edmonton's own data (the City's open-data portal, Edmonton Police Service, ETS and EPCOR water quality) can now be queried from an AI assistant, alongside Statistics Canada, the Bank of Canada and CMHC. I am an Edmonton-based economist, and I built the open-source server that does it, MapleStats MCP. I would like to offer the society a talk on it.

The talk would show the problem it addresses (Canadian data spread across many institutions and interfaces), a few live workflows on Edmonton questions, and how I tested it against other servers on a 61-question benchmark, including where it did not win. On the 53 questions every server was asked, it answered 91.8% correctly over three runs, with no invented StatCan table or vector ids. The write-up is here: [blog post link].

Would the society have room for it at an upcoming event?

Regards,
Daniel Sánchez Pazmiño

*Note for Daniel: the City of Edmonton portal is in the Socrata module (`socrata/constants.py`), and Edmonton police, transit and EPCOR water quality have their own modules (`eps_`, `ets_`, `epcor_`). "Edmonton-based" is my assumption; change it if it is wrong. If OSI agrees to a joint session, mention it here instead.*

---

## 4. Vancouver data group

**To:** [group name to confirm; the Notion page mentions the Vancouver Data Visualization Group] [organizer name and channel]
**Subject:** Virtual talk proposal: from a question to a sourced, chartable dataset

Hello [name], I hope you are well.

For most charts, the slow part is getting a clean dataset with a source you can cite. I would like to offer [group name] a virtual talk on that step, using MapleStats MCP, an open-source server I built that lets AI assistants fetch Canadian public data from the publisher.

For BC questions it reads BC Stats, DriveBC, BC's environmental monitoring data and the City of Vancouver's open-data portal, along with Statistics Canada, the Bank of Canada and CMHC. The talk would follow one question through: the assistant finds the series, the server returns it with its source, and a generated R or Python script pulls the same data again for charting. The chat demo on the website also draws a chart and a sourced table under each answer. About [30-45] minutes over video. The write-up is here: [blog post link].

Would a session like this work for the group, at a time that suits you?

Regards,
Daniel Sánchez Pazmiño

---

## 5. Natural Resources Canada (Torben)

**To:** Torben [surname, channel]
**Subject:** NRCan wildfire and earthquake data in MapleStats MCP

Hi Torben,

[One line on how you know each other, if useful.]

Several NRCan sources can now be queried from AI assistants through MapleStats MCP, an open-source server I built: the Canadian Wildland Fire Information System (hotspots, fire danger, fire-weather stations and the national situation reports), the National Burned Area Composite, Earthquakes Canada and the annual mineral production statistics. The write-up is here: [blog post link]. It is free to use at https://mcp.maplestats.danielstats.io/mcp, with no account needed.

If you or your colleagues try it, I would like to know whether the NRCan tools describe the data the way your team would.

Regards,
Daniel

*Note for Daniel: the sources are from `docs/ROADMAP.md` (`cwfis_`, `nrcan_nbac_`, `earthquakes_search`, `nrcan_minerals_`). NRCan energy use and geospatial (`nrcan_energy_use_`, `nrcan_geo_`) are also in; swap them in if they are closer to Torben's own work.*

---

## 6. SFU Economics

**To:** [SFU Economics: communications contact or faculty contact, name and channel]
**Subject:** MapleStats MCP: an open-source tool for Canadian economic data

Hello [name], I hope you are well.

[One sentence on your connection to the department, e.g. degree and year.] Students in the department regularly need a Canadian figure they can cite, and often the same figure for the United States or Europe to compare against. I built an open-source tool for that: MapleStats MCP, a server that lets AI assistants read data directly from Statistics Canada, the Bank of Canada, CMHC and many federal and provincial sources, with OECD and Eurostat series as comparators. Every figure comes with its citation and the R, Python, Stata or Julia code that reproduces the pull. It is free to use and needs no installation. The write-up is here: [blog post link].

I built it with MA students and researchers in mind, and tested it against other Canadian data servers on a 61-question benchmark: on the 53 questions every server was asked, it answered 91.8% correctly over three runs. The results are published with their limitations.

Would the department consider featuring it, for example in a profile or newsletter item? I can provide a short description or a demo.

Regards,
Daniel Sánchez Pazmiño
