from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.canadabuys import client
from maple_data_mcp.modules.canadabuys.schemas import (
    AwardSearchResult,
    BulkFileList,
    ContractSearchResult,
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


@tool
async def canadabuys_search_contracts(
    query: str = "",
    supplier: str | None = None,
    buyer: str | None = None,
    category: Category | None = None,
    min_value: float | None = None,
    fiscal_year: str | None = None,
    limit: int = 25,
    lang: Literal["en", "fr"] = "en",
) -> ContractSearchResult:
    """Search federal contract history (contracts awarded, including
    amendments) for one fiscal year, from 2009-2010 to the current year
    ("2009-jan-Mar" covers January to March 2009). Each contract's
    amendments are merged into one record with its original amount, total
    value, and amendment count, sorted by total value (largest first).
    supplier matches legal or standardized supplier name; buyer matches the
    contracting department; min_value filters on total contract value.

    Use for: historical federal contracts back to 2009; largest contracts
    a department signed; a company's federal contract history; sole-source
    (non-competitive) contracts and their justification.
    Keywords: CanadaBuys, contract history, contracts awarded, federal
    contracts, supplier, vendor, sole source, non-competitive, amendment,
    contract value, government spending, PSPC.
    Mots-clés: AchatsCanada, historique des contrats, contrats octroyés,
    marchés fédéraux, fournisseur, fournisseur unique, non concurrentiel,
    modification, valeur du contrat, dépenses gouvernementales, SPAC.
    """
    return await client.search_contracts(
        query,
        supplier=supplier,
        buyer=buyer,
        category=category,
        min_value=min_value,
        fiscal_year=fiscal_year,
        limit=limit,
        lang=lang,
    )


@tool
async def canadabuys_list_bulk_files(lang: Literal["en", "fr"] = "en") -> BulkFileList:
    """List CanadaBuys' whole-history and legacy bulk CSV downloads with
    their URLs, sizes, and last-modified dates: every tender notice from
    2009, award notices from 2012, and contract history from 2009 in one
    file each (57MB to over 800MB). These are links for offline analysis,
    not queried here; lang is a no-op because the files are bilingual.

    Use for: downloading the full CanadaBuys or pre-CanadaBuys (Buy and
    Sell) procurement history for research or bulk analysis.
    Keywords: CanadaBuys, bulk download, legacy, Buy and Sell, historical
    tenders, historical awards, contract history, full dataset, CSV.
    Mots-clés: AchatsCanada, téléchargement en bloc, Achatsetventes,
    appels d'offres historiques, attributions historiques, historique des
    contrats, jeu de données complet, fichier CSV.
    """
    return await client.list_bulk_files()
