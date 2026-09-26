"""plan_query: a multi-source plan for one Canadian public-data question."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.planner import client
from maplestats_mcp.modules.planner.schemas import QueryPlan


@tool
async def plan_query(question: str, lang: Literal["en", "fr"] = "en") -> QueryPlan:
    """Plan which sources answer a question that may span several agencies.

    Use for: the first call on a substantive question ("How have rents
    and interest rates moved in Calgary since 2020?"). Returns the
    topics it touches, the tools to call for each in order, local
    portals for any province or city named, and caveats on combining
    them. Then run the steps with call_tool. lang is accepted for
    consistency; the plan text is English.
    Keywords: plan, which data source, where to find, combine sources,
    cross-source, question, research, Canada data.
    Mots-clés : planifier, quelle source de données, où trouver, combiner
    des sources, question, recherche, données canadiennes, statistiques.
    """
    return client.plan(question)
