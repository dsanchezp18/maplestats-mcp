from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.canadabuys import client
from maple_data_mcp.modules.canadabuys.schemas import (
    AwardSearchResult,
    NoticeDetail,
    TenderSearchResult,
)

Category = Literal["goods", "services", "construction", "services_related_to_goods"]


@tool
async def canadabuys_search_tenders(
    query: str = "",
    notice_set: Literal["open", "new"] = "open",
    category: Category | None = None,
    region: str | None = None,
    buyer: str | None = None,
    limit: int = 25,
    lang: Literal["en", "fr"] = "en",
) -> TenderSearchResult:
    """Search federal tender notices (bid opportunities) on CanadaBuys.
    notice_set "open" covers every tender still accepting bids; "new"
    covers only those posted today. query matches title, description,
    UNSPSC commodity, reference and solicitation numbers (all terms must
    appear). region and buyer are case-insensitive substring filters on
    region of delivery and contracting organization. Results are sorted
    soonest-closing first.

    Use for: finding open government contracts to bid on; listing what a
    department is currently buying; checking closing dates for a tender.
    Keywords: CanadaBuys, tender, bid opportunity, RFP, RFQ, solicitation,
    procurement, government contract, PSPC, open tenders, closing date.
    Mots-clés: AchatsCanada, appel d'offres, occasion de soumission,
    demande de propositions, sollicitation, approvisionnement, marché
    public, SPAC, appels d'offres ouverts, date de clôture.
    """
    return await client.search_tenders(
        query,
        notice_set=notice_set,
        category=category,
        region=region,
        buyer=buyer,
        limit=limit,
        lang=lang,
    )


@tool
async def canadabuys_search_awards(
    query: str = "",
    supplier: str | None = None,
    buyer: str | None = None,
    category: Category | None = None,
    fiscal_year: str | None = None,
    limit: int = 25,
    lang: Literal["en", "fr"] = "en",
) -> AwardSearchResult:
    """Search federal contract award notices on CanadaBuys for one fiscal
    year (April-March, e.g. "2025-2026"; defaults to the current year,
    earliest 2022-2023). supplier and buyer are case-insensitive substring
    filters on the winning supplier's legal name and the contracting
    organization. Returns contract amount, dates, and supplier location,
    newest first.

    Use for: who won a government contract; which contracts a company has
    been awarded; how much a department spent on a procurement.
    Keywords: CanadaBuys, contract award, award notice, supplier, vendor,
    winning bidder, contract value, federal spending, procurement, PSPC.
    Mots-clés: AchatsCanada, attribution de contrat, avis d'attribution,
    fournisseur, soumissionnaire retenu, valeur du contrat, dépenses
    fédérales, approvisionnement, marché public, SPAC.
    """
    return await client.search_awards(
        query,
        supplier=supplier,
        buyer=buyer,
        category=category,
        fiscal_year=fiscal_year,
        limit=limit,
        lang=lang,
    )


@tool
async def canadabuys_get_notice(
    reference_number: str,
    fiscal_year: str | None = None,
    lang: Literal["en", "fr"] = "en",
) -> NoticeDetail:
    """Get the full detail of one CanadaBuys notice by reference number
    (e.g. "MX-443841357513"), including the untruncated description. Looks
    in open tenders first, then award notices for the current and
    previous fiscal years, or only fiscal_year when given.

    Use for: reading the full text of a tender or award found by a search.
    Keywords: CanadaBuys, notice detail, tender detail, award detail,
    reference number, solicitation, full description, procurement notice.
    Mots-clés: AchatsCanada, détail de l'avis, appel d'offres, avis
    d'attribution, numéro de référence, sollicitation, description
    complète, avis d'approvisionnement.
    """
    return await client.get_notice(reference_number, fiscal_year=fiscal_year, lang=lang)
