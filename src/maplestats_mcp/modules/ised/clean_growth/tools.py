"""MCP tools for the Clean Growth Hub's federal cleantech investment figures."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.ised.clean_growth import client
from maplestats_mcp.modules.ised.clean_growth.schemas import FederalInvestment

Lang = Literal["en", "fr"]


@tool
async def ised_clean_growth_get_federal_investment(lang: Lang = "en") -> FederalInvestment:
    """Get federal clean technology investment 2016-2024 (Clean Technology Data Strategy) as data.

    Use for: how much the federal government has committed to cleantech
    projects: total ($29 billion), number of agreements, median agreement,
    for-profit share, non-repayable share, and totals by purpose
    (development, business support, adoption); agreement value by year;
    share of agreements by province or territory; value by cleantech
    subsector; plus the page's methodology notes. The Clean Growth Hub
    publishes these only as a web page and PDF; this tool reads them into
    numbers (dollars, not billions). For project-level records, query the
    grants and contributions DataStore table named in records_resource_id
    with ckan_datastore_search(portal='federal'). lang picks English or
    French labels and notes; the numbers are the same.
    Keywords: clean technology, cleantech, federal investment, Clean
    Growth Hub, CTDS, green funding, grants and contributions, renewable
    energy, subsector, ISED, NRCan.
    Mots-clés : technologies propres, investissement fédéral, Carrefour de
    la croissance propre, stratégie de données, financement vert,
    subventions et contributions, énergie renouvelable, sous-secteur.
    """
    return await client.federal_investment(lang)
