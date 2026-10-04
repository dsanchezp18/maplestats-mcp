"""MCP tools for CBSA border wait times."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.cbsa import client
from maplestats_mcp.modules.cbsa.schemas import BorderWaitTimes

Lang = Literal["en", "fr"]


@tool
async def cbsa_border_wait_times(
    province: str = "",
    crossing: str = "",
    direction: Literal["both", "canada_bound", "us_bound"] = "both",
    lang: Lang = "en",
) -> BorderWaitTimes:
    """Current wait times at Canada-U.S. land border crossings (CBSA).

    Use for: how long the line is right now at the Peace Bridge, Ambassador
    Bridge, Gordie Howe Bridge, Blue Water Bridge, Rainbow Bridge, Lacolle,
    Pacific Highway, Douglas (Peace Arch), Coutts, Emerson and about 20 other
    crossings, for travellers and commercial trucks, entering Canada or
    the United States. Each crossing comes with its own update time; the
    file is refreshed every few minutes and cached here for two minutes.
    `province` is the Canadian side (ON, QC, BC, NB, MB, SK, AB or a name);
    `crossing` matches the office or town ('windsor', 'peace bridge');
    `direction` keeps only Canada-bound or U.S.-bound lanes. CBSA posts
    Canada-bound waits; most U.S.-bound lanes read 'not_reported'. For
    trends, the historical files are open.canada.ca datasets (see
    `historical_data`). Open Government Licence - Canada.
    Keywords: border wait times, border crossing delay, CBSA, Canada US
    border, Peace Bridge wait, Ambassador Bridge, Lacolle, Pacific Highway,
    border lineup, crossing into the United States.
    Mots-clés : temps d'attente à la frontière, ASFC, poste frontalier,
    frontière canado-américaine, délai à la douane, file d'attente
    frontière, pont Ambassador, Lacolle, traverser aux États-Unis.
    """
    return await client.border_wait_times(
        province=province, crossing=crossing, direction=direction, lang=lang
    )
