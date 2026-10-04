"""MCP tools for the Office of the Parliamentary Budget Officer."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.pbo import client
from maplestats_mcp.modules.pbo.schemas import (
    Disposition,
    PboInformationRequest,
    PboInformationRequestList,
    PboPublication,
    PboSearchResult,
    PublicationType,
    RequestStatus,
)

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
    impact, revenue projection, spending projection, economic projection,
    Parliamentary Budget Officer.
    Mots-clés : tableaux du DPB, estimation des coûts, incidence financière,
    projection des revenus, projection des dépenses, projection économique,
    directeur parlementaire du budget, résultats de l'évaluation.
    """
    return await client.get_publication(publication_id, lang=lang)


@tool
async def pbo_search_information_requests(
    query: str = "",
    department: str = "",
    status: RequestStatus | Literal["open"] | None = None,
    disposition: Disposition | None = None,
    since: str = "",
    until: str = "",
    page: int = 1,
    lang: Lang = "en",
) -> PboInformationRequestList:
    """Search the register of information requests PBO sent to federal departments.

    Use for: what data the Parliamentary Budget Officer asked departments
    for, and whether they answered: all 1,100+ requests since 2008 with the
    department, request date, deadline, extension, status and outcome (all
    disclosed, disclosed in part, nothing disclosed, information does not
    exist). Counts by outcome, status and department come with every result,
    so it answers "how often did National Defence refuse PBO" or "which
    requests are overdue". `query` matches words in the request summary
    (English and French, accents ignored); `department` an acronym (FIN,
    DND, CRA, TBS) or part of a name; `status` 'open' keeps every pending
    request, and open ones carry days_past_deadline; `since`/`until` bound
    the request date (YYYY, YYYY-MM or YYYY-MM-DD). 25 per page, newest
    first. Pass an id to pbo_get_information_request for the letters. The
    first call in a session takes about 30 seconds while the whole
    register is read (the API ignores filters); it is then kept 6 hours.
    Keywords: Parliamentary Budget Officer, PBO information request,
    access to information, departmental disclosure, refused request,
    overdue request, government transparency, data request, PBO mandate.
    Mots-clés : directeur parlementaire du budget, DPB, demande
    d'information, communication de renseignements, refus de communiquer,
    demande en retard, transparence gouvernementale, ministère fédéral.
    """
    return await client.search_information_requests(
        query,
        department=department,
        status=status,
        disposition=disposition,
        since=since,
        until=until,
        page=page,
        lang=lang,
    )


@tool
async def pbo_get_information_request(request_id: str, lang: Lang = "en") -> PboInformationRequest:
    """Read one PBO information request with links to its letters.

    Use for: the details of one request from pbo_search_information_requests:
    department, dates, status, outcome and note, and the request letter and
    the department's replies (mostly PDF) in the requested language.
    `request_id` is PBO's number, e.g. 'IR0959', 'RI0929' or 'IR0080a'.
    The first request-register call in a session takes about 30 seconds:
    PBO's API cannot look a request up by its number and ignores filters,
    so all ~29 register pages are read at one per second, then kept for 6
    hours (later calls answer in under a second).
    Keywords: PBO information request, request letter, reply letter,
    departmental response, disclosure, Parliamentary Budget Officer,
    IR number, request details.
    Mots-clés : demande d'information du DPB, lettre de demande, lettre de
    réponse, réponse du ministère, communication, directeur parlementaire
    du budget, numéro de demande, détails.
    """
    return await client.get_information_request(request_id, lang=lang)
