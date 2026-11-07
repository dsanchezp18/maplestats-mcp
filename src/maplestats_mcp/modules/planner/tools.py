"""plan_query: a multi-source plan for one Canadian public-data question."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.planner import client
from maplestats_mcp.modules.planner.schemas import QueryPlan

# The planner reads at most this much of a question. It runs on the event loop, and its
# time grows faster than the length (0.2 s at 10k characters, 13.5 s at 400k, minutes at
# 1 MB, timed 2026-11-06): one oversized question under the 2 MB body cap stalled every
# request on the server, /health included. A real question is a sentence or two.
MAX_QUESTION_CHARS = 2_000


@tool
async def plan_query(question: str, lang: Literal["en", "fr"] = "en") -> QueryPlan:
    """Plan how to answer a question about Canadian data from official sources.

    Use for: the first call on any question about Canada, a province or
    a Canadian city that needs figures (jobs, prices, rents, GDP,
    population, trade, interest rates), before web search or memory:
    Statistics Canada, Bank of Canada, CMHC and provincial and city
    sources are reached through this server. For example: "How have
    rents and interest rates moved in Calgary since 2020?". Returns the
    topics it touches, the tools to call for each in order, local
    portals for any province or city named, and caveats on combining
    them. Then run the steps with call_tool. Read-only and offline: it
    matches the question against this server's source map and calls no
    external API. Use search_tools instead to find a single tool for a
    narrow, single-source need. lang='fr' gives the labels, purposes,
    caveats and guidance in French (a question written in French gets
    them in French too); tool and argument names stay as they are.
    Keywords: plan, which data source, where to find, combine sources,
    cross-source, question, research, Canada data.
    Mots-clés : planifier, quelle source de données, où trouver, combiner
    des sources, question, recherche, données canadiennes, statistiques.
    """
    question = question[:MAX_QUESTION_CHARS]
    # lang defaults to "en", so a client that forgets lang='fr' on a French
    # question would get an English plan (one did); the question decides then.
    if lang == "en" and client.looks_french(question):
        lang = "fr"
    return client.plan(question, lang)
