"""MCP tools for StatCan's Delta File bulk daily-update archive."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.delta import client
from maplestats_mcp.modules.statcan.delta.schemas import DeltaFileLink

Lang = Literal["en", "fr"]


@tool
async def statcan_delta_get_file_link(date: str, lang: Lang = "en") -> DeltaFileLink:
    """Get the Delta File download link for one date, confirming it exists.

    Use for: bulk-downloading every table/vector data and metadata
    update StatCan released on one business day, as a single ZIP --
    the preferred mechanism (per StatCan's own developer guidance) for
    large updates, rather than re-fetching individual tables one at a
    time. date is "YYYY-MM-DD". A Delta File only exists for business
    days that had a release (weekends and holidays will report
    exists=False); check exists before treating the url as
    downloadable. The ZIP carries both English and French metadata, so
    `lang` has no effect. Keywords: StatCan, delta file, bulk update,
    daily update, all tables, full refresh.
    Mots-clés : Statistique Canada, fichier delta, mise à jour en
    bloc, mise à jour quotidienne, tous les tableaux, actualisation
    complète.
    """
    del lang
    return await client.get_file_link(date)
