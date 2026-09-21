"""MCP tools for StatCan's Delta File bulk daily-update archive."""

from __future__ import annotations

from fastmcp.tools import tool

from maple_data_mcp.modules.statcan.delta import client
from maple_data_mcp.modules.statcan.delta.schemas import DeltaFileLink


@tool
async def statcan_delta_get_file_link(date: str) -> DeltaFileLink:
    """Get the Delta File download link for one date, confirming it exists.

    Use for: bulk-downloading every table/vector data and metadata
    update StatCan released on one business day, as a single ZIP --
    the preferred mechanism (per StatCan's own developer guidance) for
    large updates, rather than re-fetching individual tables one at a
    time. date is "YYYY-MM-DD". A Delta File only exists for business
    days that had a release (weekends and holidays will report
    exists=False); check exists before treating the url as
    downloadable. Keywords: StatCan, delta file, bulk update, daily
    update, all tables, full refresh.
    Mots-clés : Statistique Canada, fichier delta, mise à jour en
    bloc, mise à jour quotidienne, toutes les tables.
    """
    return await client.get_file_link(date)
