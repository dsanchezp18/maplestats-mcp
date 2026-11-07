# LinkedIn post

*Draft. Not posted. Replace [blog post link] once the post is live.*

---

I have spent the last few months building MapleStats MCP, an open-source server that lets an AI assistant (Claude, ChatGPT, Cursor and others) read Canadian public data directly from the source: Statistics Canada, the Bank of Canada, CMHC, dozens of federal agencies, the provincial statistics bureaus and the open-data portals, in English and French. Every figure comes back with its citation, and the server says so plainly when a figure is not published instead of letting the assistant guess. It is free to use at https://mcp.maplestats.danielstats.io/mcp, or locally with `uvx maplestats-mcp`.

On my own benchmark of 53 questions, each asked three times, it averaged 48.7 correct answers per run against 42.7 for the next server, with no hallucinated answers. Most of that gap comes from sources other servers do not cover; on Statistics Canada's regular tables the servers are close. The write-up, with the caveats, is here: [blog post link]. You can also try it in a browser at https://chat.maplestats.danielstats.io. If you work with Canadian data, I would like to hear what it gets wrong.
