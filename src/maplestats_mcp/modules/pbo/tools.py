"""MCP tools for the Office of the Parliamentary Budget Officer."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.pbo import client
from maplestats_mcp.modules.pbo.schemas import PboPublication, PboSearchResult, PublicationType

Lang = Literal["en", "fr"]


@tool
async def pbo_search_publications(
    query: str = "",
    types: list[PublicationType] | None = None,
    page: int = 1,
    lang: Lang = "en",
) -> PboSearchResult:
    """Search Parliamentary Budget Officer (PBO) publications.

    Use for: finding PBO's independent cost estimates of bills, motions and
    budget measures, legislative costing notes, economic and fiscal outlooks,
    reports on the Estimates, federal spending, program costs, tax changes
    and the public service. With a `query`, PBO's own search ranks results;
    without one, the newest come first. `types` keeps some kinds: RP report,
    NT note, LEG legislative costing note, ES cost estimate, OA additional
    analysis, LIBARC archived (2008-2021). 15 per page. Pass a result's id to
    pbo_get_publication for its tables.
    Keywords: Parliamentary Budget Officer, PBO, cost estimate, costing
    note, fiscal cost, bill costing, economic and fiscal outlook, federal
    budget analysis, Estimates, fiscal sustainability.
    Mots-clés : directeur parlementaire du budget, DPB, estimation des
    coûts, note d'évaluation, coût financier, projet de loi, perspectives
    économiques et financières, budget fédéral, budget des dépenses,
    viabilité financière.
    """
    return await client.search_publications(query, types=list(types or []), page=page, lang=lang)


@tool
async def pbo_get_publication(publication_id: str, lang: Lang = "en") -> PboPublication:
    """Read one PBO publication with its tables and text.

    Use for: getting the numbers in a PBO costing or report: five-year cost
    estimates of a measure, projected revenues and spending, economic
    projections (GDP, unemployment, interest rates), Estimates breakdowns.
    `publication_id` is PBO's id, e.g. 'LEG-2526-012-S' or 'RP-2627-002-S',
    from pbo_search_publications. Tables come from PBO's structured PBOML
    document: 'table' ones have rows keyed by column label, 'html' ones
    rows of cells, 'kvlist' ones key/value pairs, each with sources and
    notes. Costing notes since 2021 and most reports since 2025 have them;
    older publications return has_structured_content false and a PDF link.
    Charts are images without data. Reuse is personal and non-commercial,
    unaltered, crediting PBO.
    Keywords: PBO tables, cost estimate figures, costing results, fiscal
    impact, revenue projection, spending projection, economic projection.
    Mots-clés : tableaux du DPB, estimation des coûts, incidence
    financière, projection des revenus, projection des dépenses,
    projection économique.
    """
    return await client.get_publication(publication_id, lang=lang)
