from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.elections_financial_returns import client
from maplestats_mcp.modules.elections_financial_returns.schemas import (
    CandidateSearchResult,
    ElectionList,
    FinancialReturnPart,
)

Act = Literal["after_2019", "2015_2019", "2007_2014", "2004_2006"]


@tool
async def elections_financial_returns_list_elections(
    act: Act = "after_2019", lang: Literal["en", "fr"] = "en"
) -> ElectionList:
    """List general elections and by-elections available for a candidate
    financial-return search under a given Canada Elections Act period.

    act is the Canada Elections Act period: after_2019 (default),
    2015_2019, 2007_2014 or 2004_2006. lang="fr" returns the portal's
    French election labels; the ids are the same in both languages.

    Use for: finding the election_id to pass into
    elections_financial_returns_search_candidates or
    elections_financial_returns_get_financial_return_part; discovering
    recent or upcoming by-elections not yet known by name.
    Keywords: elections canada, election list, by-election, general
    election, candidate, political financing, act period, election id,
    writ, campaign return.
    Mots-clés : élections canada, liste des élections, élection partielle,
    élection générale, candidat, financement politique, période de la
    loi, identifiant d'élection, bref, rapport de campagne.
    """
    return await client.list_elections(act=act, lang=lang)


@tool
async def elections_financial_returns_search_candidates(
    election_id: str,
    act: Act = "after_2019",
    last_name: str = "",
    first_name: str = "",
    party_id: str = "-1",
    province_id: str = "-1",
    district_id: str = "-1",
    return_status: Literal["submitted", "amended"] = "submitted",
    offset: int = 0,
    limit: int = 300,
    lang: Literal["en", "fr"] = "en",
) -> CandidateSearchResult:
    """Search federal election candidates on Elections Canada's Political
    Financing portal, returning each match's client_id, party, and
    electoral district for use with
    elections_financial_returns_get_financial_return_part.

    An unknown election_id is NotFound. The portal returns every match at
    once (about 1,900 candidates in a general election); page with offset
    and limit (at most 300) while has_more is true. lang="fr" returns the
    French party and district names.

    Use for: finding a specific candidate's internal id before pulling
    their campaign financial return; browsing candidates by party or
    province for one election; discovering valid party_id/province_id
    values via the result's available_parties/available_provinces.
    Keywords: elections canada, candidate search, political financing,
    campaign return, client id, party, electoral district, province,
    financial disclosure.
    Mots-clés : élections canada, recherche de candidats, financement
    politique, rapport de campagne, identifiant, parti, circonscription,
    province, divulgation financière.
    """
    return await client.search_candidates(
        election_id,
        act=act,
        last_name=last_name,
        first_name=first_name,
        party_id=party_id,
        province_id=province_id,
        district_id=district_id,
        return_status=return_status,
        offset=offset,
        limit=limit,
        lang=lang,
    )


@tool
async def elections_financial_returns_get_financial_return_part(
    candidate_client_id: str,
    part: str,
    election_id: str,
    act: Act = "after_2019",
    return_status: Literal["submitted", "amended"] = "submitted",
    lang: Literal["en", "fr"] = "en",
) -> FinancialReturnPart:
    """Retrieve one part of a federal election candidate's official
    Complete Financial Return -- declaration, contributions received,
    loans, expenses, transfers, or bank reconciliation.

    part is one of: "1" (Declaration), "2A" (Contributions Received),
    "2B" (Operating Loans), "2C" (Contributions Returned), "2D"
    (Transfers Received), "2E" (Other Cash Inflows), "2F" (Summary of
    Inflows), "3A" (Campaign Expenses), "3B" (Litigation/Personal
    Expenses), "3C" (Summary of Outflows), "4" (Non-Monetary
    Transfers), "5" (Unpaid Loans and Claims), "6" (Bank
    Reconciliation). candidate_client_id comes from
    elections_financial_returns_search_candidates for the same
    election_id; a candidate who did not run in that election is
    NotFound. lang="fr" downloads the French report, whose section and
    field names are French (DONNÉES_DÉTAIL, Nom_de_famille_du_candidat);
    part_label stays English.

    Use for: auditing a candidate's campaign expenses or donors; the
    declared official agent; unpaid claims or loans; bank
    reconciliation totals; any line item from an official candidate
    financial return filed under the Canada Elections Act.
    Keywords: elections canada, campaign finance, financial return,
    candidate expenses, contributions received, official agent,
    election spending, political financing, donor, campaign loan.
    Mots-clés : élections canada, financement de campagne, rapport
    financier, dépenses de candidat, contributions reçues, agent
    officiel, dépenses électorales, financement politique, donateur,
    prêt de campagne.
    """
    return await client.get_financial_return_part(
        candidate_client_id,
        part,
        election_id=election_id,
        act=act,
        return_status=return_status,
        lang=lang,
    )
